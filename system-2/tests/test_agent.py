"""The agent loop against a fake robot and a scripted model: no key, no network, no sim. Every way a turn can go wrong."""
import json
import pathlib
import re

import pytest
from rav_contracts import ActionSpec, Checkpoint, Control, Escalation, ParamSpec, Plan, Report, SceneInventory, SteerCommand, Step, StepTrace, StepVerdict, TestRequest
from rav_contracts import CheckResult as Result
from rav_harness import prompts
from rav_harness.agent import AgentConfig, run_agent, sim_auto_approve, trim
from rav_harness.loop import Steering
from rav_harness.manual import Manual
from rav_harness.client import ToolFailed
from rav_harness.loop import run_test
from rav_harness.mock import FakeSystem1, MockBackend
from rav_harness.model import Message, ModelReply, ScriptedModel, ToolRequest, ToolResult, Unavailable, call
from rav_harness.reward import coverage, reward
from rav_harness.runlog import RunLog, read_events
from rav_harness.verdicts import findings_from, settle_one

REQUEST = TestRequest(request_id="t", product="A product", revision="A", spec={"planted_fault": "SECRET-ANSWER jammed part"})
HARNESS = pathlib.Path(__file__).resolve().parents[1] / "harness/src/rav_harness"


def say(*calls, text="", thinking="", **kw):
    return ModelReply(model="", text=text, thinking=thinking, calls=list(calls), tokens_in=10, tokens_out=5, **kw)


def steps(*targets, skill="press", prefix="s"):
    return [{"id": f"{prefix}{n}", "skill": skill, "target": t} for n, t in enumerate(targets, 1)]


class Robot(MockBackend):
    """Attempts come from a script per target; anything unscripted passes and drives a reading."""

    def __init__(self, script=None, controls=("c1", "c2", "c3"), checks=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.ids, self.checks, self.executed = list(controls), checks or {}, []
        self.offset = 0.0
        self.explores = 0

    def perceive(self):
        self.explores += 1
        return SceneInventory(controls=[Control(id=i, kind="button", pos_mm=(250.0 + self.offset, 30.0 * n, 60.0), normal=(0.0, 0.0, 1.0), source="mock") for n, i in enumerate(self.ids)])

    def default_plan(self, scene):
        return Plan(plan_id="rules", steps=[Step(id=f"r{n}", skill="press", target=c.id) for n, c in enumerate(scene.controls)], source="rules")

    def execute(self, step):
        self.executed.append(step)
        status = (self.script.get(step.target) or ["passed"]).pop(0) if self.script.get(step.target) else "passed"
        label = {"failed": "stuck", "inconclusive": "inconclusive", "unsafe": "unsafe"}.get(status)
        if status == "unsafe":
            status = "inconclusive"
        trace = StepTrace(step=step.id, stop_reason="ok", peak_force_n=2.0, travel_mm=1.0 if status == "passed" else 0.0,
                          readout_change={f"R_{step.target}": [0, 1]} if status == "passed" else {}, checks=self.checks.get(step.id, []))
        return trace, StepVerdict(step=step.id, target=step.target, status=status, label=label, reason=f"scripted {status}")


class Fake(FakeSystem1):
    """The real tools' behaviour for what the agent adds: home, and checks on a stop."""

    def system_status(self):
        s = super().system_status()
        return s.model_copy(update={"actions": [ActionSpec(skill="press", kinds=["button"], params=[ParamSpec(name="force_limit", min=0.1, max=14)]),
                                                ActionSpec(skill="reposition", kinds=["object"], params=[ParamSpec(name="dx_mm", min=-50, max=50)])]})

    def routine_start(self, routine, plan=None, policy=None):
        self.started = getattr(self, "started", []) + [routine]
        if routine == "home":
            self.routines += 1
            def go():
                yield Checkpoint(routine_id=f"r{self.routines}", stop="done", status="completed")
            self.routine = go()
            self.next = next(self.routine)
            from rav_contracts import RoutineHandle
            return RoutineHandle(routine_id=f"r{self.routines}", routine="home")
        return super().routine_start(routine, plan, policy)


class FakeS1(Fake):
    """Answers stops by forwarding, so decisions reach the fake's own generator."""

    def _run_plan(self, plan, policy):
        gen = FakeSystem1._run_plan(self, plan, policy)
        cp = next(gen)
        while True:
            for s in cp.verdicts:
                s.checks = self.traces[s.trace_ref].checks
            decision = yield cp
            try:
                cp = gen.send(decision)
            except StopIteration:
                return


def go(tmp_path, script, robot=None, approve=sim_auto_approve, config=None, manual=None, steering=None, ask=None, on_delta=None, wait=None, system1=None):
    robot = robot or Robot()
    system1 = system1 or FakeS1(robot)
    client = ScriptedModel(script)
    log = RunLog("r", tmp_path)
    config = config or AgentConfig(check_back=False)  # scripted plans here test other rules; check-back has its own tests
    report = run_agent(system1, REQUEST, log, client, approve=approve, config=config, manual=manual, steering=steering, ask=ask, on_delta=on_delta, wait=wait)
    return report, read_events(log.path), client, robot


def happy(targets=("c1", "c2", "c3")):
    return [say(call("get_status")), say(call("look_at_device"), thinking="Let me look."), say(call("propose_plan", steps=steps(*targets))), say(call("run_plan")),
            say(call("finish_run", summary="All good."), text="Done.")]


def errors_told(client):
    return [r.content["error"] for req in client.requests for m in req["messages"] for r in m.results if "error" in r.content]


def test_a_clean_run_ends_in_a_report_with_every_turn_and_call_traced(tmp_path):
    report, events, client, robot = go(tmp_path, happy())
    assert report.reward.value == 1.0 and not report.findings and report.coverage.passed == ["c1", "c2", "c3"]
    types = [e.type for e in events]
    assert types.count("model_turn") == 5 and "agent_state" in types and types[-1] == "run_finished"
    calls = [e.payload for e in events if e.type == "tool_call"]
    assert {c["tool"] for c in calls if c["caller"] == "model"} >= {"look_at_device", "propose_plan", "run_plan", "finish_run"}
    assert any(c["tool"] == "system1.routine_start" for c in calls)
    thinking = [e.payload["thinking"] for e in events if e.type == "model_turn"]
    assert "Let me look." in thinking
    assert any(e.type == "approved" and e.payload["by"] == "auto (sim)" for e in events)
    assert (tmp_path / "r/report.json").is_file() and (tmp_path / "r/model/turn-1.json").is_file()


def test_clean_checkpoints_cost_no_model_turn(tmp_path):
    report, events, client, robot = go(tmp_path, happy())
    assert len(robot.executed) == 3 and sum(e.type == "crossing" for e in events) >= 3
    assert len(client.requests) == 5


def test_nothing_moves_on_a_bad_plan_and_every_problem_is_named(tmp_path):
    bad = [{"id": "s1", "skill": "press", "target": "nope"}, {"id": "s2", "skill": "juggle", "target": "c1"},
           {"id": "s3", "skill": "press", "target": "c1", "params": {"force_limit": 99}}, {"id": "s4", "skill": "press", "target": "c2", "params": {"spin": 1}}]
    script = [say(call("look_at_device")), say(call("propose_plan", steps=bad)), *happy()[2:]]
    report, events, client, robot = go(tmp_path, script)
    told = errors_told(client)[0]
    assert all(word in told for word in ("nope", "juggle", "force_limit", "spin"))
    assert [s.id for s in robot.executed] == ["s1", "s2", "s3"]
    rejected = next(e.payload for e in events if e.type == "tool_call" and not e.payload["ok"])
    assert rejected["layer"] == "model" and rejected["error_kind"] == "bad_args"


@pytest.mark.parametrize("name, args, kind", [
    ("no_such_tool", {}, "unknown_tool"), ("get_evidence", {"ref": "nope"}, "unknown_target"), ("run_plan", {}, "refused"),
    ("answer_stop", {"kind": "continue"}, "refused"), ("propose_plan", {"steps": "x"}, "bad_args"), ("look_at_device", {"extra": 1}, "bad_args"),
])
def test_each_wrong_call_comes_back_readable_and_is_the_models(tmp_path, name, args, kind):
    report, events, client, _ = go(tmp_path, [ModelReply(model="", calls=[ToolRequest("x", name, args)]), *happy()])
    assert errors_told(client)
    bad = next(e.payload for e in events if e.type == "tool_call" and e.payload["tool"] == name and not e.payload["ok"])
    assert bad["error_kind"] == kind and bad["layer"] == "model" and report.reward.value == 1.0


def test_the_same_rejected_call_gets_told_then_ends_the_run(tmp_path):
    stuck = lambda: say(call("run_plan"))  # noqa: E731
    report, events, client, _ = go(tmp_path, [stuck() for _ in range(12)], config=AgentConfig(max_repeats=3, check_back=False))
    assert any("same rejected call" in e for e in errors_told(client))
    assert any(e.type == "message" and "repeating" in e.payload["text"] for e in events) and events[-1].payload["status"] == "aborted"


def test_a_cut_off_reply_and_a_reply_with_no_call_get_a_nudge(tmp_path):
    cut = ModelReply(model="", text="I'll", stop_reason="max_tokens")
    report, events, client, _ = go(tmp_path, [cut, say(text="Thinking about it."), *happy()])
    turns = [e.payload for e in events if e.type == "model_turn"]
    assert turns[0]["error_kind"] == "max_tokens" and report.reward.value == 1.0
    said = [m.text for m in client.requests[2]["messages"] if m.role == "user"]
    assert prompts.CUT_OFF in said and prompts.NO_CALL in said


def test_budgets_end_the_run_with_a_report(tmp_path):
    report, events, _, _ = go(tmp_path, lambda m, t: say(call("get_status")), config=AgentConfig(max_turns=3))
    assert sum(e.type == "model_turn" for e in events) == 3 and isinstance(report, Report)
    assert events[-1].payload["status"] == "aborted" and any("turn limit" in str(e.payload) for e in events if e.type == "message")
    report, events, _, _ = go(tmp_path, lambda m, t: say(call("get_status")), config=AgentConfig(max_tokens=20))
    assert any("token limit" in str(e.payload) for e in events if e.type == "message")


def test_a_person_refusing_a_plan_stops_it_moving(tmp_path):
    answers = iter([None, "Ada"])
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1"))), say(call("run_plan")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))),
              say(call("run_plan")), say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script, approve=lambda kind, ref: next(answers))
    assert len(robot.executed) == 3 and any(e.type == "approved" and e.payload["by"] == "Ada" for e in events)


