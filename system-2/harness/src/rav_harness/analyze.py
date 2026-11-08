"""Replay a recorded run's findings into an analyst, and stop at the proposed patches.

`fix_and_retest` runs the whole loop. This runs only the CAD step, from a run that already happened (on the arm,
in the sim, or simulated for a product the arm hasn't met): each finding gets the same AnalystContext it would get
live, and nothing is approved, applied or retested. With the Onshape analyst the patches stay on their branches.
Findings are analyzed in parallel by default: each has its own branch and session.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from rav_contracts import CadBackend, Finding, StepOutcome

from .loop import Analyst, diagnose
from .runlog import RunLog, read_events


def analyze_run(run: str | pathlib.Path, analyst: Analyst, cad: CadBackend, log_root: str | pathlib.Path = "runs",
                only: list[str] | None = None, parallel: bool = True) -> pathlib.Path:
    """Analyze each finding of `run` (an events.jsonl); write an analysis run log and summary.json beside it."""
    run = pathlib.Path(run)
    events = read_events(run)
    outcomes = [StepOutcome(**e.payload) for e in events if e.type == "step_finished"]
    findings = [Finding(**e.payload) for e in events if e.type == "finding"]
    findings = [f for f in findings if not only or f.id in only or f.target in only]
    log = RunLog(f"{run.parent.name}-analysis", log_root)
    log.emit("message", {"role": "harness", "text": f"analyzing {len(findings)} finding(s) from {run}"
                                                    f"{' in parallel' if parallel and len(findings) > 1 else ''}"})
    start = time.monotonic()
    summary: list[dict[str, Any]] = []
    for f, cause, patch in diagnose(findings, analyst, cad, log, outcomes, parallel):
        log.emit("root_cause", cause)
        if patch is None:
            log.emit("message", {"role": "harness", "text": f"no CAD fix for {f.id}: {cause.root_cause}"})
        else:
            log.emit("patch_proposed", patch)
        summary.append({"finding": f.model_dump(mode="json"), "cause": cause.model_dump(mode="json"),
                        "patch": patch.model_dump(mode="json") if patch else None})
    log.emit("message", {"role": "harness", "text": f"analysis took {time.monotonic() - start:.1f} s"})
    out = log.dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2))
    return out
