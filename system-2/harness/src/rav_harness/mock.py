"""The planted-fault demo as a script, so the whole loop runs with no robot, sim, GPU or network.

Rev A has the two faults from the plan: button 2 binds (clearance 0.15 mm) and the door needs a pinch.
Rev B has both patched. The Console, the report and the integration test all build against this. FakeSystem1 stands in
for System 1's server and applies the same stop rules, so all of System 2 runs and tests with nothing from System 1.
"""
from __future__ import annotations

from collections.abc import Generator

from rav_contracts import (Checkpoint, Control, Decision, Escalation, EscalationPolicy, Plan,
                           RoutineHandle, RoutineName, SceneInventory, SceneReport, Step, StepSummary, StepTrace,
                           StepVerdict, SystemStatus, TestRequest)

from .analyst import rule_analyst
from .loop import run_test
from .runlog import RunLog
from .trace import ToolRejected, Tracer

CONTROLS = [("button_1", "button", 0), ("button_2", "button", 25), ("button_3", "button", 50), ("door", "door", 90)]


class MockBackend:
    def __init__(self, revision: str = "A"):
        self.revision = revision

    def perceive(self) -> SceneInventory:
        controls = [Control(id=i, kind=k, pos_mm=(250.0, y - 25.0, 60.0), normal=(-0.7, 0.0, 0.7), source="mock")
                    for i, k, y in CONTROLS]
        controls.append(Control(id="display", kind="display", pos_mm=(250.0, 0.0, 110.0), normal=(-1.0, 0.0, 0.0), source="mock"))
        return SceneInventory(controls=controls, notes=["mock scene"])

    def default_plan(self, scene: SceneInventory) -> Plan:
        steps = [Step(id=f"s{n + 1}", skill="push_latch" if c.kind == "door" else "observe" if c.kind == "display" else "press",
                      target=c.id, params={"force_limit": 6}, expected="the readout changes")
                 for n, c in enumerate(scene.controls)]
        return Plan(plan_id=f"mock-rev{self.revision}", steps=steps, source="mock")

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        fixed = self.revision != "A"
        if step.target == "button_2" and not fixed:
            trace = StepTrace(step=step.id, stop_reason="force_limit", duration_s=3.2, peak_force_n=6.0, travel_mm=0.3,
                              force_trace=[(0.0, 0.0), (1.0, 2.2), (2.0, 4.6), (3.0, 6.0)])
            verdict = StepVerdict(step=step.id, target=step.target, status="failed", label="stuck",
                                  reason="reached the 6.0 N limit with 0.3 mm of travel; no readout changed",
                                  evidence=[f"{step.id} force trace"])
        elif step.target == "door" and not fixed:
            trace = StepTrace(step=step.id, stop_reason="force_limit", duration_s=4.0, peak_force_n=6.0, travel_mm=0.5)
            verdict = StepVerdict(step=step.id, target=step.target, status="failed", label="accessibility",
                                  reason="door stayed shut after a 6.0 N flat-pad push; it opens only with a pinch, which the no-thumbs rule bans",
                                  evidence=[f"{step.id} force trace"])
        else:
            channel = {"button_1": "BTN1", "button_2": "BTN2", "button_3": "BTN3", "door": "DOOR", "display": "LCD"}[step.target]
            trace = StepTrace(step=step.id, stop_reason="target_travel", duration_s=2.5, peak_force_n=2.9, travel_mm=2.7,
                              force_trace=[(0.0, 0.0), (1.0, 1.4), (2.0, 2.9)], readout_change={channel: [0, 1, 0]})
            verdict = StepVerdict(step=step.id, target=step.target, status="passed", reason=f"{step.target} drives {channel}", channel=channel)
        return trace, verdict

    def close(self) -> None:
        pass


