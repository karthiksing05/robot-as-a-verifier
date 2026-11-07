"""When System 1 defers, and when it doesn't."""
import time

import pytest
from rav_interface import AUTONOMOUS, BALANCED, TETHERED, Check, Decision, EscalationPolicy, Plan, Step, StepTrace
from rav_interface import DEVICE_CONTROL, Control, StepVerdict
from rav_server.actions import reposition_action
from rav_server.engine import MAX_FORCE_N, RoutineEngine, RoutineError, clamp, evaluate_checks
from rav_server.mock_robot import MockRobot
from rav_server.robot import PipelineFailure

QUIET = EscalationPolicy(name="quiet", retries_per_step=0, checkpoint_every=None)
PLAN = Plan(plan_id="p", steps=[Step(id=f"s{n}", skill="press", target=f"button_{n}") for n in (1, 2, 3)])


def explored(eng):
    """A plan needs a scene: explore first, as every caller must, and wait for the worker to let go."""
    handle = eng.start("explore", policy=QUIET)
    assert eng.wait(handle.routine_id, 5).stop == "done"
    while eng.active is not None:
        time.sleep(0.001)
    return eng


def engine(**robot):
    robot_ = MockRobot(**robot)
    return explored(RoutineEngine(lambda: robot_, "mock")), robot_


def run(eng, plan=PLAN, policy=QUIET, answer=None):
    """Runs a plan to the end, answering each stop, and returns every stop in order."""
    handle = eng.start("run_plan", plan, policy)
    stops = []
    while True:
        cp = eng.wait(handle.routine_id, 5)
        assert cp.stop, "timed out"
        stops.append(cp)
        if cp.status != "paused":
            return stops
        eng.resume(handle.routine_id, (answer or (lambda _: Decision()))(cp))


def test_a_clean_run_crosses_once_when_the_policy_is_quiet():
    eng, _ = engine()
    stops = run(eng)
    assert [s.stop for s in stops] == ["done"] and len(stops[0].verdicts) == 3


def test_tethered_checks_back_after_every_step():
    eng, _ = engine()
    assert [s.stop for s in run(eng, policy=TETHERED)] == ["checkpoint", "checkpoint", "done"]


@pytest.mark.parametrize("policy", [QUIET, TETHERED, BALANCED, AUTONOMOUS])
def test_a_clean_fail_always_wakes_system_2(policy):
    eng, _ = engine(script={"button_2": ["failed"]})
    stops = run(eng, policy=policy)
    assert any(s.escalation and s.escalation.code == "step_failed" and s.escalation.target == "button_2" for s in stops)


def test_an_escalation_carries_the_mechanism_with_its_numbers():
    eng, _ = engine(script={"button_2": ["failed"]})
    e = run(eng)[0].escalation
    assert e.measured["peak_force_n"] == 4.8 and e.measured["travel_mm"] == 0.3 and e.tried == ["press x1"]


def test_a_stop_stays_small_and_holds_no_raw_samples():
    eng, _ = engine(script={"button_2": ["failed"]})
    stop = run(eng)[0]
    assert len(stop.model_dump_json()) < 2048
    assert "force_trace" not in stop.model_dump_json()
    assert eng.evidence(stop.verdicts[-1].trace_ref).force_trace  # still there on request


def test_retries_stay_local_within_the_budget():
    eng, robot = engine(script={"button_2": ["inconclusive", "passed"]})
    stops = run(eng, policy=BALANCED)
    assert [s.stop for s in stops] == ["done"] and stops[0].retries_resolved == 1
    assert [s.target for s in robot.executed].count("button_2") == 2


def test_retries_exhausted_escalates():
    eng, _ = engine(script={"button_2": ["inconclusive"] * 5})
    stops = run(eng, policy=BALANCED)
    assert stops[0].escalation.code == "retries_exhausted" and stops[0].verdicts[-1].attempts == 3


