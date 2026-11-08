"""rav mock | run | explore | analyze | agent | up | eval | soft | spend. Each run writes runs/<id>/events.jsonl and report.json."""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import shutil
import tempfile
import time

from rav_contracts import POLICIES, TestRequest

from .commands import explore as explore_command, rule_responder
from .loop import auto_approve, fix_and_retest, robot_may_auto_approve, rule_planner, run_test
from .mock import mock_analyst, mock_system_1
from .model import DEFAULT_MODEL, MODELS
from .runlog import RunLog


def _print(report) -> None:
    print(f"{report.run_id}: {report.summary}")
    for f in report.findings:
        print(f"  {f.id} [{f.label}] {f.target}: {f.what_happened}")


def mock(args) -> None:
    from rav_cad import ParamsBackend

    # work on a copy so that a mock run never rewrites the Rev A file in the repo
    with tempfile.TemporaryDirectory() as tmp:
        params = shutil.copy(args.params, tmp)
        request = TestRequest(request_id=args.id, product="Test box (mock)", revision="A")
        analyst, cad = mock_analyst, ParamsBackend(params)
        if args.analyst == "onshape":
            analyst, cad = _onshape(args.tags)
        elif args.analyst == "local":
            analyst, cad = _local(args.tags if args.step else None, args.step, pathlib.Path(args.runs))
        elif args.analyst != "rules":
            from .analyst import cli_analyst, model_analyst
            analyst = cli_analyst if args.analyst == "cli" else model_analyst
        before, after = fix_and_retest(mock_system_1, request, analyst, cad, log_root=args.runs, policy=POLICIES[args.policy],
                                       parallel=args.analyst in ("onshape", "local"))
    _print(before)
    if after:
        _print(after)
        print(f"reward {before.reward.value:.2f} -> {after.reward.value:.2f}")


def _onshape(tags: str):
    """The Onshape analyst and backend, or a clear reason they can't run here (keys, the tag file, the network)."""
    try:
        from rav_cad.onshape.backend import OnshapeBackend
        from .analyst import make_onshape_analyst
        backend = OnshapeBackend(tags, require_approval=False)    # the harness approves through approve() and logs it
        backend.client.list_versions(backend.doc.did)               # fails fast on bad keys or no access
    except Exception as e:  # noqa: BLE001 - shown to the person running it
        raise SystemExit(f"--analyst onshape can't start: {type(e).__name__}: {e}\n"
                         "Fill in .env at the repo root (see .env.example) and the ids in the tag file, "
                         "or run with --analyst cli to use the CadQuery model instead.") from e
    return make_onshape_analyst(backend, tags), backend


APPLIANCE_SPEC = "subjects/appliance/cad/appliance.rev_a.yaml"


def _local(tags: str | None, step: str | None, runs: pathlib.Path):
    """The local CadQuery analyst and backend. The tested revision is `step` (a STEP assembly) with the product's tag
    file, or, with neither, our parametric appliance (tags made from its build, its feature code as references)."""
    from rav_cad.local import LocalCadBackend
    from .analyst import make_local_analyst
    out = runs / "local_out"
    if step:
        if not tags:
            raise SystemExit("--analyst local with --step needs the product's tag file (--tags)")
        backend = LocalCadBackend(tags, step, out_dir=out, require_approval=False)
    else:
        import yaml
        from rav_cad.generic import bench
        from rav_cad.local.backend import parametric_sources
        from rav_cad.parametric.build import build
        from rav_cad.parametric.spec import Spec
        built = build(Spec.load(APPLIANCE_SPEC))
        tags = str(pathlib.Path(tempfile.mkdtemp()) / "appliance.tags.yaml")
        pathlib.Path(tags).write_text(yaml.safe_dump(bench.tags_dict(built)))
        backend = LocalCadBackend(tags, bench.parts(built), out_dir=out, require_approval=False, product="appliance",
                                  sources=parametric_sources(built))
    return make_local_analyst(backend, tags), backend