def test_auto_approval_is_refused_for_a_real_robot(tmp_path):
    class Real(FakeS1):
        def system_status(self):
            return super().system_status().model_copy(update={"robot": "real"})
    with pytest.raises(PermissionError):
        go(tmp_path, happy(), system1=Real(Robot()))


def test_a_new_target_in_an_amendment_needs_a_person_but_a_retest_doesnt(tmp_path):
    asked = []
    def approve(kind, ref):
        asked.append(kind)
        return "Ada"
    robot = Robot({"c1": ["failed"]}, controls=("c1", "c2", "c3", "c4"))
    plan = steps("c1", "c2", "c3")
    script = [say(call("look_at_device")), say(call("propose_plan", steps=plan)), say(call("run_plan")),
              say(call("answer_stop", kind="amend", steps=[{"id": "again", "skill": "press", "target": "c1"}, *plan[1:]])),
              say(call("propose_plan", steps=[{"id": "new", "skill": "press", "target": "c4"}])), say(call("run_plan")), say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script, robot, approve=approve)
    assert asked == ["plan", "plan"]
    amended = next(e.payload for e in events if e.type == "plan_amended")
    assert amended["level"] < 2 and "c4" in report.coverage.passed


# --- the retest rule -----------------------------------------------------------------------------

def v(status, target="c1"):
    return StepVerdict(step="s", target=target, status=status, label="stuck" if status == "failed" else None, reason=status)


@pytest.mark.parametrize("attempts, status, confirmed", [
    (["failed"], "failed", False), (["failed", "failed"], "failed", True), (["failed", "inconclusive", "failed"], "failed", True),
    (["failed", "passed"], "intermittent", True), (["passed", "failed"], "intermittent", True), (["failed", "passed", "failed"], "intermittent", True),
    (["passed", "failed", "failed"], "failed", True), (["inconclusive", "passed"], "passed", True), (["inconclusive"], "inconclusive", True),
    (["skipped"], "skipped", True), (["observed"], "observed", True), (["inconclusive", "inconclusive"], "inconclusive", True),
])
def test_what_attempts_add_up_to(attempts, status, confirmed):
    s = settle_one("c1", [v(a) for a in attempts])
    assert (s.status, s.confirmed) == (status, confirmed)


