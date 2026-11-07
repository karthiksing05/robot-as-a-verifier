"""What a control's attempts add up to. Plain code, computed only from step verdicts, so anyone can recompute it from a
run's log. The model can ask for more attempts, but it can't change the result.

    judged attempts           result
    F F (no pass between)     failed, confirmed
    F (once, never retested)  failed, not confirmed
    F P, P F, F P F           intermittent: reported with every attempt, neither hidden nor called a clean pass
    P                         passed

Inconclusive and skipped attempts say nothing about the device, so they're not judged: an inconclusive between two
failures doesn't count as a pass. They decide the result only when nothing else exists.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from rav_contracts import Finding, StepVerdict


@dataclass
class Settled:
    target: str
    status: str  # passed, failed, intermittent, observed, inconclusive or skipped
    confirmed: bool = True
    attempts: list[StepVerdict] = field(default_factory=list)

    @property
    def failures(self) -> list[StepVerdict]:
        return [v for v in self.attempts if v.status == "failed"]


def settle_one(target: str, attempts: list[StepVerdict]) -> Settled:
    judged = [v.status for v in attempts if v.status in ("passed", "failed")]
    if "failed" in judged:
        repeated = any(a == b == "failed" for a, b in zip(judged, judged[1:]))
        if repeated or "passed" not in judged:
            return Settled(target, "failed", repeated, attempts)
        return Settled(target, "intermittent", True, attempts)
    if judged:
        return Settled(target, "passed", True, attempts)
    statuses = {v.status for v in attempts}
    for status in ("observed", "inconclusive", "skipped"):
        if status in statuses:
            return Settled(target, status, True, attempts)
    return Settled(target, "untested", True, attempts)


def settle(verdicts: Iterable[StepVerdict]) -> dict[str, Settled]:
    by_target: dict[str, list[StepVerdict]] = {}
    for v in verdicts:
        by_target.setdefault(v.target, []).append(v)
    return {t: settle_one(t, attempts) for t, attempts in by_target.items()}


def findings_from(verdicts: Iterable[StepVerdict], seqs: dict[int, int] | None = None) -> list[Finding]:
    """One finding per control that failed or was intermittent, in the order they first failed. seqs maps
    id(verdict) to the step_finished event's seq, so the Console can jump to it."""
    verdicts, seqs = list(verdicts), seqs or {}
    found = []
    for s in sorted((s for s in settle(verdicts).values() if s.status in ("failed", "intermittent")),
                    key=lambda s: verdicts.index(s.failures[0])):
        first = s.failures[-1] if s.status == "failed" else s.failures[0]
        if s.status == "intermittent":
            line = ", ".join(v.status for v in s.attempts)
            what, label, severity = f"failed and also passed ({line}). First failure: {first.reason}", "intermittent", "medium"
        else:
            what, label = first.reason, first.label or "anomalous"
            severity = "high" if label in ("stuck", "no_actuation", "unsafe") else "medium"
        found.append(Finding(id=f"F{len(found) + 1}", severity=severity, target=s.target, label=label, what_happened=what,
                             step_ids=[v.step for v in s.attempts], event_seqs=[seqs[id(v)] for v in s.failures if id(v) in seqs],
                             evidence=[e for v in s.failures for e in v.evidence], confirmed=s.confirmed))
    return found