def analyze(args) -> None:
    """The CAD step alone: each finding of a recorded run goes to the analyst; nothing is approved or applied."""
    from .analyze import analyze_run

    if args.analyst == "onshape":
        analyst, cad = _onshape(args.tags)
    elif args.analyst == "local":
        analyst, cad = _local(args.tags if args.step else None, args.step, pathlib.Path(args.runs))
    else:
        from rav_cad import ParamsBackend
        from .analyst import cli_analyst, model_analyst, rule_analyst
        analyst = {"rules": rule_analyst, "cli": cli_analyst, "model": model_analyst}[args.analyst]
        work = tempfile.mkdtemp()
        cad = ParamsBackend(shutil.copy(args.params, work))     # a copy: analysis never rewrites the repo's file
    out = analyze_run(args.run, analyst, cad, log_root=args.runs, only=args.finding or None, parallel=not args.serial)
    for row in json.loads(pathlib.Path(out).read_text()):
        f, cause, patch = row["finding"], row["cause"], row["patch"]
        print(f"\n{f['id']} {f['target']}: {f['what_happened']}\n  cause ({cause['confidence']:.2f}): {cause['root_cause']}")
        if patch:
            where = (patch.get("source") or {}).get("url") or patch["file"]
            edits = [e["summary"] for e in patch.get("edits") or []] or [
                f"{c['param']}: {c['from_value']} -> {c['to_value']}" for c in patch["changes"]]
            print("  patch: " + "; ".join(edits) + f"\n  on: {where}")
        else:
            print("  no CAD fix proposed")
    print(f"\nanalysis log and summary: {pathlib.Path(out).parent}")


def _connect(args):
    from .client import McpSystem1

    return McpSystem1(args.url)


def _person_here(kind: str, ref: str) -> str | None:
    """On a real arm, the person at this terminal approves each plan and change, after seeing its steps."""
    return "terminal" if input(f"Approve {kind} {ref} on the real arm? Type yes: ").strip().lower() == "yes" else None


def _show_steps(event) -> None:
    if event.type == "scene_ready":
        for note in event.payload.get("notes") or []:
            print(f"  note: {note}")
    if event.type in ("plan_ready", "plan_amended"):
        for s in event.payload.get("steps") or []:
            print(f"  {s['id']}: {s['skill']} {s['target']} {s.get('params') or ''}")


def _only(targets: str | None, angle: float | None = None):
    """The rule-based plan cut to the steps on these controls, such as a single press. With angle, each knob or dial is
    turned once, by that many degrees (+ counter-clockwise seen from the front), in place of the plan's turn and back."""
    if not targets and angle is None:
        return rule_planner
    keep = set(targets.split(",")) if targets else None

    def planner(request, scene, fallback):
        steps, turned = [], set()
        for s in fallback.steps:
            if keep is not None and s.target not in keep:
                continue
            if angle is not None and s.skill == "turn":
                if s.target in turned:
                    continue
                turned.add(s.target)
                s = s.model_copy(update={"params": {**s.params, "angle": angle}})
            steps.append(s)
        if not steps:
            raise SystemExit(f"the plan has no step on {targets}. The scan found: {', '.join(c.id for c in scene.controls)}")
        return fallback.model_copy(update={"steps": steps})
    return planner


def run(args) -> None:
    run_id = args.id or f"run-{int(time.time())}"
    request = TestRequest(request_id=run_id, product=args.product)
    system1 = _connect(args)
    try:
        real = not robot_may_auto_approve(system1.system_status().robot)
        log = RunLog(run_id, args.runs, on_event=_show_steps if real else None)
        policy, respond = _survey_review(args, system1, log)
        try:
            _print(run_test(system1, request, log, planner=_only(args.only, args.angle), approve=_person_here if real else auto_approve,
                            policy=policy, respond=respond))
        finally:
            _save_frames(system1, system1.scene_get().scene.frames, log.dir / "frames")
    finally:
        system1.close()


def _save_frames(system1, refs, folder) -> None:
    """The scan's photos (the labelled panel map, then its views) as JPEGs, to look at after the run."""
    folder.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        (folder / f"{ref.replace(':', '_')}.jpg").write_bytes(base64.b64decode(system1.evidence_frame(ref).data_b64))
    print(f"  photos in {folder.resolve()}")


def explore(args) -> None:
    system1 = _connect(args)
    try:
        log = RunLog(args.id or f"explore-{int(time.time())}", args.runs)
        scene, plan = explore_command(system1, log, *_survey_review(args, system1, log))
        _save_frames(system1, scene.frames, log.dir / "frames")
    finally:
        system1.close()
    for c in scene.controls:
        print(f"  {c.id:<12} {c.kind:<8} conf {c.conf:.2f}")
    for note in scene.notes:
        print(f"  note: {note}")
    print(f"fallback plan {plan.plan_id}: {len(plan.steps)} steps")