def test_a_wrong_response_escalates_as_unexpected():
    eng, _ = engine(script={"button_2": ["wrong"]})
    assert run(eng)[0].escalation.code == "unexpected_response"


def test_safety_stops_first_and_ends_the_routine():
    eng, robot = engine(script={"button_2": ["unsafe"]})
    stops = run(eng)
    assert (stops[-1].stop, stops[-1].status) == ("safety_abort", "aborted")
    assert "button_3" not in [s.target for s in robot.executed]


def test_a_robot_fault_is_reported_as_a_safety_abort():
    class Broken(MockRobot):
        def execute(self, step):
            raise OSError("servo bus lost")
    eng = explored(RoutineEngine(lambda: Broken(), "mock"))
    stops = run(eng)
    assert stops[-1].stop == "safety_abort" and "servo bus lost" in stops[-1].reason


def test_it_holds_until_system_2_answers():
    eng, robot = engine(script={"button_1": ["failed"]})
    handle = eng.start("run_plan", PLAN, QUIET)
    assert eng.wait(handle.routine_id, 5).stop == "escalation"
    again = eng.wait(handle.routine_id, 0.2)
    assert again.stop is None and again.status == "paused" and len(robot.executed) == 1
    eng.stop(handle.routine_id)
    assert eng.wait(handle.routine_id, 5).status == "stopped"


def test_amending_replaces_the_remaining_steps():
    eng, robot = engine(script={"button_1": ["failed"]})
    new = Step(id="x", skill="press", target="button_3", params={"force_limit": MAX_FORCE_N})
    run(eng, answer=lambda _: Decision(kind="amend", steps=[new]))
    assert [s.id for s in robot.executed] == ["s1", "x"]


def test_a_force_over_the_limit_gets_a_clear_answer_and_the_clamp_cant_refuse():
    eng, robot = engine()
    with pytest.raises(RoutineError, match="force_limit=20 is outside 0.1 to 14 N"):
        eng.start("run_plan", Plan(plan_id="p", steps=[Step(id="s", skill="press", target="button_1", params={"force_limit": 20})]))
    assert robot.executed == []
    assert clamp(Step(id="s", skill="press", target="b", params={"force_limit": 99})).params["force_limit"] == MAX_FORCE_N == eng.status().max_force_n


def test_a_bad_plan_names_every_problem_before_anything_moves():
    eng, robot = engine()
    bad = Plan(plan_id="p", steps=[Step(id="a", skill="turn", target="button_1", params={"angle": 30}), Step(id="b", skill="press", target="nope"),
                                   Step(id="c", skill="press_hold", target="button_1"), Step(id="d", skill="press", target="button_1", params={"forse": 3})])
    with pytest.raises(RoutineError) as e:
        eng.start("run_plan", bad)
    for word in ("a (turn", "takes: press", "no control called nope", "press_hold isn't offered", "unknown param forse"):
        assert word in str(e.value)
    assert robot.executed == [] and eng.status().state == "idle"


def test_a_bad_amendment_fails_and_the_routine_keeps_holding():
    eng, robot = engine(script={"button_1": ["failed"]})
    handle = eng.start("run_plan", PLAN, QUIET)
    assert eng.wait(handle.routine_id, 5).stop == "escalation"
    with pytest.raises(RoutineError, match="no control called nope"):
        eng.resume(handle.routine_id, Decision(kind="amend", steps=[Step(id="x", skill="press", target="nope")]))
    assert eng.status().state == "paused" and len(robot.executed) == 1
    eng.resume(handle.routine_id, Decision())
    assert eng.wait(handle.routine_id, 5).stop == "done"


def test_a_plan_needs_a_scene():
    eng = RoutineEngine(MockRobot, "mock")
    with pytest.raises(RoutineError, match="run explore first"):
        eng.start("run_plan", PLAN)


def test_the_allowed_actions_are_published():
    actions = {a.skill: a for a in RoutineEngine(MockRobot, "mock").status().actions}
    assert set(actions) == {"press", "flip", "slide", "turn", "push_latch", "observe"}
    assert [p.name for p in actions["turn"].params if p.required] == ["angle"] and "knob" in actions["turn"].kinds
    assert next(p for p in actions["press"].params if p.name == "force_limit").default == 6.0


