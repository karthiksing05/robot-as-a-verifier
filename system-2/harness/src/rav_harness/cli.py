"""rav mock | rav run | rav explore. Each run writes runs/<id>/events.jsonl and report.json."""
from __future__ import annotations

import argparse
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
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except ConnectionError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
