"""Runs routines on the robot, and decides when System 1 has to defer. No model is involved here, and none may be.

One worker thread owns the robot for its whole life, because the sim's renderers belong to the thread that made them.
A routine runs until a stop. At any stop but the last it holds at the step boundary until System 2 answers, with the
arm safe. If System 2 never answers, it keeps holding: System 1 doesn't improvise.

A bad request fails in the tool call, before anything moves, and a routine holding at a stop keeps holding. Validation
reads only the contract (rav_interface.check_steps), so it needs no robot and no worker thread.
"""
from __future__ import annotations

import itertools
import queue
import statistics
import threading
import traceback
from collections import Counter, deque
from collections.abc import Callable
from typing import Any

from rav_interface import (ActionSpec, Check, CheckResult, Checkpoint, Decision, Escalation, EscalationPolicy, Frame, Plan, RoutineHandle,
                           RoutineName, SceneReport, Step, StepSummary, StepTrace, StepVerdict, SystemStatus, TETHERED, check_steps)

from .actions import ACTIONS, MAX_FORCE_N
from .robot import PipelineFailure, Robot

SUMMARY_MEASURES = ("contact_offset_mm", "refined", "refine_shift_mm", "regrip_mm", "landing_n", "lcd", "collisions")
# pose_unstable: how far off the robot's own corrections have to be, in mm, before the map of the device is in doubt.
POSE_SERIES = ("refine_shift_mm", "contact_offset_mm")
POSE_GROWING_MM = 4.0  # three in a row, each larger, ending at least this far off, the one before at least half that
POSE_JUMP_MM = 6.0  # two in a row at least this far off,
POSE_JUMP_ABOVE_MM = 3.0  # and this much above what earlier steps in the routine needed


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
        self.attempts: Counter[str] = Counter()  # by step id, across retries and amendments, so no trace is overwritten
        self.pose_history: dict[str, list[float]] = {k: [] for k in POSE_SERIES}
        self.stale_hold = False  # holding because the device moved: the old poses can't be run on


def clamp(step: Step, cap: float = MAX_FORCE_N) -> Step:
    """A second guard behind validation: no plan gets past the limit, however it arrived."""
    limit = step.params.get("force_limit")
    if isinstance(limit, (int, float)) and limit > cap:
        return step.model_copy(update={"params": {**step.params, "force_limit": cap}})
    return step


def _metric(check: Check, trace: StepTrace, verdict: StepVerdict) -> tuple[Any, bool]:
    """(the measured value, whether this attempt measured it)."""
    if check.metric.startswith("reading:"):
        channel = check.metric.split(":", 1)[1]
        seq = trace.readout_change.get(channel)
        readings = trace.measures.get("readings") or {}
        if seq:
            return seq[-1], True
        if channel in readings:
            return readings[channel], True
        return None, verdict.status in ("passed", "failed") and channel not in readings and bool(readings)
    if check.metric in ("peak_force_n", "travel_mm", "duration_s"):
        value = getattr(trace, check.metric)
    else:
        value = trace.measures.get(check.metric)
    return value, value is not None


def evaluate_checks(step: Step, trace: StepTrace, verdict: StepVerdict) -> list[CheckResult]:
    """Each Step.check against this attempt's measurements. Reported beside the verdict, which it never changes."""
    results = []
    for c in step.check:
        actual, measured = _metric(c, trace, verdict)
        passed: bool | None = None
        if measured:
            try:
                if c.op == "changed":
                    if c.metric.startswith("reading:"):
                        seq = trace.readout_change.get(c.metric.split(":", 1)[1]) or []
                        passed = len(seq) > 1 and seq[0] != seq[-1]
                    else:
                        passed = bool(actual)
                elif c.op == "==":
                    passed = actual == c.value
                elif actual is not None:
                    passed = actual <= c.value if c.op == "<=" else actual >= c.value
            except TypeError:
                passed = None
        results.append(CheckResult(metric=c.metric, op=c.op, value=c.value, actual=actual if isinstance(actual, (int, float, str, bool)) else None, passed=passed))
    return results


