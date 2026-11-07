"""The slash commands: macros over System 1's tools and, soon, model calls. They belong to System 2.

/explore today runs System 1's explore routine and takes its rule-based plan. Recalling similar products from memory and
writing a high-level plan is where the model comes in.
"""
from __future__ import annotations

from collections.abc import Callable

from rav_contracts import Checkpoint, Crossing, Decision, EscalationPolicy, Plan, RoutineHandle, SceneInventory, System1, TETHERED

from .runlog import RunLog

Responder = Callable[[Checkpoint], Decision]


def rule_responder(stop: Checkpoint) -> Decision:
    """Carries on at every stop, and is what the model replaces. Failures are still recorded: only the reaction is missing."""
    return Decision()


def log_crossing(log: RunLog, handle: RoutineHandle, stop: Checkpoint, policy: EscalationPolicy) -> None:
    e = stop.escalation
    log.emit("crossing", Crossing(routine=handle.routine, stop=stop.stop, code=e.code if e else None, step=e.step if e else None,
                                  target=e.target if e else None, policy=policy.name, verdicts=len(stop.verdicts),
                                  retries_resolved=stop.retries_resolved).model_dump(mode="json"))


def wait_for_stop(system1: System1, handle: RoutineHandle, should_stop: Callable[[], bool] = lambda: False) -> Checkpoint:
    """routine_wait blocks on System 1, so the model never spends a turn polling. A timed-out wait isn't a crossing."""
    asked = False
    while True:
        stop = system1.routine_wait(handle.routine_id)
        if stop.stop:
            return stop
        if not asked and should_stop():
            system1.routine_stop(handle.routine_id)
            asked = True


def explore(system1: System1, log: RunLog, policy: EscalationPolicy = TETHERED, respond: Responder = rule_responder) -> tuple[SceneInventory, Plan]:
    """/explore: discover what's on the device, and return it with the fallback plan."""
    handle = system1.routine_start("explore", policy=policy)
    while True:
        stop = wait_for_stop(system1, handle)
        log_crossing(log, handle, stop, policy)
        if stop.status != "paused":
            break
        system1.routine_resume(handle.routine_id, respond(stop))
    if stop.status != "completed":
        raise RuntimeError(f"explore ended {stop.status}: {stop.reason}")
    report = system1.scene_get()
    return report.scene, report.fallback_plan