def test_a_robot_error_then_a_clean_retest_isnt_a_broken_device(tmp_path):
    robot = Robot({"c1": ["failed", "passed"]})
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
              say(call("answer_stop", kind="amend", steps=[{"id": "again", "skill": "press", "target": "c1"}, *steps("c2", "c3")[0:0], {"id": "s2", "skill": "press", "target": "c2"}, {"id": "s3", "skill": "press", "target": "c3"}])),
              say(call("finish_run", summary="x"))]
    report, events, _, _ = go(tmp_path, script, robot)
    assert report.coverage.intermittent == ["c1"] and report.coverage.failed == []
    assert [f.label for f in report.findings] == ["intermittent"]


def test_a_repeated_failure_is_a_confirmed_finding_recomputable_from_the_log(tmp_path):
    robot = Robot({"c1": ["failed", "failed"]})
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
              say(call("answer_stop", kind="amend", steps=[{"id": "again", "skill": "press", "target": "c1"}, {"id": "s2", "skill": "press", "target": "c2"}, {"id": "s3", "skill": "press", "target": "c3"}])),
              say(call("answer_stop", kind="continue")), say(call("finish_run", summary="x"))]
    report, events, _, _ = go(tmp_path, script, robot)
    assert report.coverage.failed == ["c1"] and report.findings[0].confirmed and report.findings[0].event_seqs
    verdicts = [StepVerdict(**e.payload["verdict"]) for e in events if e.type == "step_finished"]
    controls = next(e for e in reversed(events) if e.type == "scene_ready").payload["controls"]
    assert reward(coverage([Control(**c) for c in controls], verdicts)) == report.reward
    assert [f.target for f in findings_from(verdicts)] == ["c1"]


# --- dependent procedures ------------------------------------------------------------------------

def failed_check(metric="reading:run", want="start", got="refused"):
    return [Result(metric=metric, op="==", value=want, actual=got, passed=False)]


def test_a_failed_check_counts_only_when_what_it_needs_was_truly_there(tmp_path):
    def run(requires, robot_checks):
        robot = Robot(checks=robot_checks, controls=("a", "b"))
        plan = [{"id": "first", "skill": "press", "target": "a"},
                {"id": "then", "skill": "press", "target": "b", "check": [{"metric": "reading:run", "op": "==", "value": "start", "source": "manual"}], "requires": requires}]
        script = [say(call("look_at_device")), say(call("propose_plan", steps=plan)), say(call("run_plan"))]
        script += [say(call("answer_stop", kind="continue")), say(call("finish_run", summary="x"))]
        script = script[:3] + [say(call("finish_run", summary="x"))]
        return go(tmp_path, script, robot)
    # R_a is 1 after the first step, so this condition holds and the refusal is a finding
    report, events, _, _ = run([{"metric": "reading:R_a", "op": "==", "value": "1"}], {"then": failed_check()})
    assert report.coverage.failed == ["b"] and report.findings[0].label == "wrong_feedback"
    judged = next(e.payload for e in events if e.type == "check_judged")
    assert judged["counted"] and judged["met"]
    # this condition never held, so the refusal says nothing about the product
    report, events, _, _ = run([{"metric": "reading:R_a", "op": "==", "value": "7"}], {"then": failed_check()})
    assert report.coverage.passed == ["a", "b"] and not report.findings
    judged = next(e.payload for e in events if e.type == "check_judged")
    assert not judged["counted"] and "R_a" in judged["why"]
    # a reading nobody has seen doesn't count as met either
    report, _, _, _ = run([{"metric": "reading:NEVER", "op": "==", "value": "1"}], {"then": failed_check()})
    assert not report.findings


def test_finish_needs_every_control_accounted_for(tmp_path):
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1"))), say(call("run_plan")), say(call("finish_run", summary="x")),
              say(call("finish_run", summary="y", controls=[{"id": "c2", "why": "out of reach"}, {"id": "c3", "why": "needs a pinch"}]))]
    report, events, client, _ = go(tmp_path, script)
    assert any("c2" in e and "c3" in e for e in errors_told(client)) and report.coverage.passed == ["c1"]
    assert events[-1].payload["status"] == "completed"


def test_a_claim_that_disagrees_with_the_sensors_goes_on_the_record(tmp_path):
    script = happy()[:-1] + [say(call("finish_run", summary="x", controls=[{"id": "c1", "status": "failed"}]))]
    _, events, _, _ = go(tmp_path, script)
    assert any(e.type == "message" and "attempts add up to passed" in e.payload["text"] for e in events)


# --- recovery ------------------------------------------------------------------------------------

def test_a_safety_stop_needs_a_person_then_the_run_goes_on(tmp_path):
    asked = []
    def approve(kind, ref):
        asked.append(kind)
        return "Ada"
    robot = Robot({"c2": ["unsafe"]})
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
              say(call("propose_plan", steps=steps("c2", "c3"))), say(call("recover", action="home")),
              say(call("propose_plan", steps=[{"id": "s9", "skill": "press", "target": "c2"}, {"id": "s10", "skill": "press", "target": "c3"}])), say(call("run_plan")),
              say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script, robot, approve=approve)
    assert "safety" in asked and any("recover" in e for e in errors_told(client))
    assert report.coverage.passed == ["c1", "c2", "c3"] and events[-1].payload["status"] == "completed"


def test_a_refused_recovery_can_still_finish(tmp_path):
    robot = Robot({"c2": ["unsafe"]})
    def approve(kind, ref):
        return None if kind == "safety" else "Ada"
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")), say(call("recover", action="home")),
              say(call("finish_run", summary="x", controls=[{"id": "c3", "why": "the arm is stopped"}]))]
    report, events, _, _ = go(tmp_path, script, robot, approve=approve)
    assert report.coverage.passed == ["c1"] and report.coverage.inconclusive == ["c2"] and events[-1].payload["status"] == "aborted"


