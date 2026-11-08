"""rav mock | rav run | rav explore | rav analyze. Each run writes runs/<id>/events.jsonl and report.json."""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import tempfile
import time

from rav_contracts import POLICIES, TestRequest

from .commands import explore as explore_command
from .loop import fix_and_retest, run_test
from .mock import mock_analyst, mock_system_1
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


def run(args) -> None:
    run_id = args.id or f"run-{int(time.time())}"
    request = TestRequest(request_id=run_id, product=args.product)
    system1 = _connect(args)
    try:
        _print(run_test(system1, request, RunLog(run_id, args.runs), policy=POLICIES[args.policy]))
    finally:
        system1.close()


def explore(args) -> None:
    system1 = _connect(args)
    try:
        scene, plan = explore_command(system1, RunLog(args.id or f"explore-{int(time.time())}", args.runs), POLICIES[args.policy])
    finally:
        system1.close()
    for c in scene.controls:
        print(f"  {c.id:<12} {c.kind:<8} conf {c.conf:.2f}")
    print(f"fallback plan {plan.plan_id}: {len(plan.steps)} steps")


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
        c.set_defaults(fn=fn)
    r = sub.choices["run"]
    r.add_argument("--product", default="Device under test")
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except ConnectionError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