class FakeSystem1:
    """The seven tools in-process, over a scripted robot. Mirrors rav_server.engine's stops; each has tests for them."""

    def __init__(self, robot: MockBackend | None = None):
        self.robot = robot or MockBackend()
        self.report, self.traces = SceneReport(), {}
        self.routine: Generator[Checkpoint, Decision, None] | None = None
        self.routines, self.resumes, self.executed = 0, [], []

    def system_status(self) -> SystemStatus:
        return SystemStatus(state="idle", robot="fake", skills=["press", "push_latch", "observe"])

    def scene_get(self) -> SceneReport:
        return self.report

    def evidence_get(self, ref: str) -> StepTrace:
        return self.traces[ref]

    def routine_start(self, routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        self.routines += 1
        policy = policy or EscalationPolicy()
        self.routine = self._explore() if routine == "explore" else self._run_plan(plan, policy)
        self.next: Checkpoint | None = next(self.routine)
        return RoutineHandle(routine_id=f"r{self.routines}", routine=routine)

    def routine_wait(self, routine_id: str, timeout_s: float = 30.0) -> Checkpoint:
        stop, self.next = self.next, None
        return stop

    def routine_resume(self, routine_id: str, decision: Decision) -> None:
        self.resumes.append(decision)
        self.next = self.routine.send(decision)

    def routine_stop(self, routine_id: str) -> None:
        pass

    def close(self) -> None:
        self.robot.close()

    def _explore(self):
        scene = self.robot.perceive()
        self.report = SceneReport(scene=scene, fallback_plan=self.robot.default_plan(scene))
        n = len(scene.controls)
        yield Checkpoint(routine_id=f"r{self.routines}", stop="done", status="completed", steps_done=n, steps_total=n)

    def _run_plan(self, plan: Plan, policy: EscalationPolicy):
        rid, queue, done, since = f"r{self.routines}", list(plan.steps), 0, []
        while queue:
            step = queue.pop(0)
            self.executed.append(step)
            trace, verdict = self.robot.execute(step)
            ref = f"trace:{rid}:{step.id}"
            self.traces[ref] = trace
            done += 1
            since.append(StepSummary(verdict=verdict, peak_force_n=trace.peak_force_n, travel_mm=trace.travel_mm,
                                     stop_reason=trace.stop_reason, readout_change=trace.readout_change, trace_ref=ref))
            base = dict(routine_id=rid, steps_done=done, steps_total=done + len(queue))
            if verdict.label == "unsafe":
                yield Checkpoint(**base, stop="safety_abort", status="aborted", verdicts=since, reason=verdict.reason)
                return
            if verdict.status == "failed":
                code = "unexpected_response" if verdict.label == "wrong_behavior" else "step_failed"
                stop = dict(stop="escalation", escalation=Escalation(code=code, step=step.id, target=step.target, tried=[f"{step.skill} x1"],
                                                                      measured={"peak_force_n": trace.peak_force_n, "travel_mm": trace.travel_mm}))
            elif verdict.status == "inconclusive":
                stop = dict(stop="escalation", escalation=Escalation(code="retries_exhausted", step=step.id, target=step.target))
            elif policy.checkpoint_every and queue and done % policy.checkpoint_every == 0:
                stop = dict(stop="checkpoint")
            else:
                continue
            decision = yield Checkpoint(**base, **stop, status="paused", verdicts=since)
            since = []
            if decision.kind == "abort":
                yield Checkpoint(routine_id=rid, stop="done", status="stopped", steps_done=done, steps_total=done, reason=decision.note)
                return
            if decision.kind == "skip":
                queue = [s for s in queue if s.target not in decision.targets]
            elif decision.kind == "amend":
                queue = list(decision.steps)
        yield Checkpoint(routine_id=rid, stop="done", status="completed", steps_done=done, steps_total=done, verdicts=since)


def mock_system_1(revision: str = "A") -> FakeSystem1:
    return FakeSystem1(MockBackend(revision))


class MockModelBackend(MockBackend):
    """A scripted model driving the mock robot through its tools, with one failure of every kind, so the Console's
    trace can be built and tested before a frontier model is connected. Nothing here came from a real model."""
    MODEL = "mock-model"

    def __init__(self, tracer: Tracer, request: TestRequest):
        super().__init__("A")
        self.tracer, self.request = tracer, request

    def think(self, **fields) -> str:
        fields.setdefault("stop_reason", "tool_use")
        return self.tracer.turn(self.MODEL, tokens_in=fields.pop("tokens_in", 1800), tokens_out=fields.pop("tokens_out", 120), latency_ms=fields.pop("latency_ms", 1400.0), **fields)

    def attempt(self, turn: str, tool: str, args: dict, fn):
        try:
            return self.tracer.call(tool, args, fn, turn=turn)
        except (ToolRejected, TimeoutError):
            return None

    def perceive(self) -> SceneInventory:
        self.tracer.stage = "MAP"
        turn = self.think(input=f"Test {self.request.product}. {self.request.instruction}", thinking="Nothing is known about this device yet, so scan it first.", text="Scanning the panel.")
        return self.tracer.call("perception.scan", {}, lambda: super(MockModelBackend, self).perceive(), turn=turn,
                                summarize=lambda s: {"controls": [c.id for c in s.controls]})

    def propose(self, scene: SceneInventory) -> Plan:
        self.tracer.stage = "PLAN"
        known = {c.id for c in scene.controls}

        def validate(targets: list[str]) -> dict:
            missing = [t for t in targets if t not in known]
            if missing:
                raise ToolRejected("unknown_target", f"{missing[0]} isn't in the scene. Known controls: {sorted(known)}")
            return {"valid": True, "steps": len(targets)}

        wrong = ["button_1", "button_2", "button_9", "door", "display"]
        turn = self.think(input="perception.scan returned 5 controls", thinking="There are probably as many buttons as a keypad has, so I'll include button_9.", text="Proposing a plan.", tokens_out=340)
        self.attempt(turn, "plan.validate", {"targets": wrong}, lambda: validate(wrong))
        right = [c.id for c in scene.controls]
        turn = self.think(input="plan.validate error: button_9 isn't in the scene", text="I invented button_9. Using only the scanned controls.", tokens_out=210)
        self.attempt(turn, "plan.validate", {"targets": right}, lambda: validate(right))
        return super().default_plan(scene)

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        self.tracer.stage, self.tracer.step = "TEST", step.id
        args = {"skill": step.skill, "target": step.target, "force_limit": 6}
        run = lambda: super(MockModelBackend, self).execute(step)  # noqa: E731
        brief = lambda r: {"status": r[1].status, "peak_force_n": r[0].peak_force_n, "travel_mm": r[0].travel_mm}  # noqa: E731
        call = lambda turn, a=args: self.tracer.call("robot.run_step", a, run, turn=turn, summarize=brief)  # noqa: E731
        if step.target == "button_2":
            result = call(self.think(input=f"Next: {step.id}", text=f"Pressing {step.target}."))
            self.think(input=f"robot.run_step: {brief(result)}", thinking="It stopped at the force limit, so the press must have registered.",
                       text="button_2 works.", claims={step.id: "passed"}, stop_reason="end_turn")
        elif step.target == "button_3":
            def stalls():
                raise TimeoutError("no reply from the arm controller in 30 s")
            turn = self.think(input=f"Next: {step.id}", text=f"Pressing {step.target}.")
            self.attempt(turn, "robot.run_step", args, stalls)
            result = call(self.think(input="robot.run_step error: no reply from the arm controller in 30 s", text="A timeout says nothing about the button. Trying once more."))
        elif step.target == "door":
            def too_hard():
                raise ToolRejected("bad_args", "force_limit 40 is over this skill's 6 N cap")
            hard = {**args, "force_limit": 40}
            turn = self.think(input=f"Next: {step.id}", thinking="Doors can be stiff, so push harder.", text="Pushing the door hard.")
            self.attempt(turn, "robot.run_step", hard, too_hard)
            turn = self.think(input="robot.run_step error: force_limit 40 is over this skill's 6 N cap", text="Pushing the door hard.")
            self.attempt(turn, "robot.run_step", hard, too_hard)
            result = call(self.think(input="robot.run_step error: force_limit 40 is over this skill's 6 N cap", text="The cap is firm. Using 6 N."))
        elif step.target == "display":
            self.think(input=f"Next: {step.id}", text="I'll read the displ", stop_reason="max_tokens", error="the reply was cut off before any tool call", error_kind="max_tokens", tokens_out=1024)
            result = call(self.think(input="Your last reply was cut off. Continue.", text="Reading the display."))
        else:
            result = call(self.think(input=f"Next: {step.id}", text=f"Pressing {step.target}."))
        self.tracer.step = None
        return result


# The analyst for the mock demo: the rule analyst, which knows the two planted faults.
mock_analyst = rule_analyst


def mock_model_run(run_id: str, root: str = "runs"):
    """Rev A with the scripted model at the controls."""
    log = RunLog(run_id, root)
    request = TestRequest(request_id=run_id, product="Test box, scripted model (mock)", revision="A")
    backend = MockModelBackend(Tracer(log, caller="model"), request)
    return run_test(FakeSystem1(backend), request, log, planner=lambda _request, scene, _fallback: backend.propose(scene))