def test_a_pipeline_error_needs_no_person_and_a_look_can_be_retried(tmp_path):
    class Flaky(FakeS1):
        fails = 1
        def _explore(self):
            if self.fails:
                self.fails -= 1
                yield Checkpoint(routine_id=f"r{self.routines}", stop="pipeline_error", status="aborted", reason="couldn't find a plain panel")
                return
            yield from super()._explore()
    script = [say(call("look_at_device")), *happy()[1:]]
    asked = []
    report, events, client, _ = go(tmp_path, script, system1=Flaky(Robot()), approve=lambda k, r: asked.append(k) or "Ada")
    assert report.reward.value == 1.0 and asked == ["plan"]
    assert any(e.type == "crossing" and e.payload["stop"] == "pipeline_error" for e in events)


def test_the_api_going_down_finishes_on_the_rule_plan_and_says_so(tmp_path):
    report, events, _, _ = go(tmp_path, [say(call("look_at_device")), Unavailable("out of quota")])
    assert report.coverage.passed == ["c1", "c2", "c3"]
    assert any(e.type == "plan_ready" and e.payload["source"] == "rules" for e in events)
    assert any(e.type == "message" and "rule-based" in e.payload["text"] for e in events)
    bad = next(e.payload for e in events if e.type == "model_turn" and e.payload.get("error"))
    assert bad["error_kind"] == "api_error" and bad["layer"] == "pipeline"


def test_the_api_going_down_at_a_stop_closes_the_routine_first(tmp_path):
    robot = Robot({"c1": ["failed"]})
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")), Unavailable("503")]
    report, events, _, _ = go(tmp_path, script, robot)
    assert report.coverage.failed == ["c1"] and report.coverage.passed == ["c2", "c3"]


# --- the device moving ---------------------------------------------------------------------------

class Drifting(Robot):
    """The device is bumped after `after` steps: whatever then runs misses, until someone looks again."""

    def __init__(self, after, **kw):
        super().__init__(**kw)
        self.after, self.done, self.moved = after, 0, False

    def execute(self, step):
        self.done += 1
        if self.done > self.after and not self.moved:
            self.moved = True
            self.offset = 40.0
        if self.moved and self.explores < 2:
            self.executed.append(step)
            return StepTrace(step=step.id, stop_reason="landed", travel_mm=0.0), StepVerdict(step=step.id, target=step.target, status="inconclusive", label="inconclusive", reason="never touched it")
        return super().execute(step)


def test_the_device_moving_mid_run_is_noticed_and_recovered_from(tmp_path):
    robot = Drifting(1, controls=("c1", "c2", "c3", "c4"))
    def model(messages, tools):
        results = [r for m in messages[-1:] for r in m.results]
        last = results[-1].content if results else {}
        if not results:
            return say(call("look_at_device"))
        if results[-1].call.name == "look_at_device" and last.get("scene_version") == 1:
            return say(call("propose_plan", steps=steps("c1", "c2", "c3", "c4")))
        if results[-1].call.name == "propose_plan":
            return say(call("run_plan"))
        if last.get("device_may_have_moved"):
            return say(call("recover", action="re_explore"))
        if last.get("next") == "answer_stop":
            return say(call("answer_stop", kind="continue"))
        if results[-1].call.name == "recover":
            left = [i for i, s in last["progress"].items() if s in ("untested", "inconclusive")]
            return say(call("propose_plan", steps=[{"id": f"re-{i}", "skill": "press", "target": i} for i in left]))
        return say(call("finish_run", summary="done"))
    report, events, client, robot = go(tmp_path, model, robot)
    assert robot.explores == 2
    assert sorted(report.coverage.passed) == ["c1", "c2", "c3", "c4"], report.coverage
    assert not report.findings and events[-1].payload["status"] == "completed"
    first = next(e for e in events if e.type == "step_finished")
    assert first.payload["verdict"]["status"] == "passed"  # what ran before the move keeps its verdict


def test_a_plan_from_before_a_new_look_cant_run(tmp_path):
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("look_at_device")), say(call("run_plan")),
              say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")), say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script)
    assert any("No approved plan" in e for e in errors_told(client)) and report.reward.value == 1.0


def test_controls_keep_their_verdicts_across_a_look_even_when_ids_change(tmp_path):
    class Renamed(Robot):
        def perceive(self):
            scene = super().perceive()
            if self.explores == 1:
                return scene
            return SceneInventory(controls=[c.model_copy(update={"id": f"new-{c.id}", "pos_mm": (c.pos_mm[0] + 40, c.pos_mm[1], c.pos_mm[2])}) for c in scene.controls])
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1"))), say(call("run_plan")), say(call("recover", action="re_explore")),
              say(call("propose_plan", steps=[{"id": "x2", "skill": "press", "target": "new-c2"}, {"id": "x3", "skill": "press", "target": "new-c3"}])),
              say(call("run_plan")), say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script, Renamed())
    assert report.coverage.detected == 3 and sorted(report.coverage.passed) == ["c1", "c2", "c3"], report.coverage


def test_moving_the_device_on_purpose_is_a_plan_step_a_person_signs_and_needs_a_new_look(tmp_path):
    class Movable(Robot):
        def perceive(self):
            scene = super().perceive()
            return scene.model_copy(update={"controls": [*scene.controls, Control(id="device", kind="object", pos_mm=(250.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0), source="mock")]})
    class Tools(FakeS1):
        moved = False
        def scene_get(self):
            report = super().scene_get()
            if self.moved and self.routine_count_after == self.routines:
                return report.model_copy(update={"scene": report.scene.model_copy(update={"stale": True})})
            return report
        def routine_start(self, routine, plan=None, policy=None):
            if routine == "explore":
                self.moved = False
            if plan and any(s.skill == "reposition" for s in plan.steps):
                self.moved = True
            handle = super().routine_start(routine, plan, policy)
            self.routine_count_after = self.routines
            return handle
    asked = []
    move = [{"id": "m", "skill": "reposition", "target": "device", "params": {"dx_mm": 20}}]
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1"))), say(call("run_plan")),
              say(call("propose_plan", steps=move)), say(call("run_plan")),
              say(call("propose_plan", steps=[{"id": "s2", "skill": "press", "target": "c2"}])), say(call("run_plan")), say(call("look_at_device")),
              say(call("propose_plan", steps=[{"id": "s2", "skill": "press", "target": "c2"}, {"id": "s3", "skill": "press", "target": "c3"}])), say(call("run_plan")),
              say(call("finish_run", summary="x"))]
    report, events, client, robot = go(tmp_path, script, Movable(), approve=lambda k, r: asked.append(r) or "Ada", system1=Tools(Movable()))
    assert asked[:2] == ["plan-1", "plan-2"]
    assert any("out of date" in e for e in errors_told(client))
    assert report.coverage.detected == 3 and sorted(report.coverage.passed) == ["c1", "c2", "c3"], report.coverage
    assert not [f for f in report.findings if f.target == "device"]


