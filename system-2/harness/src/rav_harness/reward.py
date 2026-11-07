"""Coverage and the reward, computed only from step verdicts so anyone can recompute them from a run's log."""
from __future__ import annotations

from collections.abc import Iterable

from rav_contracts import DEVICE_CONTROL, Control, Coverage, Reward, StepVerdict

from .verdicts import settle


def coverage(controls: Iterable[Control], verdicts: Iterable[StepVerdict]) -> Coverage:
    """A control with several attempts takes what they add up to (verdicts.py)."""
    settled = settle(verdicts)
    buckets: dict[str, list[str]] = {s: [] for s in ("passed", "failed", "observed", "inconclusive", "intermittent")}
    skipped: dict[str, str] = {}
    controls = [c for c in controls if c.id != DEVICE_CONTROL]  # the device itself isn't a control to test
    for c in controls:
        s = settled.get(c.id)
        if s is None:
            skipped[c.id] = "no test ran"
        elif s.status == "skipped":
            skipped[c.id] = s.attempts[-1].reason
        else:
            buckets[s.status].append(c.id)
    return Coverage(detected=len(controls), passed=buckets["passed"], failed=buckets["failed"], observed=buckets["observed"],
                    inconclusive=buckets["inconclusive"], intermittent=buckets["intermittent"], skipped=skipped)


def reward(cov: Coverage) -> Reward:
    """R = control coverage x pass rate on covered controls. Observe-only controls count toward coverage only.
    Inconclusive tests aren't covered: they say something about the robot, not the device. An intermittent control is
    covered, and doesn't count as a pass."""
    control_coverage = cov.covered / cov.detected if cov.detected else 0.0
    judged = len(cov.passed) + len(cov.failed) + len(cov.intermittent)
    pass_rate = len(cov.passed) / judged if judged else 0.0
    return Reward(value=round(control_coverage * pass_rate, 4), control_coverage=round(control_coverage, 4),
                  pass_rate=round(pass_rate, 4))
