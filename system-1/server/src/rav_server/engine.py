"""Runs routines on the robot, and decides when System 1 has to defer. No model is involved here, and none may be.

One worker thread owns the robot for its whole life, because the sim's renderers belong to the thread that made them.
A routine runs until a stop. At any stop but the last it holds at the step boundary until System 2 answers, with the
arm safe. If System 2 never answers, it keeps holding: System 1 doesn't improvise.
"""
from __future__ import annotations

import itertools
import queue
import threading
from collections import deque
from collections.abc import Callable

from rav_interface import (Checkpoint, Decision, Escalation, EscalationPolicy, Plan, RoutineHandle, RoutineName, SceneReport,
                           Step, StepSummary, StepTrace, StepVerdict, SystemStatus, TETHERED)

from .robot import Robot

MAX_FORCE_N = 15.0  # the hard cap, whatever a plan asks for (docs/decisions.md D21)
SKILLS = ["press", "flip", "slide", "turn", "push_latch"]


class RoutineError(ValueError):
    """A request System 2 got wrong: the tool layer reports these back as tool errors."""


class _Routine:
    def __init__(self, routine_id: str, name: RoutineName, policy: EscalationPolicy, plan: Plan | None):
        self.id, self.name, self.policy, self.plan = routine_id, name, policy, plan
        self.stops: queue.Queue[Checkpoint] = queue.Queue()
        self.decisions: queue.Queue[Decision] = queue.Queue()
        self.stop_requested = threading.Event()
        self.paused = False
        self.finished = False


def clamp(step: Step, cap: float = MAX_FORCE_N) -> Step:
    """No plan gets past the force cap, however it was written."""
    limit = step.params.get("force_limit")
    if isinstance(limit, (int, float)) and limit > cap:
        return step.model_copy(update={"params": {**step.params, "force_limit": cap}})
    return step