def test_a_perception_failure_is_a_pipeline_error_and_a_hardware_one_stays_a_safety_abort():
    class NoPanel(MockRobot):
        def perceive(self):
            raise PipelineFailure("RuntimeError: a plain panel?")
    eng = RoutineEngine(NoPanel, "mock")
    stop = eng.wait(eng.start("explore").routine_id, 5)
    assert (stop.stop, stop.status) == ("pipeline_error", "aborted") and "plain panel" in stop.reason

    class Bus(MockRobot):
        def perceive(self):
            raise OSError("servo bus lost")
    eng = RoutineEngine(Bus, "mock")
    assert eng.wait(eng.start("explore").routine_id, 5).stop == "safety_abort"


def test_verdicts_since_the_last_stop_survive_a_fault():
    class Dies(MockRobot):
        def execute(self, step):
            if step.target == "button_2":
                raise OSError("servo bus lost")
            return super().execute(step)
    eng = explored(RoutineEngine(Dies, "mock"))
    stop = run(eng)[-1]
    assert stop.stop == "safety_abort" and [v.verdict.target for v in stop.verdicts] == ["button_1"]


def test_every_attempt_keeps_its_own_trace_even_across_a_reused_id():
    eng, _ = engine(script={"button_1": ["inconclusive", "failed", "passed"]})
    one = Plan(plan_id="p", steps=[Step(id="s1", skill="press", target="button_1")])
    stops = run(eng, one, BALANCED, answer=lambda _: Decision(kind="amend", steps=one.steps))
    first, again = stops[0].verdicts[0], stops[1].verdicts[0]
    assert first.attempt_refs == [f"trace:{stops[0].routine_id}:s1:1"] and first.trace_ref.endswith(":2") and again.trace_ref.endswith(":3")
    assert eng.evidence(first.attempt_refs[0]).attempt == 1 and eng.evidence(again.trace_ref).attempt == 3


def test_a_failed_check_wakes_system_2_and_never_changes_the_verdict():
    eng, _ = engine()
    step = Step(id="s", skill="press", target="button_1", check=[Check(metric="peak_force_n", op="<=", value=1.0), Check(metric="travel_mm", op=">=", value=0.1)])
    stops = run(eng, Plan(plan_id="p", steps=[step]))
    summary = stops[0].verdicts[0]
    assert summary.verdict.status == "passed" and [c.passed for c in summary.checks] == [False, True] and summary.checks[0].actual == 4.8
    assert stops[0].escalation.code == "unexpected_response" and stops[0].escalation.measured["failed_checks"][0]["metric"] == "peak_force_n"


def test_a_check_on_a_reading_compares_what_changed():
    trace = StepTrace(step="s", readout_change={"FAN": [0.5, 0.9]}, measures={"readings": {"FAN": 0.9, "MODE": 3}})
    verdict = StepVerdict(step="s", target="t", status="passed", reason="")
    checks = [Check(metric="reading:FAN", op="changed"), Check(metric="reading:FAN", op=">=", value=0.8), Check(metric="reading:MODE", op="==", value=3),
              Check(metric="reading:MODE", op="changed"), Check(metric="reading:NOPE", op="==", value=1)]
    results = evaluate_checks(Step(id="s", skill="press", target="t", check=checks), trace, verdict)
    assert [r.passed for r in results] == [True, True, True, False, False]


def test_an_unmeasured_check_says_so():
    trace, verdict = StepTrace(step="s"), StepVerdict(step="s", target="t", status="skipped", reason="refused")
    assert evaluate_checks(Step(id="s", skill="press", target="t", check=[Check(metric="travel_mm", op=">=", value=1), Check(metric="reading:FAN", op="changed")]), trace, verdict)[0].passed is None