def _survey_review(args, system1, log):
    """The policy and responder for explore: with --survey-review System 1 holds after its survey, and with --review
    after its scan, and the model answers, with the manual if one was given."""
    policy = POLICIES[args.policy]
    if args.survey_review is None and args.review is None:
        return policy, rule_responder
    from .manual import Manual
    from .model import make_client
    from .survey import survey_reviewer

    path = args.review or args.survey_review
    manual = "\n\n".join(Manual(path).pages) if path else None
    client = make_client(DEFAULT_MODEL, run=log.run_id)
    update = {"review_survey": args.survey_review is not None, "review_scan": args.review is not None}
    return policy.model_copy(update=update), survey_reviewer(system1, client, log, manual)


def up(args) -> None:
    from .service import Service

    service = Service(args.runs, args.port)
    print(f"rav-agent on http://127.0.0.1:{service.port}. Open Live in the Console.")
    service.serve()


def agent(args) -> None:
    """One model run on a running server, with plans auto-approved on the sim and approved at this terminal on a real arm."""
    from .agent import run_agent, sim_auto_approve
    from .manual import Manual
    from .model import make_client

    run_id = args.id or f"agent-{int(time.time())}"
    system1 = _connect(args)
    try:
        real = not robot_may_auto_approve(system1.system_status().robot)
        log = RunLog(run_id, args.runs, on_event=_show_steps if real else None)
        report = run_agent(system1, TestRequest(request_id=run_id, product=args.product), log, make_client(args.model, args.fallback, effort=args.effort, run=run_id),
                           approve=_person_here if real else sim_auto_approve, manual=Manual(args.manual) if args.manual else None)
    finally:
        system1.close()
    _print(report)


def _budget(args):
    from .ledger import Budget

    return Budget(args.budget_usd, no_price_ok=args.no_price_ok, token_cap=args.token_cap)


def spend(args) -> None:
    from .ledger import spend_table

    print(spend_table())


def soft(args) -> None:
    from .soft import format_table, run_round_one

    models = args.models.split(",") + (["rules"] if args.baseline else [])
    from .soft import SCENARIOS
    chosen = [c for c in SCENARIOS if not args.scenarios or c.name in args.scenarios.split(",")]
    done = run_round_one(models, args.runs, _budget(args), chosen)
    print(format_table(done["summary"]))
    if done["stopped"]:
        print(f"stopped early: {done['stopped']}")
    print(f"every run: {done['folder']}/results.json")