class RoutineEngine:
    def __init__(self, make_robot: Callable[[], Robot], robot_name: str = "robot"):
        self.make_robot, self.robot_name = make_robot, robot_name
        self.robot: Robot | None = None
        self.report = SceneReport()
        self.traces: dict[str, StepTrace] = {}
        self.routines: dict[str, _Routine] = {}
        self.active: _Routine | None = None
        self.ids = itertools.count(1)
        self.jobs: queue.Queue[_Routine | None] = queue.Queue()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._work, name="routine-worker", daemon=True)
        self.worker.start()

    # --- what the tools call ---------------------------------------------------------------------

    def status(self) -> SystemStatus:
        r = self.active
        state = "idle" if r is None else "paused" if r.paused else "running"
        return SystemStatus(state=state, robot=self.robot_name, skills=SKILLS, routine_id=r.id if r else None, routine=r.name if r else None)

    def start(self, routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        if routine == "run_plan" and plan is None:
            raise RoutineError("run_plan needs a plan")
        with self.lock:
            if self.active is not None:
                raise RoutineError(f"{self.active.name} ({self.active.id}) is still running. Stop it or answer its stop first")
            r = _Routine(f"r{next(self.ids)}", routine, policy or TETHERED, plan)
            self.routines[r.id], self.active = r, r
        self.jobs.put(r)
        return RoutineHandle(routine_id=r.id, routine=routine)

    def wait(self, routine_id: str, timeout_s: float = 30.0) -> Checkpoint:
        r = self._get(routine_id)
        try:
            return r.stops.get(timeout=timeout_s)
        except queue.Empty:
            status = "paused" if r.paused else "completed" if r.finished else "running"
            return Checkpoint(routine_id=r.id, status=status)

    def resume(self, routine_id: str, decision: Decision) -> None:
        r = self._get(routine_id)
        if not r.paused:
            raise RoutineError(f"{routine_id} isn't holding at a stop")
        r.decisions.put(decision)

    def stop(self, routine_id: str) -> None:
        r = self._get(routine_id)
        r.stop_requested.set()
        if r.paused:
            r.decisions.put(Decision(kind="abort", note="stop requested"))

    def evidence(self, ref: str) -> StepTrace:
        try:
            return self.traces[ref]
        except KeyError:
            raise RoutineError(f"no evidence called {ref}") from None

    def shutdown(self) -> None:
        self.jobs.put(None)
        self.worker.join(timeout=10)

    # --- the worker ------------------------------------------------------------------------------

    def _get(self, routine_id: str) -> _Routine:
        if routine_id not in self.routines:
            raise RoutineError(f"no routine {routine_id}")
        return self.routines[routine_id]

    def _work(self) -> None:
        while (r := self.jobs.get()) is not None:
            try:
                if self.robot is None:
                    self.robot = self.make_robot()
                {"explore": self._explore, "run_plan": self._run_plan, "home": self._home}[r.name](r)
            except Exception as e:  # a hardware or pipeline fault: stop first, report second
                r.stops.put(Checkpoint(routine_id=r.id, stop="safety_abort", status="aborted", reason=f"{type(e).__name__}: {e}"))
            finally:
                r.paused, r.finished = False, True
                with self.lock:
                    if self.active is r:
                        self.active = None
        if self.robot is not None:
            self.robot.close()

    def _hold(self, r: _Routine, checkpoint: Checkpoint) -> Decision:
        """Report a stop, then wait at this step boundary for as long as it takes."""
        r.paused = True
        r.stops.put(checkpoint.model_copy(update={"status": "paused"}))
        decision = r.decisions.get()
        r.paused = False
        return decision

    def _explore(self, r: _Routine) -> None:
        scene = self.robot.perceive()
        self.report = SceneReport(scene=scene, fallback_plan=self.robot.default_plan(scene))
        n = len(scene.controls)
        unsure = {c.id: round(c.conf, 3) for c in scene.controls if c.conf < r.policy.confidence_floor}
        if unsure:
            decision = self._hold(r, Checkpoint(routine_id=r.id, stop="escalation", steps_done=n, steps_total=n, escalation=Escalation(
                code="perception_low_confidence", tried=["scan"], measured={"confidence": unsure, "floor": r.policy.confidence_floor},
                options=["continue", "abort"])))
            if decision.kind == "abort":
                r.stops.put(Checkpoint(routine_id=r.id, stop="done", status="stopped", steps_done=n, steps_total=n, reason=decision.note))
                return
        r.stops.put(Checkpoint(routine_id=r.id, stop="done", status="completed", steps_done=n, steps_total=n))

    def _home(self, r: _Routine) -> None:
        home = getattr(self.robot, "home", None)
        if home:
            home()
        r.stops.put(Checkpoint(routine_id=r.id, stop="done", status="completed"))

    def _attempt(self, r: _Routine, step: Step) -> tuple[StepTrace, StepVerdict, int]:
        """Local retries: only when the robot couldn't carry out the test, which says nothing about the device."""
        attempt = 0
        while True:
            attempt += 1
            trace, verdict = self.robot.execute(step)
            if verdict.status != "inconclusive" or verdict.label == "unsafe" or attempt > r.policy.retries_per_step or r.stop_requested.is_set():
                return trace.model_copy(update={"attempt": attempt}), verdict.model_copy(update={"attempt": attempt}), attempt

    def _run_plan(self, r: _Routine) -> None:
        queue_ = deque(clamp(s) for s in r.plan.steps)
        done, since, resolved, total = 0, [], 0, len(queue_)
        policy = r.policy

        def snapshot(**fields) -> Checkpoint:
            nonlocal since, resolved
            cp = Checkpoint(routine_id=r.id, steps_done=done, steps_total=done + len(queue_), retries_resolved=resolved, verdicts=since, **fields)
            since, resolved = [], 0
            return cp

        while queue_:
            if r.stop_requested.is_set():
                r.stops.put(snapshot(stop="done", status="stopped", reason="stop requested"))
                return
            step = queue_.popleft()
            trace, verdict, attempts = self._attempt(r, step)
            ref = f"trace:{r.id}:{step.id}"
            self.traces[ref] = trace
            done += 1
            resolved += attempts > 1 and verdict.status == "passed"
            since.append(StepSummary(verdict=verdict, attempts=attempts, peak_force_n=trace.peak_force_n, travel_mm=trace.travel_mm,
                                     stop_reason=trace.stop_reason, readout_change=trace.readout_change, trace_ref=ref))
            if verdict.label == "unsafe":
                r.stops.put(snapshot(stop="safety_abort", status="aborted", reason=verdict.reason))
                return
            escalation = self._escalation(step, trace, verdict, attempts)
            if escalation is not None:
                decision = self._hold(r, snapshot(stop="escalation", escalation=escalation))
            elif policy.checkpoint_every and queue_ and done % policy.checkpoint_every == 0:
                decision = self._hold(r, snapshot(stop="checkpoint"))
            else:
                continue
            if decision.kind == "abort":
                r.stops.put(snapshot(stop="done", status="stopped", reason=decision.note or "aborted by System 2"))
                return
            if decision.kind == "skip":
                kept = [s for s in queue_ if s.target not in decision.targets]
                queue_.clear()
                queue_.extend(kept)
            elif decision.kind == "amend":
                queue_.clear()
                queue_.extend(clamp(s) for s in decision.steps)
        r.stops.put(snapshot(stop="done", status="completed"))

    @staticmethod
    def _escalation(step: Step, trace: StepTrace, verdict: StepVerdict, attempts: int) -> Escalation | None:
        """Whether this result needs System 2. A refused step never does: it just appears in the report."""
        measured = {"peak_force_n": trace.peak_force_n, "travel_mm": trace.travel_mm, "stop": trace.stop_reason, "readout_change": trace.readout_change}
        common = dict(step=step.id, target=step.target, tried=[f"{step.skill} x{attempts}"], measured=measured)
        if verdict.status == "failed":
            code = "unexpected_response" if verdict.label == "wrong_behavior" else "step_failed"
            return Escalation(code=code, **common)
        if verdict.status == "inconclusive":
            return Escalation(code="retries_exhausted", **common)
        return None