# --- steering ------------------------------------------------------------------------------------

def test_an_operators_message_reaches_the_next_turn(tmp_path):
    steering = Steering()
    def model(messages, tools):
        if len(messages) == 1:
            steering.send(SteerCommand(kind="message", text="Test c3 first.", by="Ada"))
            return say(call("look_at_device"))
        said = [m.text for m in messages if m.role == "user"]
        if any("Test c3 first." in s for s in said) and not any(m.role == "assistant" and m.reply.calls and m.reply.calls[0].name == "propose_plan" for m in messages):
            return say(call("propose_plan", steps=steps("c3", "c1", "c2")))
        names = [c.name for m in messages if m.role == "assistant" for c in m.reply.calls]
        return say(call("run_plan")) if "run_plan" not in names else say(call("finish_run", summary="x"))
    report, events, client, robot = go(tmp_path, model, steering=steering)
    assert robot.executed[0].target == "c3"
    assert any(e.type == "steer_applied" for e in events) and any(e.type == "message" and e.payload.get("by") == "Ada" for e in events)


def test_a_skip_is_enforced_whatever_the_model_then_asks(tmp_path):
    steering = Steering()
    steering.send(SteerCommand(kind="skip", target="c2", text="It's fragile."))
    script = [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))),
              say(call("propose_plan", steps=[{"id": "a", "skill": "press", "target": "c1"}, {"id": "b", "skill": "press", "target": "c3"}])), say(call("run_plan")),
              say(call("finish_run", summary="x", controls=[{"id": "c2", "why": "the operator asked"}]))]
    report, events, client, robot = go(tmp_path, script, steering=steering)
    assert "c2" not in [s.target for s in robot.executed] and any("operator asked" in e for e in errors_told(client))


def test_stop_closes_the_routine_and_ends_the_run(tmp_path):
    steering = Steering()
    robot = Robot({"c1": ["failed"]})
    def model(messages, tools):
        names = [c.name for m in messages if m.role == "assistant" for c in m.reply.calls]
        if not names:
            return say(call("look_at_device"))
        if "propose_plan" not in names:
            return say(call("propose_plan", steps=steps("c1", "c2", "c3")))
        if "run_plan" not in names:
            return say(call("run_plan"))
        if "finish_run" not in names and not steering.commands and not any(prompts.STOPPED in (m.text or "") for m in messages):
            steering.send(SteerCommand(kind="stop"))
            return say(call("get_status"))
        return say(call("finish_run", summary="stopped"))
    report, events, client, robot = go(tmp_path, model, robot, steering=steering)
    assert events[-1].payload["status"] == "stopped" and len(robot.executed) == 1


def test_pause_holds_the_model_until_resume(tmp_path):
    steering = Steering()
    steering.send(SteerCommand(kind="pause"))
    waited = []
    def wait():
        waited.append(1)
        if len(waited) == 3:
            steering.send(SteerCommand(kind="resume"))
    report, _, client, _ = go(tmp_path, happy(), steering=steering, wait=wait)
    assert len(waited) == 3 and report.reward.value == 1.0


def test_a_question_waits_for_a_person_and_nobody_answering_is_an_answer(tmp_path):
    script = [say(call("ask_operator", question="Which first?")), *happy()]
    _, _, client, _ = go(tmp_path, script, ask=lambda q: "c1")
    assert any(r.content.get("answer") == "c1" for m in client.requests[1]["messages"] for r in m.results)
    _, _, client, _ = go(tmp_path, [say(call("ask_operator", question="Which first?")), *happy()])
    assert any(r.content.get("answer") is None and "note" in r.content for m in client.requests[1]["messages"] for r in m.results)


def test_reasoning_streams_as_its_written(tmp_path):
    deltas = []
    go(tmp_path, happy(), on_delta=deltas.append)
    assert {"type": "model_delta", "turn": "turn-2", "kind": "thought", "text": "Let me look."} in deltas


# --- context, manual, images ---------------------------------------------------------------------

def test_older_results_shrink_and_calls_stay_paired():
    calls = [ToolRequest(f"c{i}", "get_scene", {}) for i in range(10)]
    messages = [Message("user", "brief")]
    for c in calls:
        raw = {"role": "model", "parts": [{"text": "hm", "thought": True}, {"functionCall": {"name": c.name}, "thoughtSignature": "SIG"}]}
        messages.append(Message("assistant", reply=ModelReply(model="m", calls=[c], raw_message=raw)))
        messages.append(Message("user", results=[ToolResult(c, {"controls": ["big"] * 100, "stop": "done"})]))
    out = trim(messages, 6)
    assert len(out) == len(messages) and out[0].text == "brief"
    old_reply, old_result = out[1], out[2]
    assert old_result.results[0].content == {"earlier": '{"stop": "done"}'}
    assert old_reply.reply.raw_message["parts"] == [{"functionCall": {"name": "get_scene"}, "thoughtSignature": "SIG"}]
    assert out[-1].results[0].content["controls"]


def test_manual_pages_and_search(tmp_path):
    path = tmp_path / "m.md"
    path.write_text("\n".join(f"line {i} about things" for i in range(100)) + "\nTo open, lift the flap.")
    manual = Manual(path)
    assert manual.read()["pages"] == 2 and "line 0" in manual.read(1)["text"]
    assert manual.read(query="lift flap")["hits"][0]["page"] == 2
    with pytest.raises(ValueError):
        manual.read(9)


