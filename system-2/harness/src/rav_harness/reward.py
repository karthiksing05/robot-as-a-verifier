"""Coverage and the reward, computed only from step verdicts so anyone can recompute them from a run's log."""
from __future__ import annotations

from collections.abc import Iterable

from rav_contracts import Control, Coverage, Reward, StepVerdict

# A control with several steps takes its worst result.
RANK = {"failed": 4, "inconclusive": 3, "skipped": 2, "passed": 1, "observed": 0}


def coverage(controls: Iterable[Control], verdicts: Iterable[StepVerdict]) -> Coverage:
    controls = list(controls)
    worst: dict[str, StepVerdict] = {}
    for v in verdicts:
        if v.target not in worst or RANK[v.status] > RANK[worst[v.target].status]:
            worst[v.target] = v
    buckets = {s: [] for s in RANK}
    skipped: dict[str, str] = {}
    for c in controls:
        v = worst.get(c.id)
        if v is None:
            skipped[c.id] = "no test ran"
        elif v.status == "skipped":
            skipped[c.id] = v.reason
        else:
            buckets[v.status].append(c.id)
    return Coverage(detected=len(controls), passed=buckets["passed"], failed=buckets["failed"],
                    observed=buckets["observed"], inconclusive=buckets["inconclusive"], skipped=skipped)


def reward(cov: Coverage) -> Reward:
    """R = control coverage x pass rate on covered controls. Observe-only controls count toward coverage only.
    Inconclusive tests aren't covered: they say something about the robot, not the device."""
    control_coverage = cov.covered / cov.detected if cov.detected else 0.0
    judged = len(cov.passed) + len(cov.failed)
    pass_rate = len(cov.passed) / judged if judged else 0.0
    return Reward(value=round(control_coverage * pass_rate, 4), control_coverage=round(control_coverage, 4),
                  pass_rate=round(pass_rate, 4))