def _pose_drift(history: dict[str, list[float]]) -> dict[str, Any] | None:
    """The numbers, if the robot's corrections say the device isn't where the map has it. One large correction isn't
    enough: a single part can be badly scanned, and only a trend across parts says the whole device moved."""
    for name, values in history.items():
        if len(values) >= 3 and values[-3] < values[-2] < values[-1] and values[-2] >= POSE_GROWING_MM / 2 and values[-1] >= POSE_GROWING_MM:
            return {"series": name, "pattern": "growing", "values_mm": values[-5:], "threshold_mm": POSE_GROWING_MM}
        if len(values) >= 2 and min(values[-2:]) >= POSE_JUMP_MM:
            earlier = values[:-2]
            baseline = statistics.median(earlier) if earlier else 0.0
            if min(values[-2:]) >= baseline + POSE_JUMP_ABOVE_MM:
                return {"series": name, "pattern": "jump", "values_mm": values[-5:], "baseline_mm": round(baseline, 2), "threshold_mm": POSE_JUMP_MM}
    return None


class RoutineEngine:
    def __init__(self, make_robot: Callable[[], Robot], robot_name: str = "robot", actions: list[ActionSpec] | None = None,
                 max_force_n: float = MAX_FORCE_N):
        self.make_robot, self.robot_name = make_robot, robot_name
        self.actions, self.max_force_n = ACTIONS if actions is None else actions, max_force_n
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

    def _actions(self) -> list[ActionSpec]:
        """The table, plus what this robot adds once it exists: reposition's ranges come from the device's data."""
        extra = getattr(self.robot, "extra_actions", None)
        return [*self.actions, *extra()] if extra else self.actions

    def status(self) -> SystemStatus:
        r = self.active
        state = "idle" if r is None else "paused" if r.paused else "running"
        actions = self._actions()
        return SystemStatus(state=state, robot=self.robot_name, skills=[a.skill for a in actions], actions=actions,
                            max_force_n=self.max_force_n, routine_id=r.id if r else None, routine=r.name if r else None)

    def _bad_steps(self, steps: list[Step]) -> None:
        scene = self.report.scene
        if scene is None:
            raise RoutineError("no scene yet: run explore first")
        problems = check_steps(steps, scene.controls, self._actions())
        if problems:
            raise RoutineError(f"{len(problems)} problem(s), and nothing moved:\n" + "\n".join(problems))

    def start(self, routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        if routine == "run_plan" and plan is None:
            raise RoutineError("run_plan needs a plan")
        with self.lock:
            if self.active is not None:
                raise RoutineError(f"{self.active.name} ({self.active.id}) is still running. Stop it or answer its stop first")
            if routine == "run_plan":
                if self.report.scene is not None and self.report.scene.stale:
                    raise RoutineError("the device moved since the last explore, so its poses are old: run explore first")
                self._bad_steps(plan.steps)
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
        if r.stale_hold and decision.kind != "abort":
            raise RoutineError("the device moved, so the remaining steps would run on old poses: abort this routine, then run explore")
        if decision.kind == "amend":
            self._bad_steps(decision.steps)  # raises with the routine still holding
        r.decisions.put(decision)

    def stop(self, routine_id: str) -> None:
        r = self._get(routine_id)
        r.stop_requested.set()
        if r.paused:
            r.decisions.put(Decision(kind="abort", note="stop requested"))

    def evidence(self, ref: str) -> StepTrace | Frame:
        if ref.startswith("frame:"):
            get = getattr(self.robot, "frame", None)
            frame = get(ref) if get else None
            if frame is None:
                raise RoutineError(f"no evidence called {ref}")
            return frame
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
            except PipelineFailure as e:  # perception couldn't do its job, and the arm is safe: System 2 can respond to this
                r.stops.put(Checkpoint(routine_id=r.id, stop="pipeline_error", status="aborted", reason=str(e)))
            except Exception as e:  # a hardware fault, or one we can't place: stop first, report second
                traceback.print_exc()
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
        def hold(code, tried):  # the robot holds where it calls this, for System 2's answer
            return lambda measured: self._hold(r, Checkpoint(routine_id=r.id, stop="escalation", escalation=Escalation(
                code=code, tried=[tried], measured=measured, options=["continue", "abort"])))
        self.robot.review = hold("survey_review", "survey") if r.policy.review_survey else None
        self.robot.review_scan = hold("scan_review", "scan") if r.policy.review_scan else None
        try:
            scene = self.robot.perceive()
        finally:
            self.robot.review = self.robot.review_scan = None
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

    def _attempt(self, r: _Routine, step: Step) -> tuple[StepTrace, StepVerdict, int, list[str]]:
        """Local retries: only when the robot couldn't carry out the test, which says nothing about the device. Every
        attempt keeps its own trace, under its own reference."""
        local, refs = 0, []
        while True:
            local += 1
            r.attempts[step.id] += 1
            n = r.attempts[step.id]
            trace, verdict = self.robot.execute(step)
            trace = trace.model_copy(update={"attempt": n, "checks": evaluate_checks(step, trace, verdict)})
            verdict = verdict.model_copy(update={"attempt": n})
            ref = f"trace:{r.id}:{step.id}:{n}"
            self.traces[ref] = trace
            refs.append(ref)
            if verdict.status != "inconclusive" or verdict.label == "unsafe" or local > r.policy.retries_per_step or r.stop_requested.is_set():
                return trace, verdict, local, refs

    def _refresh_scene(self) -> None:
        current = getattr(self.robot, "current_scene", None)
        if current and self.report.scene is not None:
            self.report = self.report.model_copy(update={"scene": current()})

    def _run_plan(self, r: _Routine) -> None:
        queue_ = deque(clamp(s, self.max_force_n) for s in r.plan.steps)
        done, since, resolved = 0, [], 0
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
            if self.report.scene is not None and self.report.scene.stale:  # never on old poses, whatever the plan or policy
                r.stale_hold = True
                decision = self._hold(r, snapshot(stop="escalation", escalation=Escalation(
                    code="pose_unstable", tried=[], measured={"pattern": "device_moved", "steps_not_run": [s.id for s in queue_][:8]}, options=["abort"])))
                r.stops.put(snapshot(stop="done", status="stopped", reason=decision.note or "the device moved"))
                return
            step = queue_.popleft()
            try:
                trace, verdict, attempts, refs = self._attempt(r, step)
            except Exception as e:  # keep the verdicts since the last stop: they're real
                traceback.print_exc()  # the stop carries only the message: where it came from goes to this terminal
                r.stops.put(snapshot(stop="safety_abort", status="aborted", reason=f"{type(e).__name__}: {e}"))
                return
            done += 1
            resolved += attempts > 1 and verdict.status == "passed"
            since.append(self._summary(trace, verdict, attempts, refs))
            self._refresh_scene()
            if verdict.label == "unsafe":
                r.stops.put(snapshot(stop="safety_abort", status="aborted", reason=verdict.reason))
                return
            if self.report.scene is not None and self.report.scene.stale and queue_ and self._escalation(step, trace, verdict, attempts) is None:
                continue  # the top of the loop holds for this, so one move is one stop
            escalation = self._escalation(step, trace, verdict, attempts)
            drift = self._pose_escalation(r, step, trace, attempts)  # every step, so a run of misses still counts
            if drift is not None:
                if escalation is None or escalation.code == "retries_exhausted":
                    escalation = drift  # a robot that keeps missing because the device moved: that's the news
                else:  # a clean failure still reports as one, with this beside it
                    escalation = escalation.model_copy(update={"measured": {**escalation.measured, "pose_drift": drift.measured}})
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
                queue_.extend(clamp(s, self.max_force_n) for s in decision.steps)
        r.stops.put(snapshot(stop="done", status="completed"))

    @staticmethod
    def _summary(trace: StepTrace, verdict: StepVerdict, attempts: int, refs: list[str]) -> StepSummary:
        measures = {k: trace.measures[k] for k in SUMMARY_MEASURES if trace.measures.get(k) not in (None, [], "")}
        return StepSummary(verdict=verdict, attempts=attempts, peak_force_n=trace.peak_force_n, travel_mm=trace.travel_mm,
                           stop_reason=trace.stop_reason, readout_change=trace.readout_change, measures=measures, checks=trace.checks,
                           trace_ref=refs[-1], attempt_refs=refs[:-1])

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
        failed = [c for c in trace.checks if c.passed is False]
        if failed:  # System 2 asked for a number and this isn't it. The verdict stands, and what it means is System 2's to work out
            return Escalation(code="unexpected_response", step=step.id, target=step.target, tried=common["tried"],
                              measured={**measured, "failed_checks": [c.model_dump(mode="json") for c in failed]})
        return None

    @staticmethod
    def _pose_escalation(r: _Routine, step: Step, trace: StepTrace, attempts: int) -> Escalation | None:
        """pose_unstable: the corrections each step needs keep getting larger, so the device may have moved."""
        for key, values in r.pose_history.items():
            if key == "contact_offset_mm" and step.skill not in ("press", "push_latch"):
                continue  # on a sideways push, this is how far along the path it first touched
            value = trace.measures.get(key)
            if isinstance(value, (int, float)):
                values.append(round(abs(float(value)), 2))
        drift = _pose_drift(r.pose_history)
        if drift is None:
            return None
        for values in r.pose_history.values():  # once per trend: it wakes System 2, and doesn't then wake it every step
            values.clear()
        return Escalation(code="pose_unstable", step=step.id, target=step.target, tried=[f"{step.skill} x{attempts}"], measured=drift)