def test_the_model_reads_a_manual_only_when_there_is_one(tmp_path):
    path = tmp_path / "m.txt"
    path.write_text("Press it.")
    _, _, client, _ = go(tmp_path, [say(call("read_manual", page=1)), *happy()], manual=Manual(path))
    assert "1 pages" in client.requests[0]["messages"][0].text and any(r.content.get("text") == "Press it." for m in client.requests[1]["messages"] for r in m.results)
    _, _, client, _ = go(tmp_path, [say(call("read_manual")), *happy()])
    assert any(r.content.get("available") is False for m in client.requests[1]["messages"] for r in m.results)


def test_a_frame_goes_to_the_model_as_an_image(tmp_path):
    from rav_contracts import Frame
    class WithFrames(FakeS1):
        def evidence_frame(self, ref):
            return Frame(ref=ref, data_b64="QUJD", width=2, height=2, caption="a view")
    _, _, client, _ = go(tmp_path, [say(call("get_evidence", ref="frame:1")), *happy()], system1=WithFrames(Robot()))
    assert client.requests[1]["messages"][-1].images[0].data_b64 == "QUJD"


# --- staying general ---------------------------------------------------------------------------

def _vocabulary() -> set[str]:
    root = HARNESS.parents[2]
    words = {"stuck_button", "button_1", "button_2", "button_3", "slider_1", "dial_1", "toggle_1", "door_1", "centrifuge", "microwave", "rotor", "tube rack"}
    for folder in (root / "subjects").iterdir():
        if folder.is_dir():
            words.add(folder.name)
    appliances = root.parent / "appliances"
    if appliances.is_dir():
        words |= {p.name for p in appliances.iterdir() if p.is_dir()}
    faults = root.parent / "system-1/sim/faults.py"
    words |= set(re.findall(r'^\s*"([a-z_]+)":\s*\{', faults.read_text(), re.M))
    return {w.lower() for w in words if len(w) > 3}


@pytest.mark.parametrize("name", ["prompts.py", "agent.py", "toolbelt.py", "model.py", "manual.py", "verdicts.py", "service.py", "eval.py", "launch.py"])
def test_no_device_knowledge_in_the_prompts_or_the_harness(name):
    text = (HARNESS / name).read_text().lower()
    found = sorted(w for w in _vocabulary() if re.search(rf"\b{re.escape(w)}\b", text))
    assert not found, f"{name} knows about {found}"


def test_the_prompt_doesnt_state_an_error_rate():
    assert not re.search(r"\d+\s*(%|percent)", prompts.SYSTEM)


def test_nothing_planted_reaches_a_saved_request(tmp_path):
    report, events, client, _ = go(tmp_path, happy())
    for path in (tmp_path / "r/model").glob("*.json"):
        assert "SECRET-ANSWER" not in path.read_text()
    assert "SECRET-ANSWER" not in json.dumps([m.text for r in client.requests for m in r["messages"]])


def test_the_answer_key_cant_reach_the_model_through_its_tools(tmp_path):
    (tmp_path / "r").mkdir()
    (tmp_path / "r/answer_key.json").write_text('{"faults": [{"part": "KEY-PART"}]}')
    _, _, client, _ = go(tmp_path, [*happy()[:-1], say(call("get_evidence", ref="../answer_key.json")), say(call("read_manual", query="answer_key")), say(call("finish_run", summary="x"))])
    assert "KEY-PART" not in json.dumps([r.content for req in client.requests for m in req["messages"] for r in m.results], default=str)


def test_same_device_with_opaque_ids_gives_the_same_findings(tmp_path):
    def model(ids):
        def script(messages, tools):
            names = [c.name for m in messages if m.role == "assistant" for c in m.reply.calls]
            if not names:
                return say(call("look_at_device"))
            if "propose_plan" not in names:
                return say(call("propose_plan", steps=steps(*ids)))
            if "run_plan" not in names:
                return say(call("run_plan"))
            last = messages[-1].results[-1].content
            if last.get("next") == "answer_stop":
                return say(call("answer_stop", kind="continue"))
            return say(call("finish_run", summary="x"))
        return script
    plain = ["c1", "c2", "c3", "c4"]
    opaque = ["q9x", "k2p", "zz1", "m0m"]
    a, _, _, _ = go(tmp_path / "a", model(plain), Robot({"c2": ["failed"]}, controls=plain))
    b, _, _, _ = go(tmp_path / "b", model(list(reversed(opaque))), Robot({"k2p": ["failed"]}, controls=opaque))
    rename = dict(zip(plain, opaque))
    assert [rename[f.target] for f in a.findings] == [f.target for f in b.findings]
    assert sorted(rename[c] for c in a.coverage.passed) == sorted(b.coverage.passed) and a.reward == b.reward


class MovedHold(FakeS1):
    """The robot's own rule: after a move it holds and takes nothing but abort."""

    def _run_plan(self, plan, policy):
        self.answers = getattr(self, "answers", [])
        if getattr(self, "held", False):
            yield from FakeS1._run_plan(self, plan, policy)
            return
        self.held = True
        escalation = Escalation(code="pose_unstable", step=plan.steps[0].id, measured={"pattern": "device_moved"})
        yield Checkpoint(routine_id=f"r{self.routines}", stop="escalation", status="paused", escalation=escalation, steps_done=0, steps_total=len(plan.steps))
        yield Checkpoint(routine_id=f"r{self.routines}", stop="done", status="aborted", reason="aborted", steps_done=0, steps_total=len(plan.steps))

    def routine_resume(self, routine_id, decision):
        self.answers = getattr(self, "answers", []) + [decision.kind]
        if getattr(self, "held", False) and decision.kind != "abort" and not getattr(self, "aborted", False):
            raise ToolFailed("routine_resume: the device moved, so the remaining steps would run on old poses: abort this routine, then run explore")
        self.aborted = True
        return super().routine_resume(routine_id, decision)


