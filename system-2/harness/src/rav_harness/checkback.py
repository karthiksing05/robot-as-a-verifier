"""Check-back: every change is checked where the device shows it, groups of changes are followed by a look at what they
left, and the run ends with a look compared against the first.

A step that only reads the control it operated proves the control moved, not that the device did what it should. So:

  (i)   every step that changes something checks at least one of the device's outputs: the display (lcd) or a reading
        on a channel other than the one its control drives;
  (ii)  after a group of changes, the plan reads the device back: an observe step with a check on its outputs. Where
        nothing in the scene can be observed, a repeat of an earlier step, with such a check, does it instead;
  (iii) the run ends with a look at the device, compared with the first: what the run left changed goes in the report.

(i) and (ii) are checked here, from the plan alone, like any other bad request: nothing moves until they hold.
(iii) is the tool belt's, at finish_run. Nothing here knows any device: only skills, metrics and channel names the
robot itself published.
"""
from __future__ import annotations

from typing import Any, Iterable

from rav_contracts import Check, Control, Step

READS = ("observe", "none", "wait")  # skills that change nothing
EXEMPT = ("reposition",)  # moves the device, not its controls: a new look follows anyway
GROUP = 5  # changes in a row, at most, before the plan reads the device back


def changes(step: Step) -> bool:
    return step.skill not in READS and step.skill not in EXEMPT


def output_checks(step: Step, own: set[str]) -> list[Check]:
    """Checks on what the device shows, rather than on the part the step pushed: the display, or any channel but its own."""
    out = []
    for c in step.check:
        metric = c.metric.strip()
        if metric.lower() == "lcd" or (metric.startswith("reading:") and metric.removeprefix("reading:") not in own):
            out.append(c)
    return out


def missing_checkback(steps: list[Step], own: dict[str, set[str]], tried_before: Iterable[str] = (), can_observe: bool = True,
                      group: int = GROUP) -> list[str]:
    """What the plan is missing, one line each; empty when it checks back.

    own: control id -> the channels it's known to drive (from earlier steps' verdicts). tried_before: controls already
    operated in this run. can_observe: the robot offers observe on something in the scene."""
    problems = []
    seen = set(tried_before)
    run: list[str] = []  # changing steps since the last check-back
    ends_unchecked: str | None = None
    for s in steps:
        mine = own.get(s.target, set())
        reads_out = bool(output_checks(s, mine))
        if changes(s) and not reads_out:
            drives = f" other than {', '.join(sorted(mine))}, which {s.target} drives" if mine else ""
            problems.append(f"{s.id}: {s.skill} {s.target} changes something but checks none of the device's outputs. Add a check on lcd, or on "
                            f"a reading:<channel>{drives}, for what the device should show after it (the display, a light, another reading). "
                            "If the manual says nothing should change there, check that it still shows what it showed before, and say so in source")
        checks_back = reads_out and (s.skill == "observe" or (not can_observe and changes(s) and s.target in seen))
        if checks_back:
            run, ends_unchecked = [], None
        elif changes(s):
            run.append(s.id)
            ends_unchecked = s.id
            if len(run) == group + 1:
                problems.append(f"{run[0]} to {s.id}: {len(run)} changes in a row with no check-back. After a group of changes (a mode change, a power "
                                f"cycle, a procedure; at most {group}), {_how(can_observe)}")
        seen.add(s.target)
    if ends_unchecked and sum(changes(s) for s in steps) >= 2:
        problems.append(f"after {ends_unchecked}: the plan ends on changes it never checks back. {_how(can_observe).capitalize()}")
    return problems


def _how(can_observe: bool) -> str:
    if can_observe:
        return ("add an observe step whose checks read the display, lights or readings: what the earlier steps should have left there, "
                "with the earlier step named in source")
    return ("repeat an earlier step with checks on the device's outputs (nothing in the scene can be observed): what the earlier steps "
            "should have left there, with the earlier step named in source")


# --- (iii) the closing look ------------------------------------------------------------------------

def state_of(controls: Iterable[Control], readings: dict[str, Any]) -> dict[str, Any]:
    """What a look and the readings say about where the device stands. Only what a scan reports stably."""
    out: dict[str, Any] = {}
    for c in controls:
        if c.on is not None:
            out[f"{c.id} on"] = c.on
        if c.latched is not None:
            out[f"{c.id} latched"] = c.latched
        if c.position is not None:
            out[f"{c.id} position"] = round(c.position, 1)
    for name, value in readings.items():
        out[f"{'display' if name == 'lcd' else name}"] = value
    return out


def differences(first: dict[str, Any], now: dict[str, Any]) -> list[str]:
    out = []
    for key in sorted(set(first) | set(now)):
        if key in first and key in now and first[key] != now[key]:
            out.append(f"{key}: {first[key]} at the start, {now[key]} now")
    return out
