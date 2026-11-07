"""When System 1 defers, and when it doesn't."""
import pytest
from rav_interface import AUTONOMOUS, BALANCED, TETHERED, Decision, EscalationPolicy, Plan, Step
from rav_server.engine import MAX_FORCE_N, RoutineEngine, RoutineError
from rav_server.mock_robot import MockRobot

QUIET = EscalationPolicy(name="quiet", retries_per_step=0, checkpoint_every=None)
PLAN = Plan(plan_id="p", steps=[Step(id=f"s{n}", skill="press", target=f"button_{n}") for n in (1, 2, 3)])


def engine(**robot):
    robot_ = MockRobot(**robot)
    return RoutineEngine(lambda: robot_, "mock"), robot_


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
    eng = RoutineEngine(lambda: Broken(), "mock")
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


def test_amending_replaces_the_remaining_steps_under_the_force_cap():
    eng, robot = engine(script={"button_1": ["failed"]})
    new = Step(id="x", skill="press", target="button_3", params={"force_limit": 99})
    run(eng, answer=lambda _: Decision(kind="amend", steps=[new]))
    assert [s.id for s in robot.executed] == ["s1", "x"] and robot.executed[-1].params["force_limit"] == MAX_FORCE_N


def test_skip_and_abort():
    eng, robot = engine(script={"button_1": ["failed"]})
    run(eng, answer=lambda _: Decision(kind="skip", targets=["button_2"]))
    assert [s.target for s in robot.executed] == ["button_1", "button_3"]
    eng, robot = engine(script={"button_1": ["failed"]})
    assert run(eng, answer=lambda _: Decision(kind="abort"))[-1].status == "stopped" and len(robot.executed) == 1


def test_explore_escalates_only_below_the_floor():
    eng, _ = engine(conf=0.2)
    handle = eng.start("explore", policy=TETHERED)
    stop = eng.wait(handle.routine_id, 5)
    assert stop.escalation.code == "perception_low_confidence" and eng.report.fallback_plan
    eng.resume(handle.routine_id, Decision())
    assert eng.wait(handle.routine_id, 5).stop == "done"
    eng, _ = engine(conf=0.2)
    assert eng.wait(eng.start("explore", policy=AUTONOMOUS).routine_id, 5).stop == "done"


def test_nothing_starts_until_asked_and_one_routine_runs_at_a_time():
    eng, robot = engine(script={"button_1": ["failed"]})
    assert eng.status().state == "idle" and robot.executed == []
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