def test_a_realistic_stop_stays_under_2_kb():
    class Full(MockRobot):
        def execute(self, step):
            trace, verdict = super().execute(step)
            trace.measures = {"contact_offset_mm": 0.84, "refined": True, "refine_shift_mm": 1.27, "regrip_mm": 5.0, "landing_n": 1.42, "lcd": "PWR ON  FAN 42%  MODE 3",
                              "collisions": [], "refine_why": "x" * 400, "readings": {f"CH{n}": n for n in range(8)}, "turned_deg": 61.0}
            trace.readout_change = {"MODE": [3, 4, 5], "FAN": [0.42, 0.43]}
            verdict.reason = "pushed through its motion and held 4.8 N at 0.3 mm of travel, but no reading changed"
            return trace, verdict
    eng = explored(RoutineEngine(lambda: Full(script={"button_2": ["failed"]}), "mock"))
    stop = run(eng)[0]
    assert stop.escalation and len(stop.model_dump_json()) < 2048 and stop.verdicts[0].measures["refine_shift_mm"] == 1.27


class Drifting(MockRobot):
    """The corrections each step needs: what a device moving under the map looks like."""

    def __init__(self, shifts):
        super().__init__(targets=tuple(f"button_{n}" for n in range(1, 8)))
        self.shifts = list(shifts)

    def execute(self, step):
        trace, verdict = super().execute(step)
        if self.shifts:
            trace.measures["refine_shift_mm"] = self.shifts.pop(0)
        return trace, verdict


SEVEN = Plan(plan_id="p", steps=[Step(id=f"s{n}", skill="press", target=f"button_{n}") for n in range(1, 8)])


@pytest.mark.parametrize("shifts, pattern", [([1.0, 2.5, 4.5], "growing"), ([1.0, 1.0, 1.2, 9.0, 9.0], "jump")])
def test_corrections_that_keep_growing_escalate_pose_unstable_with_the_numbers(shifts, pattern):
    eng = explored(RoutineEngine(lambda: Drifting(shifts), "mock"))
    stops = run(eng, SEVEN)
    found = [s.escalation for s in stops if s.escalation]
    assert [e.code for e in found] == ["pose_unstable"] and found[0].measured["pattern"] == pattern and found[0].measured["values_mm"][-1] == shifts[-1]


@pytest.mark.parametrize("shifts", [[1.0, 1.5, 1.2, 2.0, 1.1], [1.0, 8.0, 1.0, 1.2], [1.0, 2.0, 3.0]])
def test_ordinary_corrections_and_one_bad_part_dont_wake_system_2(shifts):
    eng = explored(RoutineEngine(lambda: Drifting(shifts), "mock"))
    assert [s.stop for s in run(eng, SEVEN)] == ["done"]


class Movable(MockRobot):
    """A robot with a device it can reposition, as PipelineRobot publishes one."""

    def __init__(self):
        super().__init__()
        self.stale = False

    def extra_actions(self):
        return [reposition_action(30.0, 30.0, 12.0)]

    def current_scene(self):
        scene = super().perceive()
        scene.controls.append(Control(id=DEVICE_CONTROL, kind="object", pos_mm=(250.0, 0.0, 60.0), normal=(0.0, 0.0, 1.0), source="mock"))
        return scene.model_copy(update={"stale": self.stale})

    def perceive(self):
        self.stale = False
        return self.current_scene()

    def execute(self, step):
        trace, verdict = super().execute(step)
        self.stale = self.stale or step.skill == "reposition"
        return trace, verdict


MOVE = Step(id="m", skill="reposition", target=DEVICE_CONTROL, params={"dx_mm": 10.0, "yaw_deg": 5.0})


def test_reposition_is_a_normal_step_with_its_ranges_published():
    eng = explored(RoutineEngine(Movable, "mock"))
    action = next(a for a in eng.status().actions if a.skill == "reposition")
    assert action.kinds == ["object"] and next(p for p in action.params if p.name == "yaw_deg").max == 12.0
    with pytest.raises(RoutineError, match="dx_mm=99 is outside -30 to 30 mm"):
        eng.start("run_plan", Plan(plan_id="p", steps=[Step(id="m", skill="reposition", target=DEVICE_CONTROL, params={"dx_mm": 99})]))


