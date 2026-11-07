"""Command line for the appliance CAD (needs `uv sync --extra cad`). From the repo root:

  uv run python -m rav_cad.parametric build subjects/appliance/cad/appliance.rev_a.yaml --out cad/out/rev_a
  uv run python -m rav_cad.parametric check subjects/appliance/cad/appliance.rev_a.yaml
  uv run python -m rav_cad.parametric patch subjects/appliance/cad/appliance.rev_a.yaml \
      subjects/appliance/cad/patch_button_2.json --out cad/out/rev_b
  uv run python -m rav_cad.parametric gauge --spec subjects/appliance/cad/appliance.rev_a.yaml --feature button_2 \
      --out cad/out/gauge
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rav_cad.parametric import checks, gauge, patch
from rav_cad.parametric.build import build, export
from rav_cad.parametric.render import render
from rav_cad.parametric.spec import Spec


def record_run(out: str) -> None:
    """Add the run folder to <parent>/runs.json so viewer.html lists it."""
    out = Path(out)
    idx = out.parent / "runs.json"
    try:
        runs = json.loads(idx.read_text()) if idx.exists() else []
    except ValueError:
        runs = []
    key = out.as_posix()
    if key not in runs:
        idx.write_text(json.dumps(runs + [key], indent=1))


def cmd_build(a) -> int:
    t = time.time()
    b = build(Spec.load(a.spec))
    rows = checks.run(b, interference=not a.fast)
    print(checks.table(rows))
    out = Path(a.out)
    for old in out.glob("*.stl") if out.exists() else []:      # a rebuild replaces the folder's parts
        old.unlink()
    files = export(b, out)
    (out / "checks.json").write_text(json.dumps(checks.as_json(rows), indent=2))
    if not a.no_render:
        render(b, out / "render.png")
    record_run(a.out)
    print(f"\n{len(files)} STLs + features.json in {out}  ({time.time() - t:.1f} s)")
    if not checks.ok(rows):
        print("CHECKS FAILED: fix the spec before printing")
        return 1
    return 0


def cmd_check(a) -> int:
    rows = checks.run(build(Spec.load(a.spec)), interference=not a.fast)
    print(checks.table(rows))
    return 0 if checks.ok(rows) else 1


def cmd_patch(a) -> int:
    r = patch.apply_files(a.spec, a.patch, a.out)
    print(r.summary())
    record_run(a.out)
    if r.accepted:
        render(r.built, Path(a.out) / "render.png", highlight={p.split("__")[0] for p in r.changed_parts})
        print(f"\nnew spec, changed STLs and patch_result.json in {a.out}. A teammate approves before printing.")
    return 0 if r.accepted else 1


def cmd_gauge(a) -> int:
    values = [float(v) for v in a.values.split(",")] if a.values else gauge.DEFAULT_VALUES
    if a.spec and a.feature:
        files = gauge.for_feature(Spec.load(a.spec), a.feature, a.out, values)
    elif a.type:
        files = gauge.for_type(a.type, a.out, values=values)
    else:
        print("give --spec and --feature, or --type")
        return 2
    print("\n".join(str(f) for f in files))
    print("engraved numbers are clearance in hundredths of a mm (15 = 0.15 mm). Print in the inserts' orientation.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("spec"); p.add_argument("--out", required=True)  # noqa: E702
    p.add_argument("--fast", action="store_true", help="skip the slower interference checks")
    p.add_argument("--no-render", action="store_true")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("check"); p.add_argument("spec"); p.add_argument("--fast", action="store_true")  # noqa: E702
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("patch"); p.add_argument("spec"); p.add_argument("patch")  # noqa: E702
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_patch)
    p = sub.add_parser("gauge"); p.add_argument("--spec"); p.add_argument("--feature")  # noqa: E702
    p.add_argument("--type"); p.add_argument("--values", help="comma-separated mm, e.g. 0.1,0.2,0.3")  # noqa: E702
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_gauge)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