def test_a_hold_after_a_move_is_recovered_from_and_a_wrong_answer_only_costs_a_turn(tmp_path):
    robot = Robot()
    system1 = MovedHold(robot)
    report, events, client, _ = go(tmp_path, [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
                                              say(call("answer_stop", kind="continue")), say(call("answer_stop", kind="abort")), say(call("recover", action="re_explore")),
                                              say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")), say(call("finish_run", summary="Done."))],
                                   robot=robot, system1=system1)
    assert system1.answers[:2] == ["continue", "abort"] and any("abort this routine" in e for e in errors_told(client))
    assert report.coverage.passed == ["c1", "c2", "c3"] and not report.findings and system1.started.count("explore") == 2


def test_the_rule_plan_reports_after_a_move_rather_than_crashing(tmp_path):
    system1 = MovedHold(Robot())
    report = run_test(system1, REQUEST, RunLog("r", tmp_path), approve=sim_auto_approve)
    assert system1.answers == ["abort"] and not report.findings and not report.coverage.passed
    assert any("device moved" in str(e.payload) for e in read_events(tmp_path / "r" / "events.jsonl") if e.type == "message")


def test_the_fault_a_rule_cant_separate_only_counts_if_called_passed(tmp_path):
    from rav_harness.eval import score
    report, events, _, _ = go(tmp_path, happy())
    key = {"controls": [{"id": "c1", "pos_mm": None}], "faults": [{"fault": "stuck_dial", "part": "c1"}]}
    s = score(report, events, key)
    assert s["faults_called_passed"] == ["c1"] and not s["faults_missed"] and not s["faults_planted"]
    s = score(report.model_copy(update={"coverage": report.coverage.model_copy(update={"passed": [], "inconclusive": ["c1"]})}), events, key)
    assert not s["faults_called_passed"] and not s["false_findings"]


def test_the_device_itself_is_never_listed_as_a_control(tmp_path):
    from rav_harness.toolbelt import without_device
    scene = SceneInventory(controls=[Control(id="c1", kind="button", pos_mm=[0, 0, 0], normal=[0, 0, 1]), Control(id="device", kind="object", pos_mm=[0, 0, 0], normal=[0, 0, 1])])
    assert [c.id for c in without_device(scene).controls] == ["c1"]
    report, events, _, _ = go(tmp_path, happy())
    assert all(c["id"] != "device" for e in events if e.type == "scene_ready" for c in e.payload["controls"])


def test_a_made_up_limit_is_refused_before_anything_moves(tmp_path):
    made_up = steps("c1", "c2", "c3")
    made_up[0]["check"] = [{"metric": "travel_mm", "op": ">=", "value": 20}]
    sourced = steps("c1", "c2", "c3")
    sourced[0]["check"] = [{"metric": "travel_mm", "op": ">=", "value": 20, "source": "spec sheet: 20 mm travel"}]
    report, events, client, _ = go(tmp_path, [say(call("look_at_device")), say(call("propose_plan", steps=made_up)), say(call("propose_plan", steps=sourced)),
                                              say(call("run_plan")), say(call("finish_run", summary="x"))])
    told = errors_told(client)
    assert len(set(told)) == 1 and "has no source" in told[0] and report.coverage.passed == ["c1", "c2", "c3"]


def test_a_skill_called_as_a_tool_is_pointed_at_plans(tmp_path):
    report, events, client, _ = go(tmp_path, [say(call("get_status")), say(call("press", target="c1")), *happy()[1:]])
    assert "put it in a step of a plan" in errors_told(client)[0]


def test_finishing_while_held_at_the_last_step_closes_the_routine(tmp_path):
    report, events, client, _ = go(tmp_path, [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
                                              say(call("finish_run", summary="c3 failed once."))], robot=Robot({"c3": ["failed"]}))
    assert not errors_told(client) and report.coverage.failed == ["c3"] and events[-1].payload["status"] == "completed"


HYPOTHESIS = {"controls": [{"id": "c1", "primitive": "press"}, {"id": "c2", "primitive": "press"}, {"id": "c3", "primitive": "turn", "range": {"low": 0, "high": 10}}],
              "state": [{"name": "level", "default": 0}], "relations": [{"kind": "drives", "source": "c3", "target": "level"}]}


def test_a_hypothesis_gives_a_checklist_kept_out_of_the_conversation_and_finishing_points_at_what_is_untested_once(tmp_path):
    tagged = steps("c1", "c2", "c3")
    tagged[0]["tests"] = ["actuates:c1"]
    report, events, client, _ = go(tmp_path, [say(call("look_at_device")), say(call("record_hypothesis", hypothesis="not json")),
                                              say(call("record_hypothesis", hypothesis=HYPOTHESIS)), say(call("propose_plan", steps=tagged)), say(call("run_plan")),
                                              say(call("get_status")), say(call("finish_run", summary="x")), say(call("finish_run", summary="Left the range ends: no time."))])
    told = list(dict.fromkeys(errors_told(client)))
    assert "can't be read" in told[0] and "checklist properties have no evidence yet" in told[1] and "respects_range:c3" in told[1]
    results = {r.call.name: r.content for m in client.requests[-1]["messages"] for r in m.results if "error" not in r.content}
    recorded = results["record_hypothesis"]
    assert {"actuates:c1", "respects_range:c3", "default_on_power:level", "mapping_matches:c3:level"} <= set(recorded["untested"])
    assert "checklist" not in recorded  # keys only: the statements stay in the harness
    assert "actuates:c1" not in results["run_plan"]["checklist_untested"] and "respects_range:c3" in results["run_plan"]["checklist_untested"]
    assert any(c["key"] == "respects_range:c3" and c["test"] for c in results["get_status"]["checklist_untested"])
    note = next(e.payload for e in events if e.type == "message" and "checklist" in e.payload and "tested" in e.payload["checklist"])
    assert note["checklist"]["tested"] == {"actuates:c1": "passed"} and events[-1].payload["status"] == "completed"


def test_a_loose_hypothesis_is_repaired_and_says_what_was_read_differently(tmp_path):
    from rav_harness.theory import hypothesis_schema, parse_hypothesis
    loose = {"controls": [{"id": "c1", "primitive": "push"}, {"id": "c3", "primitive": "turn", "range": "0-10 C", "unit": "C"}],
             "state": [{"name": "level", "values": "low, high"}],
             "relations": [{"kind": "drives", "source": "c3", "target": "level", "mapping": {"0": "low"}}, {"kind": "enables", "source": "ghost", "target": "c1"}],
             "procedures": [{"name": "p", "steps": [{"primitive": "press", "target": "c1", "pre": ["level = low"], "effects": [{"level": "high"}, "c3 shows 5"]}]}]}
    h, notes = parse_hypothesis(loose)
    assert h.controls[0].primitive == "press" and h.controls[1].range.high == 10 and h.state[0].values == ["low", "high"]
    assert [(c.subject, c.op, c.value) for c in h.procedures[0].steps[0].effects] == [("level", "==", "high"), ("c3", "shows", "5")]
    assert len(h.relations) == 1 and any("ghost" in n for n in notes) and any("ignored controls.1.unit" in n for n in notes)
    schema = json.dumps(hypothesis_schema())
    assert "$ref" not in schema and '"procedures"' in schema and '"subject"' in schema
    report, events, client, _ = go(tmp_path, [say(call("look_at_device")), say(call("record_hypothesis", **loose)),
                                              say(call("finish_run", summary="x", controls=[{"id": c, "why": "not tested here"} for c in ("c1", "c2", "c3")]))] * 1
                                   + [say(call("finish_run", summary="x", controls=[{"id": c, "why": "not tested here"} for c in ("c1", "c2", "c3")]))])
    recorded = next(r.content for m in client.requests[-1]["messages"] for r in m.results if r.call.name == "record_hypothesis")
    assert recorded["recorded"] > 0 and any("as press" in n for n in recorded["read_differently"])


def test_a_new_plan_closes_a_routine_held_at_a_stop(tmp_path):
    report, events, client, robot = go(tmp_path, [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2", "c3"))), say(call("run_plan")),
                                                  say(call("propose_plan", steps=steps("c1", "c2", "c3", prefix="r"))), say(call("run_plan")),
                                                  say(call("finish_run", summary="x"))], robot=Robot({"c1": ["failed"]}))
    assert not errors_told(client) and report.coverage.intermittent == ["c1"] and report.coverage.passed == ["c2", "c3"]
    assert any("has been closed" in str(r.content) for m in client.requests[-1]["messages"] for r in m.results)


# --- check-back --------------------------------------------------------------------------------

def _step(sid, skill, target, *checks):
    return Step(id=sid, skill=skill, target=target, check=[{"metric": m, "op": "changed"} for m in checks])


def test_check_back_wants_outputs_checked_on_every_change_and_a_read_back_after_a_group():
    from rav_harness.checkback import missing_checkback
    bare = missing_checkback([_step("s1", "press", "c1")], {})
    assert len(bare) == 1 and "checks none of the device's outputs" in bare[0]
    own = missing_checkback([_step("s1", "press", "c1", "reading:R_c1")], {"c1": {"R_c1"}})
    assert "other than R_c1, which c1 drives" in own[0]  # the part's own channel proves it moved, not what the device did
    assert missing_checkback([_step("s1", "press", "c1", "lcd")], {}) == []  # one change, checked where it shows: a retest needs no more
    two = [_step("s1", "press", "c1", "lcd"), _step("s2", "press", "c2", "reading:R_c1")]
    assert "after s2: the plan ends on changes it never checks back" in missing_checkback(two, {})[0]
    assert missing_checkback([*two, _step("s3", "observe", "d1", "lcd")], {}) == []
    many = [_step(f"s{n}", "press", f"c{n}", "lcd") for n in range(1, 8)] + [_step("s9", "observe", "d1", "lcd")]
    assert any("s1 to s6: 6 changes in a row" in p for p in missing_checkback(many, {}))
    blind = [*two, _step("s3", "press", "c1", "lcd")]  # nothing to observe: repeating an earlier step reads it back
    assert missing_checkback(blind, {}, can_observe=False) == [] and missing_checkback(blind, {}, can_observe=True)
    assert missing_checkback([_step("s1", "observe", "d1"), _step("s2", "none", "c1")], {}) == []


def test_closing_state_differences_name_what_changed():
    from rav_harness.checkback import differences, state_of
    first = state_of([Control(id="t", kind="toggle", pos_mm=(0, 0, 0), normal=(0, 0, 1), on=False)], {"lcd": "OFF", "mode": 0})
    now = state_of([Control(id="t", kind="toggle", pos_mm=(0, 0, 0), normal=(0, 0, 1), on=True)], {"lcd": "OFF", "mode": 2})
    assert differences(first, now) == ["mode: 0 at the start, 2 now", "t on: False at the start, True now"]


def test_a_plan_without_check_back_is_refused_and_the_run_closes_with_a_look_compared_to_the_first(tmp_path):
    checked = [{"id": "s1", "skill": "press", "target": "c1", "check": [{"metric": "lcd", "op": "changed"}]},
               {"id": "s2", "skill": "press", "target": "c2", "check": [{"metric": "reading:R_c1", "op": "==", "value": 1, "source": "s1 left it at 1"}]},
               {"id": "s3", "skill": "press", "target": "c1", "check": [{"metric": "reading:R_c2", "op": "==", "value": 1, "source": "s2 left it at 1"}]}]
    report, events, client, robot = go(tmp_path, [say(call("look_at_device")), say(call("propose_plan", steps=steps("c1", "c2"))),
                                                  say(call("propose_plan", steps=checked)), say(call("run_plan")),
                                                  say(call("finish_run", summary="x")), say(call("look_at_device")), say(call("finish_run", summary="x")),
                                                  say(call("finish_run", summary="The readings stay where the presses left them."))],
                                       robot=Robot(controls=("c1", "c2")), config=AgentConfig(check_back=True))
    told = list(dict.fromkeys(errors_told(client)))
    assert "s1: press c1 changes something but checks none of the device's outputs" in told[0] and "never checks back" in told[0]
    assert "Look at the device once more before finishing" in told[1]
    assert "isn't as the first look found it" in told[2] and "R_c1: 0 at the start, 1 now" in told[2]
    assert len(told) == 3 and robot.explores == 2 and events[-1].payload["status"] == "completed"
    assert "Closing look differs from the first: R_c1: 0 at the start, 1 now" in report.summary
    stats = next(e.payload["checkback"] for e in events if e.type == "message" and "checkback" in e.payload)
    assert stats["plans_refused"] == 1 and stats["closing_looks"] == 1 and stats["closing_differences"] == 2


def test_check_back_is_in_the_prompt_and_on_by_default():
    assert AgentConfig().check_back and AgentConfig().max_tokens == 600_000
    assert "Check back" in prompts.SYSTEM and "closing look" in prompts.SYSTEM
