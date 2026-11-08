"""rav mock | rav run | rav explore. Each run writes runs/<id>/events.jsonl and report.json."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time

from rav_contracts import POLICIES, TestRequest

from .commands import explore as explore_command
from .loop import fix_and_retest, run_test
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
        elif args.analyst != "rules":
            from .analyst import cli_analyst, model_analyst
            analyst = cli_analyst if args.analyst == "cli" else model_analyst
        before, after = fix_and_retest(mock_system_1, request, analyst, cad, log_root=args.runs, policy=POLICIES[args.policy])
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


def up(args) -> None:
    from .service import Service

    service = Service(args.runs, args.port)
    print(f"rav-agent on http://127.0.0.1:{service.port}. Open Live in the Console.")
    service.serve()


def agent(args) -> None:
    """One model run on a running server, with plans auto-approved: sim only."""
    from .agent import run_agent, sim_auto_approve
    from .manual import Manual
    from .model import make_client

    run_id = args.id or f"agent-{int(time.time())}"
    system1 = _connect(args)
    try:
        report = run_agent(system1, TestRequest(request_id=run_id, product=args.product), RunLog(run_id, args.runs), make_client(args.model, args.fallback, effort=args.effort, run=run_id),
                           approve=sim_auto_approve, manual=Manual(args.manual) if args.manual else None)
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
    m.add_argument("--analyst", default="rules", choices=["rules", "cli", "model", "onshape"],
                   help="who diagnoses the findings: the scripted rules; the model through the claude CLI (Claude Code "
                        "login, no API key); the model through the API (--extra model and an API key); or the model "
                        "fixing the real Onshape model on a branch (keys in .env, ids in --tags)")
    m.add_argument("--tags", default="subjects/appliance/onshape.yaml", help="the product's Onshape tag file (--analyst onshape)")
    m.set_defaults(fn=mock)
    for name, fn, about in (("run", run, "one full run against System 1's server"), ("explore", explore, "/explore: find the controls, and print them")):
        c = sub.add_parser(name, help=about)
        c.add_argument("--url", default="http://127.0.0.1:8780/mcp", help="System 1's server. Set RAV_TOKEN if it needs a token")
        c.add_argument("--id", default=None)
        c.set_defaults(fn=fn)
    r = sub.choices["run"]
    r.add_argument("--product", default="Device under test")
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
    e.add_argument("--route", default="depth", choices=["depth", "rgb"])
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
