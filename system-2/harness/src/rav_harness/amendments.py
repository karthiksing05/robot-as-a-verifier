"""Who has to sign off on an amended plan. Plain code assigns the level, so the model can't grade its own change.

docs/system-boundary.md#approving-an-amended-plan has the table. System 1 still clamps every parameter itself.
"""
from __future__ import annotations

from collections.abc import Iterable

from rav_contracts import Step

AUTOMATIC, NOTIFY, APPROVE, ALWAYS_A_PERSON = 0, 1, 2, 3


def _force(step: Step) -> float | None:
    limit = step.params.get("force_limit")
    return float(limit) if isinstance(limit, (int, float)) else None


def classify(approved: Iterable[Step], remaining: Iterable[Step], amended: Iterable[Step]) -> int:
    """Compares the amended steps with what a person approved, and what was still to run. Unsure means APPROVE."""
    approved, remaining, amended = list(approved), list(remaining), list(amended)
    allowed = {(s.target, s.skill): s for s in approved}
    level = AUTOMATIC
    for step in amended:
        known = allowed.get((step.target, step.skill))
        if known is None:
            return APPROVE  # a new target or skill
        limit, approved_limit = _force(step), _force(known)
        if limit is not None and (approved_limit is None or limit > approved_limit):
            return APPROVE  # more force than a person agreed to
    remaining_keys = [(s.target, s.skill) for s in remaining]
    amended_keys = [(s.target, s.skill) for s in amended]
    if amended_keys != remaining_keys:
        # A retry of one step ahead of an otherwise unchanged plan needs nobody. Any other change gets shown to a person.
        retried = len(amended_keys) == len(remaining_keys) + 1 and amended_keys[1:] == remaining_keys
        level = AUTOMATIC if retried else NOTIFY
    return level
