"""The integration test: the demo story, end to end, on mock data."""
import pathlib
import shutil

import pytest
from rav_cad import ParamsBackend
from rav_contracts import PAYLOADS, BALANCED, CadBackend, CADPatch, Decision, ParamChange, SteerCommand, Step, System1, TestRequest
from rav_harness.loop import Steering, fix_and_retest, run_test
from rav_harness.amendments import APPROVE, AUTOMATIC, NOTIFY, classify
from rav_harness.mock import FakeSystem1, MockBackend, mock_analyst, mock_system_1
from rav_harness.reward import coverage, reward
from rav_harness.runlog import RunLog, read_events

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUEST = TestRequest(request_id="t", product="box", revision="A")


@pytest.fixture
def params(tmp_path):
    return ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path))


def test_demo_story(tmp_path, params):
    before, after = fix_and_retest(mock_system_1, REQUEST, mock_analyst, params, log_root=str(tmp_path))
    assert before.reward.value == 0.6
    assert {f.target for f in before.findings} == {"button_2", "door"}
    assert after.reward.value == 1.0 and not after.findings
    assert params.read_params()["button_clearance"][1] == 0.40
    assert params.read_params()["handle_style"] == "push_latch"


def test_every_event_is_valid_and_reward_is_recomputable(tmp_path):
    log = RunLog("r", tmp_path)
    report = run_test(mock_system_1("A"), REQUEST, log)
    events = read_events(log.path)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    for e in events:
        if PAYLOADS[e.type] is not None:
            PAYLOADS[e.type](**e.payload)
    # from the log alone, as anyone auditing a run would
    from rav_contracts import Control, StepVerdict
    controls = [Control(**c) for e in events if e.type == "scene_ready" for c in e.payload["controls"]]
    verdicts = [StepVerdict(**e.payload["verdict"]) for e in events if e.type == "step_finished"]
    assert reward(coverage(controls, verdicts)).value == report.reward.value


def test_finding_links_back_to_its_step(tmp_path):
    log = RunLog("r", tmp_path)
    report = run_test(mock_system_1("A"), REQUEST, log)
    events = {e.seq: e for e in read_events(log.path)}
    for finding in report.findings:
        source = events[finding.event_seqs[0]]
        assert source.type == "step_finished" and source.payload["verdict"]["target"] == finding.target


def test_steering_applies_between_steps(tmp_path):
    steering = Steering()
    steering.send(SteerCommand(kind="prioritize", target="door"))
    steering.send(SteerCommand(kind="skip", target="button_3"))
    steering.send(SteerCommand(kind="message", text="check the door first"))
    log = RunLog("r", tmp_path)
    report = run_test(mock_system_1("A"), REQUEST, log, steering=steering)
    started = [e.payload["target"] for e in read_events(log.path) if e.type == "step_started"]
    assert started[0] == "door" and "button_3" not in started
    assert report.coverage.skipped == {"button_3": "no test ran"}


def test_stop_ends_the_run(tmp_path):
    steering = Steering()
    steering.send(SteerCommand(kind="stop"))
    log = RunLog("r", tmp_path)
    run_test(mock_system_1("A"), REQUEST, log, steering=steering)
    events = read_events(log.path)
    assert not [e for e in events if e.type == "step_started"]
    assert events[-1].payload == {"status": "stopped"}


def test_unapproved_plan_never_moves_the_arm(tmp_path):
    log = RunLog("r", tmp_path)
    with pytest.raises(PermissionError):
        run_test(mock_system_1("A"), REQUEST, log, approve=lambda kind, ref: None)
    assert not [e for e in read_events(log.path) if e.type == "step_started"]


def test_auto_approval_is_refused_before_a_real_arm_moves(tmp_path):
    class Real(FakeSystem1):
        def system_status(self):
            return super().system_status().model_copy(update={"robot": "real"})
    system1 = Real(MockBackend("A"))
    with pytest.raises(PermissionError):
        run_test(system1, REQUEST, RunLog("r", tmp_path))
    assert system1.routines == 0


def test_a_patch_that_does_not_match_the_file_is_refused(params):
    patch = CADPatch(file="x", revision_from="A", revision_to="B",
                     changes=[ParamChange(param="button_clearance[1]", from_value=0.99, to_value=0.4)])
    assert params.check(patch)
    with pytest.raises(ValueError):
        params.apply(patch)


def test_limits_refuse_a_patch(tmp_path):
    p = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path), limits={"button_clearance": (0.1, 0.6)})
    patch = CADPatch(file="x", revision_from="A", revision_to="B",
                     changes=[ParamChange(param="button_clearance[1]", from_value=0.15, to_value=2.0)])
    assert p.check(patch)


def test_implementations_fit_their_interfaces(params):
    assert isinstance(FakeSystem1(), System1)
    assert isinstance(params, CadBackend)


def test_a_clean_fail_wakes_the_harness_and_every_stop_is_counted(tmp_path):
    log = RunLog("r", tmp_path)
    run_test(mock_system_1("A"), REQUEST, log, policy=BALANCED)
    crossings = [e.payload for e in read_events(log.path) if e.type == "crossing"]
    assert [(c["stop"], c["code"], c["target"]) for c in crossings if c["stop"] == "escalation"] == [
        ("escalation", "step_failed", "button_2"), ("escalation", "step_failed", "door")]
    assert crossings[0]["routine"] == "explore" and crossings[-1]["stop"] == "done" and {c["policy"] for c in crossings} == {"balanced"}