def evaluate(args) -> None:
    from .eval import run_matrix

    models = args.models.split(",") + (["rules"] if args.baseline else [])
    if args.appliances:
        from .eval import run_authored

        rate = float(args.error_rates.split(",")[0])
        done = run_authored(args.appliances.split(","), models, rate, args.base_seed, args.error_schedule, args.effector, args.runs, budget=_budget(args))
        if done.get("stopped"):
            print(f"stopped early: {done['stopped']}")
        print(json.dumps(done["summary"], indent=2))
        print(f"every run: {done['folder']}/results.json")
        return
    done = run_matrix(args.devices.split(","), args.faults.split(","), [float(r) for r in args.error_rates.split(",")], models, args.repeats, args.route, args.runs, args.base_seed, budget=_budget(args), error_schedule=args.error_schedule)
    if done.get("stopped"):
        print(f"stopped early: {done['stopped']}")
    print(json.dumps(done["summary"], indent=2))
    print(f"every run: {done['folder']}/results.json")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav", description=__doc__)
    ap.add_argument("--runs", default="runs", help="where run folders go")
    sub = ap.add_subparsers(dest="command", required=True)
    ap.add_argument("--policy", default="tethered", choices=sorted(POLICIES), help="how much System 1 does before it defers")
    m = sub.add_parser("mock", help="the planted-fault demo, with a fake System 1: Rev A, patch, Rev B")
    m.add_argument("--id", default="mock")
    m.add_argument("--params", default="subjects/appliance/cad/params.rev_a.json")
    m.add_argument("--analyst", default="rules", choices=["rules", "cli", "model", "onshape", "local"],
                   help="who diagnoses the findings: the scripted rules; the model through the claude CLI (Claude Code "
                        "login, no API key); the model through the API (--extra model and an API key); the model "
                        "fixing the real Onshape model on a branch (keys in .env, ids in --tags); or the model writing "
                        "CadQuery for new parts in a local workspace (offline)")
    m.add_argument("--step", default=None, help="the tested revision as a STEP assembly (--analyst local; default: our box)")
    m.add_argument("--tags", default="subjects/appliance/onshape.yaml", help="the product's Onshape tag file (--analyst onshape)")
    a = sub.add_parser("analyze", help="the CAD step alone: a recorded run's findings to the analyst, stopping at the patches")
    a.add_argument("--run", required=True, help="a recorded run's events.jsonl")
    a.add_argument("--analyst", default="onshape", choices=["rules", "cli", "model", "onshape", "local"])
    a.add_argument("--step", default=None, help="the tested revision as a STEP assembly (--analyst local, with --tags)")
    a.add_argument("--tags", default="subjects/centrifuge/onshape.yaml", help="the product's Onshape tag file (--analyst onshape)")
    a.add_argument("--params", default="subjects/appliance/cad/params.rev_a.json", help="the params file (other analysts)")
    a.add_argument("--finding", nargs="*", help="only these finding ids or targets")
    a.add_argument("--serial", action="store_true", help="one finding at a time instead of all at once")
    a.set_defaults(fn=analyze)
    m.set_defaults(fn=mock)
    for name, fn, about in (("run", run, "one full run against System 1's server"), ("explore", explore, "/explore: find the controls, and print them")):
        c = sub.add_parser(name, help=about)
        c.add_argument("--url", default="http://127.0.0.1:8780/mcp", help="System 1's server. Set RAV_TOKEN if it needs a token")
        c.add_argument("--id", default=None)
        c.add_argument("--survey-review", nargs="?", const="", default=None, metavar="MANUAL",
                       help="hold after the survey for the model to pick the panel and say what to expect, with this manual")
        c.add_argument("--review", nargs="?", const="", default=None, metavar="MANUAL",
                       help="hold after the scan for the model to name each part from this manual (ids become its names)")
        c.set_defaults(fn=fn)
    r = sub.choices["run"]
    r.add_argument("--product", default="Device under test")
    r.add_argument("--only", default=None, metavar="CONTROL,...", help="run only the plan's steps on these controls, such as button_1")
    r.add_argument("--angle", type=float, default=None, metavar="DEG",
                   help="turn each knob or dial once by this much (+ counter-clockwise seen from the front), such as -60")
    a = sub.add_parser("agent", help="one run with the frontier model at the controls, on a running server (sim: plans auto-approve)")
    a.add_argument("--url", default="http://127.0.0.1:8780/mcp")
    a.add_argument("--id", default=None)
    a.add_argument("--product", default="Device under test")
    a.add_argument("--model", default=DEFAULT_MODEL, help="a model on Snowflake Cortex")
    a.add_argument("--effort", default=None, choices=["low", "medium", "high"], help="ask Claude models for reasoning text, at this effort")
    a.add_argument("--fallback", default=None)
    a.add_argument("--manual", default=None, help="a PDF or text file")
    a.set_defaults(fn=agent)
    u = sub.add_parser("up", help="rav-agent: start, watch and steer runs from the Console")
    u.add_argument("--port", type=int, default=8790)
    u.set_defaults(fn=up)
    e = sub.add_parser("eval", help="a matrix of runs, each on a fresh server, scored from the answer key")
    e.add_argument("--devices", default="C", help="comma-separated: C or a seed")
    e.add_argument("--faults", default="none", help="comma-separated: none, random, or a fault name")
    e.add_argument("--error-rates", default="0")
    e.add_argument("--error-schedule", default=None, metavar="WHEN:KIND,...", help="force these robot errors on every run, such as 5:device_moved_silent")
    e.add_argument("--repeats", type=int, default=1)
    e.add_argument("--appliances", default=None, help="authored devices as id:rev, comma-separated, such as interval-timer:A. In place of --devices")
    e.add_argument("--effector", default="stock", choices=["stock", "probe"])
    e.add_argument("--models", default=",".join(MODELS))
    e.add_argument("--baseline", action="store_true", help="also run the rule-based plan on each")
    e.add_argument("--route", default="rgb", choices=["depth", "rgb"])
    e.add_argument("--base-seed", type=int, default=0)
    e.set_defaults(fn=evaluate)
    f = sub.add_parser("soft", help="round 1: short made-up scenarios on a fake robot, per model. No sim")
    f.add_argument("--models", default=",".join(MODELS))
    f.add_argument("--baseline", action="store_true", help="also run the rule-based plan on each")
    f.add_argument("--scenarios", default=None, help="comma-separated names, to run only these")
    f.set_defaults(fn=soft)
    for parser in (e, f):
        parser.add_argument("--budget-usd", type=float, default=None, help="stop before starting a run that could cross this, across the whole ledger")
        parser.add_argument("--no-price-ok", action="store_true", help="run models with no price, capped by --token-cap")
        parser.add_argument("--token-cap", type=int, default=None)
    sub.add_parser("spend", help="what every model call so far has cost, from the ledger").set_defaults(fn=spend)
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except ConnectionError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
