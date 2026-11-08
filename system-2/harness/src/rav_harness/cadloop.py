"""The CAD loop after a run: findings -> the CAD analyst (CadQuery, offline) -> approved patches -> a patched device ->
the same run again on it.

    rav fix --run runs/eval-1108-005148/001-rules-interval-timer-A            # an eval run on an authored appliance
    rav fix --run <run> --step product.step --tags product.yaml --approve Bayan  # any run, real arm included: no retest

1. **Match.** The run names controls by what perception saw; the CAD by design. match.register finds the device's pose
   from where the controls are and maps each finding's control to a CAD control. A finding on something the tags don't
   cover (a display, a toggle) is reported and skipped.
2. **Diagnose.** Each matched finding goes to the local CAD analyst (claude CLI on the Claude Code login, no keys) with
   the CAD control as its target. It decides whether CAD can fix it at all, and if so writes the new part and checks it.
3. **Approve.** A patch is applied only when approved. In the sim that is automatic and recorded ("auto (sim)", as for
   plans); otherwise a person passes --approve, and without it the loop stops at the proposed patches.
4. **Retest (authored appliances, sim only).** rav_cad.appliance.patched_device swaps the new solids into the tested
   revision, rebuilds their meshes and derives their travel from the geometry; then the same model, seed and error rate
   run on it. A finding is fixed when the retest has no finding on that CAD control and the arm pressed it.

On a real product the retest is: print rev_<X>/'s STLs, fit them, run the robot again.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from rav_contracts import Finding, StepOutcome

from .loop import diagnose
from .match import register
from .runlog import RunLog, read_events

SIM_APPROVER = "auto (sim)"


def _scene(events) -> list[dict]:
    scenes = [e.payload for e in events if e.type == "scene_ready"]
    return scenes[-1]["controls"] if scenes else []


def _record(run_dir: pathlib.Path) -> dict | None:
    """The run's row in its eval's results.json: model, device, revision, seeds."""
    path = run_dir.parent / "results.json"
    if not path.is_file():
        return None
    return next((r for r in json.loads(path.read_text()).get("results", []) if r.get("run_id") == run_dir.name), None)


def matched_findings(events, tags) -> tuple[list[tuple[Finding, Finding]], list[dict], dict]:
    """[(as the robot reported it, retargeted to its CAD control)], the findings no CAD control explains, the pose."""
    findings = [Finding(**e.payload) for e in events if e.type == "finding"]
    reg = register(_scene(events), tags)
    pairs, skipped = [], []
    for f in findings:
        cad = reg["matches"].get(f.target)
        if cad is None:
            skipped.append({"finding": f.id, "target": f.target, "why": "no CAD control the tags cover is where the robot tested it"})
            continue
        pairs.append((f, f.model_copy(update={"target": cad, "what_happened": f"{f.what_happened} (the robot called this control {f.target})"})))
    return pairs, skipped, reg


def _new_parts(patch_dir: pathlib.Path) -> dict:
    from rav_cad.local.workspace import Workspace
    result = json.loads((patch_dir / "patch_result.json").read_text())
    parts = Workspace(result["workspace"]).parts()
    return {n: parts[n] for n in result["changed"] if n in parts}


def fix_run(run_dir: str | pathlib.Path, *, device_dir: str | pathlib.Path | None = None, rev: str | None = None,
            step: str | pathlib.Path | None = None, tags: str | pathlib.Path | None = None, approve: str | None = None,
            retest: bool = True, model: str | None = None, parallel: bool = True, analyst: Any = None) -> dict:
    """The CAD loop on one run. Writes <run>/cad/ (tags, workspaces, rev_* folders, fix.json) and, with a retest, the
    retest run beside the original. Returns fix.json's content."""
    from rav_cad.local import LocalCadBackend

    from .analyst import make_local_analyst

    run_dir = pathlib.Path(run_dir).resolve()
    events = read_events(run_dir / "events.jsonl")
    record = _record(run_dir) or {}
    out = run_dir / "cad"
    out.mkdir(parents=True, exist_ok=True)
    authored = None
    if device_dir is None and step is None and record.get("authored"):
        from .eval import find_authored
        authored = find_authored(record["authored"])
        device_dir = authored["device_path"].parent
    rev = rev or record.get("rev") or "A"
    if device_dir is not None:
        from rav_cad.appliance import cad_parts, write_tags
        tags_path = write_tags(device_dir, out / "tags.yaml", rev)
        base: Any = cad_parts(device_dir, rev)
        product = pathlib.Path(device_dir).name
    elif step and tags:
        tags_path, base, product = pathlib.Path(tags), pathlib.Path(step), pathlib.Path(step).stem
        retest = False
    else:
        raise ValueError("say what was tested: an eval run on an authored appliance, or --step and --tags")
    sim = record.get("authored") is not None or device_dir is not None
    approver = approve or (SIM_APPROVER if sim else None)

    backend = LocalCadBackend(tags_path, base, out_dir=out, product=product)
    pairs, skipped, reg = matched_findings(events, backend.tags)
    log = RunLog(f"{run_dir.name}-cad", run_dir.parent)
    log.emit("message", {"role": "harness", "text": f"CAD loop on {run_dir.name}: {len(pairs)} finding(s) on CAD controls, "
                                                    f"{len(skipped)} elsewhere; pose yaw {reg['yaw_deg']} deg, residual {reg['residual_mm']} mm"})
    outcomes = [StepOutcome(**e.payload) for e in events if e.type == "step_finished"]
    started = time.monotonic()
    rows, applied = [], {}
    analyst = analyst or make_local_analyst(backend, tags_path)
    results = diagnose([cad for _, cad in pairs], analyst, backend, log, outcomes, parallel) if pairs else []
    for (orig, _), (f, cause, patch) in zip(pairs, results):
        row: dict[str, Any] = {"finding": orig.id, "robot_target": orig.target, "cad_control": f.target,
                               "cause": cause.model_dump(mode="json"), "patch": None, "applied": None}
        log.emit("root_cause", cause)
        if patch is not None:
            patch = patch.model_copy(update={"revision_to": f"{rev}-fix-{f.id}"})
            row["patch"] = patch.model_dump(mode="json")
            log.emit("patch_proposed", patch)
            if approver:
                try:
                    patch_dir = pathlib.Path(backend.apply(patch.model_copy(update={"approved_by": approver})))
                    row["applied"] = {"by": approver, "folder": str(patch_dir)}
                    for name, solid in _new_parts(patch_dir).items():
                        if name in applied:
                            row["applied"]["conflict"] = f"{name} was already changed by another fix; kept the first"
                            continue
                        applied[name] = (solid, f.id)
                except ValueError as e:
                    row["applied"] = {"refused": str(e)}
        rows.append(row)
    summary: dict[str, Any] = {"run": str(run_dir), "product": product, "rev": rev, "pose": reg, "findings": rows,
                               "not_cad": skipped, "approved_by": approver, "analysis_s": round(time.monotonic() - started, 1)}
    if not approver and any(r["patch"] for r in rows):
        summary["next"] = "patches proposed; a person approves with --approve NAME to apply them"
    if retest and applied and device_dir is not None:
        summary["retest"] = _retest(run_dir, record, authored, pathlib.Path(device_dir), rev, {n: s for n, (s, _) in applied.items()},
                                    rows, model or record.get("model") or "rules", backend.tags)
    (out / "fix.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    log.emit("message", {"role": "harness", "text": f"CAD loop done: {out / 'fix.json'}"})
    return summary


def _retest(run_dir: pathlib.Path, record: dict, authored: dict | None, device_dir: pathlib.Path, rev: str, parts: dict,
            rows: list[dict], model: str, tags) -> dict:
    from rav_cad.appliance import patched_device

    from .eval import find_authored, run_one
    from .launch import Device

    built = patched_device(device_dir, rev, parts, run_dir / "cad" / "device")
    authored = authored or find_authored(device_dir.name)
    device = Device(path=built["device"], rev=rev, effector=record.get("effector") or "stock",
                    error_rate=record.get("error_rate") or 0.0, error_seed=record.get("error_seed") or 0)
    run_id = f"{run_dir.name}-retest"
    after = run_one(device, model, run_dir.parent, run_id, authored=authored)
    after_events = read_events(run_dir.parent / run_id / "events.jsonl") if (run_dir.parent / run_id / "events.jsonl").is_file() else []
    later, _, _ = matched_findings(after_events, tags)
    still = {cad.target for _, cad in later}
    pressed = _pressed(after_events, tags)
    verdicts = {}
    for r in rows:
        if r.get("applied") and "folder" in r["applied"]:
            c = r["cad_control"]
            verdicts[r["finding"]] = ("fixed" if c not in still and c in pressed else
                                      "still failing" if c in still else "not tested on the retest")
    return {"device": built, "run": run_id, "model": model, "record": after, "verdicts": verdicts}


def _pressed(events, tags) -> set[str]:
    """CAD controls the retest operated and saw pass: a verdict of passed on a step whose target matches one."""
    reg = register(_scene(events), tags)
    out = set()
    for e in events:
        v = e.payload.get("verdict") if e.type == "step_finished" else None
        if isinstance(v, dict) and v.get("status") == "passed" and reg["matches"].get(v.get("target")):
            out.add(reg["matches"][v["target"]])
    return out