def test_a_stale_scene_holds_the_routine_and_refuses_the_next_plan_until_explore():
    eng = explored(RoutineEngine(Movable, "mock"))
    press = Step(id="p", skill="press", target="button_1")
    handle = eng.start("run_plan", Plan(plan_id="q", steps=[MOVE, press]), QUIET)
    stop = eng.wait(handle.routine_id, 5)
    assert stop.escalation.code == "pose_unstable" and stop.escalation.options == ["abort"] and stop.escalation.measured["steps_not_run"] == ["p"]
    assert stop.verdicts[0].verdict.target == DEVICE_CONTROL and eng.report.scene.stale
    for answer in (Decision(), Decision(kind="amend", steps=[press])):
        with pytest.raises(RoutineError, match="abort this routine, then run explore"):
            eng.resume(handle.routine_id, answer)
    eng.resume(handle.routine_id, Decision(kind="abort"))
    assert eng.wait(handle.routine_id, 5).status == "stopped"
    assert [s.id for s in eng.robot.executed] == ["m"]
    while eng.active is not None:
        time.sleep(0.001)
    with pytest.raises(RoutineError, match="device moved.*run explore first"):
        eng.start("run_plan", Plan(plan_id="q", steps=[press]))
    explored(eng)
    assert not eng.report.scene.stale
    assert eng.wait(eng.start("run_plan", Plan(plan_id="q", steps=[press]), QUIET).routine_id, 5).stop == "done"


def test_a_move_as_the_last_step_just_finishes():
    eng = explored(RoutineEngine(Movable, "mock"))
    stop = eng.wait(eng.start("run_plan", Plan(plan_id="q", steps=[MOVE]), QUIET).routine_id, 5)
    assert stop.stop == "done" and stop.status == "completed" and eng.report.scene.stale


def test_skip_and_abort():
    eng, robot = engine(script={"button_1": ["failed"]})
    run(eng, answer=lambda _: Decision(kind="skip", targets=["button_2"]))
    assert [s.target for s in robot.executed] == ["button_1", "button_3"]
    eng, robot = engine(script={"button_1": ["failed"]})
    assert run(eng, answer=lambda _: Decision(kind="abort"))[-1].status == "stopped" and len(robot.executed) == 1


def test_explore_escalates_only_below_the_floor():
    eng = RoutineEngine(lambda: MockRobot(conf=0.2), "mock")
    handle = eng.start("explore", policy=TETHERED)
    stop = eng.wait(handle.routine_id, 5)
    assert stop.escalation.code == "perception_low_confidence" and eng.report.fallback_plan
    eng.resume(handle.routine_id, Decision())
    assert eng.wait(handle.routine_id, 5).stop == "done"
    eng = RoutineEngine(lambda: MockRobot(conf=0.2), "mock")
    assert eng.wait(eng.start("explore", policy=AUTONOMOUS).routine_id, 5).stop == "done"


def test_nothing_starts_until_asked_and_one_routine_runs_at_a_time():
    eng, robot = engine(script={"button_1": ["failed"]})
    assert robot.executed == []
    while eng.active is not None:
        time.sleep(0.001)
    assert eng.status().state == "idle"
    handle = eng.start("run_plan", PLAN, QUIET)
    with pytest.raises(RoutineError):
        eng.start("explore")
    eng.wait(handle.routine_id, 5)
    assert eng.status().state == "paused"
    eng.stop(handle.routine_id)


def test_requests_it_cant_honour_are_refused():
    eng, _ = engine()
    with pytest.raises(RoutineError):
        eng.start("run_plan")
    with pytest.raises(RoutineError):
        eng.wait("nope")
    with pytest.raises(RoutineError):
        eng.evidence("nope")