def test_tethered_is_the_default_and_crosses_more(tmp_path):
    def count(**kw):
        log = RunLog("r", tmp_path)
        run_test(mock_system_1("B"), REQUEST, log, **kw)
        return len([e for e in read_events(log.path) if e.type == "crossing"])
    assert count() > count(policy=BALANCED) == 2


def test_the_same_result_whatever_the_policy(tmp_path):
    a = run_test(mock_system_1("A"), REQUEST, RunLog("a", tmp_path))
    b = run_test(mock_system_1("A"), REQUEST, RunLog("b", tmp_path), policy=BALANCED)
    assert a.reward == b.reward and [f.target for f in a.findings] == [f.target for f in b.findings]


S = [Step(id="s1", skill="press", target="a", params={"force_limit": 6}), Step(id="s2", skill="press", target="b", params={"force_limit": 6})]


@pytest.mark.parametrize("amended, level", [
    ([S[1]], AUTOMATIC),                                                                  # nothing changed
    ([S[0], S[1]], AUTOMATIC),                                                            # a retry of s1, then the plan
    ([Step(id="r", skill="press", target="a", params={"force_limit": 4}), S[1]], AUTOMATIC),  # the same at lower force
    ([], NOTIFY),                                                                         # skipping what's left
    ([Step(id="n", skill="press", target="c")], APPROVE),                                 # a new target
    ([Step(id="n", skill="flip", target="b")], APPROVE),                                  # a new skill
    ([Step(id="n", skill="press", target="b", params={"force_limit": 7})], APPROVE),      # more force
])
def test_code_grades_each_amendment(amended, level):
    assert classify(S, [S[1]], amended) == level


def _fail_then(decision):
    return lambda stop: decision if stop.escalation else Decision()


def test_a_big_amendment_waits_for_a_person_and_refusal_keeps_the_plan(tmp_path):
    new = Step(id="n", skill="press", target="somewhere_new")
    asked, system1 = [], mock_system_1("A")

    def refuse(kind, ref):
        asked.append(kind)
        return None if kind == "amendment" else "person"
    log = RunLog("r", tmp_path)
    run_test(system1, REQUEST, log, approve=refuse, policy=BALANCED, respond=_fail_then(Decision(kind="amend", steps=[new])))
    assert "amendment" in asked and new not in system1.executed


def test_a_small_amendment_runs_without_asking(tmp_path):
    asked, system1 = [], mock_system_1("A")
    retry = Step(id="retry", skill="press", target="button_2", params={"force_limit": 4})

    def respond(stop):
        if stop.escalation and stop.escalation.step == "s2":
            return Decision(kind="amend", steps=[retry, *[s for s in system1.report.fallback_plan.steps if s.target in ("button_3", "door", "display")]])
        return Decision()

    def note(kind, ref):
        asked.append(kind)
        return "person"
    log = RunLog("r", tmp_path)
    run_test(system1, REQUEST, log, approve=note, policy=BALANCED, respond=respond)
    assert asked == ["plan"] and retry in system1.executed
    amended = [e.payload for e in read_events(log.path) if e.type == "plan_amended"]
    assert amended[0]["level"] == AUTOMATIC and amended[0]["by"] is None


def test_trace_tells_the_model_from_the_pipeline(tmp_path):
    from rav_harness.mock import mock_model_run
    from rav_harness.runlog import read_events

    mock_model_run("trace", str(tmp_path))
    events = read_events(tmp_path / "trace" / "events.jsonl")
    calls = [e.payload for e in events if e.type == "tool_call"]
    turns = [e.payload for e in events if e.type == "model_turn"]
    failed = {c["error_kind"]: c["layer"] for c in calls if not c["ok"]}
    assert failed == {"unknown_target": "model", "bad_args": "model", "timeout": "pipeline"}
    assert next(t for t in turns if t["error"])["layer"] == "model"  # cut off at max_tokens
    assert all(c["turn"] for c in calls) and {c["caller"] for c in calls} == {"model"}
    verdicts = {e.payload["verdict"]["step"]: e.payload["verdict"]["status"] for e in events if e.type == "step_finished"}
    claim = next(t for t in turns if t["claims"])  # the model says it passed, and the sensors' verdict stands
    assert claim["claims"]["s2"] == "passed" and verdicts["s2"] == "failed"


def test_tracer_logs_an_error_and_still_raises_it(tmp_path):
    import pytest
    from rav_harness.runlog import RunLog, read_events
    from rav_harness.trace import Tracer

    log = RunLog("t", tmp_path)
    tracer = Tracer(log)

    def broken():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        tracer.call("x.y", {"a": 1}, broken)
    assert tracer.call("x.z", {}, lambda: {"n": 1}) == {"n": 1}
    first, second = [e.payload for e in read_events(log.path)]
    assert (first["ok"], first["layer"], first["error_kind"], first["caller"]) == (False, "pipeline", "exception", "rules")
    assert second["ok"] and second["result"] == {"n": 1}


def test_endless_small_retries_end_up_in_front_of_a_person(tmp_path):
    """Each retry here is level 0 and fails again, so without the limit this would press button_2 forever."""
    asked, system1 = [], mock_system_1("A")
    retry = Step(id="retry", skill="press", target="button_2")

    def respond(stop):
        return Decision(kind="amend", steps=[retry]) if stop.escalation and stop.escalation.target == "button_2" else Decision()

    def refuse_amendments(kind, ref):
        asked.append(kind)
        return None if kind == "amendment" else "person"
    run_test(system1, REQUEST, RunLog("r", tmp_path), approve=refuse_amendments, policy=BALANCED, respond=respond)
    assert asked.count("amendment") == 1 and sum(s.id == "retry" for s in system1.executed) == 5
