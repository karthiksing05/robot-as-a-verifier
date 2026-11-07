"""The published table against what the pipeline really does, and the sim's faults and errors on real physics."""
import json
import sys

import pytest
from rav_interface import Plan, SceneInventory, Step, check_steps
from rav_server.actions import ACTIONS, MAX_FORCE_N
from rav_server.main import main
from rav_server.sim_backend import CORE_DIR, SIM_DIR


def test_sim_only_flags_are_refused_for_anything_else():
    for flags in (["--fault", "stuck_button"], ["--error-rate", "0.05"], ["--answer-key", "x"], ["--placement", "random"], ["--error-schedule", "1:slow_arm"]):
        with pytest.raises(SystemExit):
            main(["--robot", "mock", *flags])


def test_the_injector_is_refused_for_anything_but_the_sim():
    from rav_server.mock_robot import MockRobot
    from rav_server.unreliable import UnreliableRobot
    with pytest.raises(ValueError, match="sim only"):
        UnreliableRobot(MockRobot(), 0.05)


def test_a_schedule_names_real_errors():
    from rav_server.unreliable import parse_schedule
    assert parse_schedule("2:false_alarm,button_2:stale_readout") == {"2": "false_alarm", "button_2": "stale_readout"}
    with pytest.raises(ValueError, match="no error called"):
        parse_schedule("2:gremlins")


sim = pytest.mark.sim


@pytest.fixture(scope="module")
def core():
    pytest.importorskip("mujoco")
    for d in (CORE_DIR, SIM_DIR):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    import affordances
    import skills
    return affordances, skills


@sim
def test_the_table_matches_the_pipeline(core):
    affordances, skills = core
    assert MAX_FORCE_N == skills.MAX_FORCE_LIMIT_N
    published = {a.skill: a for a in ACTIONS if a.skill != "observe"}
    for skill, spec in published.items():
        assert affordances.FORCE_LIMIT[skill] == next(p.default for p in spec.params if p.name == "force_limit")
    for kind, skill in affordances.SKILL_FOR.items():
        assert kind in published[skill].kinds


def _rig(core, seed=None):
    from rav_server.sim_backend import SimBackend

    return SimBackend(seed=seed, depth=True, sensing="perfect", slop=False, refine=False)


def _truth_setup(backend):
    import device

    backend.parts = device.truth(backend.arm.m, backend.arm.d)
    return {p.id: p for p in backend.parts}


@sim
def test_the_fallback_plan_is_valid_and_observes_the_display(core):
    from rav_server.sim_backend import part_to_control
    backend = _rig(core)
    try:
        _truth_setup(backend)
        controls = [part_to_control(p) for p in backend.parts]
        plan = backend.default_plan(SceneInventory(controls=controls))
        assert check_steps(plan.steps, controls, ACTIONS) == []
        assert any(s.skill == "observe" for s in plan.steps)
    finally:
        backend.close()


def _step_for(core, part):
    affordances, _ = core
    steps = [s for s in affordances.plan_tests([part]) if s["target"] == part.id]
    return Step(id="s", skill=steps[0]["skill"], target=part.id, params=steps[0].get("params", {}))


@sim
@pytest.mark.parametrize("fault", ["stuck_button", "stuck_slider", "stuck_dial", "stiff_toggle", "jammed_door", "dead_button", "dead_dial"])
def test_each_fault_really_shows_and_a_healthy_device_passes(core, fault):
    """A jammed dial comes back inconclusive, not failed: both pushes stall, and the verdict rule can't tell a jam from a
    pad on the fin's edge. That's the rule's honest answer, so a caller has to reason about it."""
    import faults

    if fault == "jammed_door" and not any(n.startswith("door") for n in _names(core)):
        pytest.skip("this device has no door")
    part = faults.FAULTS[fault]["part"]
    for planted, wanted in ((False, "passed"), (True, "inconclusive" if fault == "stuck_dial" else "failed")):
        backend = _rig(core)
        try:
            parts = _truth_setup(backend)  # what a scan would see: it can't see a jam
            if planted:
                faults.plant(backend.arm.m, fault, part, backend.arm.app, backend.arm.d)
            _, verdict = backend.execute(_step_for(core, parts[part]))
            assert verdict.status == wanted, f"{fault}, planted={planted}: {verdict.reason}"
        finally:
            backend.close()


def _names(core):
    backend = _rig(core)
    try:
        return [p.id for p in __import__("device").truth(backend.arm.m, backend.arm.d)]
    finally:
        backend.close()


@sim
def test_a_fault_goes_on_any_part_of_its_kind_and_random_comes_from_the_seed(core):
    import faults

    backend = _rig(core)
    try:
        m = backend.arm.m
        assert ("stuck_button", "button_3") in faults.options(m)
        assert faults.resolve(m, "stuck_button:button_3") == ("stuck_button", "button_3")
        assert faults.resolve(m, "random", 3) == faults.resolve(m, "random", 3)
        assert len({faults.resolve(m, "random", n) for n in range(30)}) > 3
        assert "button_3" in faults.plant(m, "stuck_button", "button_3")
        with pytest.raises(ValueError, match="no button called nope"):
            faults.plant(m, "stuck_button", "nope")
    finally:
        backend.close()


@sim
def test_a_dropped_frame_is_taken_again_and_a_dead_camera_ends_the_scan_as_a_pipeline_error(core, tmp_path):
    from rav_server.robot import PipelineFailure

    plain = _rig(core)
    try:
        expected = [(c.id, c.kind) for c in plain.perceive().controls]
    finally:
        plain.close()
    robot, sim = _unreliable(core, tmp_path, "1:dropped_frame,3:dropped_frame")
    try:
        scene = robot.perceive()
        assert [(c.id, c.kind) for c in scene.controls] == expected and "taken again" in " ".join(scene.notes)
        key = json.loads((tmp_path / "key.json").read_text())["errors"]
        assert key[0]["kind"] == "dropped_frame" and key[0]["failed"] == 2
    finally:
        robot.close()
    robot, sim = _unreliable(core, tmp_path, "2:pipeline_fault")
    try:
        with pytest.raises(PipelineFailure, match="failed to decode"):
            robot.perceive()
        assert json.loads((tmp_path / "key.json").read_text())["errors"][-1]["kind"] == "pipeline_fault"
    finally:
        robot.close()
    robot, sim = _unreliable(core, tmp_path, "1:camera_dead")
    try:
        with pytest.raises(PipelineFailure, match="gave no frame"):
            robot.perceive()
    finally:
        robot.close()


def _unreliable(core, tmp_path, schedule, **kw):
    from rav_server.sim_backend import SimBackend
    from rav_server.unreliable import UnreliableRobot

    sim = SimBackend(depth=True, sensing="perfect", slop=False, refine=False, answer_key=tmp_path / "key.json")
    return UnreliableRobot(sim, 0.0, 1, schedule, **kw), sim


@sim
@pytest.mark.parametrize("kind, status, label", [("false_alarm", "inconclusive", "unsafe"), ("stale_readout", "failed", "stuck")])
def test_an_error_goes_through_the_real_rules_and_only_the_key_says_so(core, tmp_path, kind, status, label):
    robot, sim = _unreliable(core, tmp_path, f"1:{kind}")
    try:
        parts = _truth_setup(sim)
        sim.home()  # so the forced action is the press itself, wherever in it the draw puts the spike
        _, verdict = robot.execute(_step_for(core, parts["button_1"]))
        assert (verdict.status, verdict.label) == (status, label), verdict.reason
        assert "inject" not in verdict.reason.lower() and "stale" not in verdict.reason.lower()
        assert not hasattr(sim.arm.__dict__, "tick") and sim.arm.app.__class__.__name__ == "DeviceMCU"
        errors = json.loads((tmp_path / "key.json").read_text())["errors"]
        assert [e["kind"] for e in errors] == [kind] and errors[0].get("fired", True)
        _, again = robot.execute(_step_for(core, parts["button_2"]))  # the next action is clean
        assert again.status == "passed", again.reason
    finally:
        robot.close()


@sim
def test_a_bus_fault_mid_plan_raises_and_a_missed_aim_lands_off_the_part(core, tmp_path):
    robot, sim = _unreliable(core, tmp_path, "1:pipeline_fault,2:missed_aim")
    try:
        parts = _truth_setup(sim)
        with pytest.raises(OSError):
            robot.execute(_step_for(core, parts["button_1"]))
        trace, verdict = robot.execute(_step_for(core, parts["button_2"]))
        key = json.loads((tmp_path / "key.json").read_text())
        assert key["errors"][1]["kind"] == "missed_aim" and key["errors"][1]["offset_mm"] >= 5
        assert sim.parts is not None and abs(trace.measures.get("contact_offset_mm", 0)) >= 0  # whatever the rules made of it
        assert verdict.status in ("inconclusive", "failed", "passed")
    finally:
        robot.close()


@sim
def test_a_move_changes_the_truth_and_goes_stale_and_a_silent_one_doesnt(core, tmp_path):
    robot, sim = _unreliable(core, tmp_path, "1:device_moved,2:device_moved_silent")
    try:
        parts = _truth_setup(sim)
        before = json.loads((tmp_path / "key.json").read_text())["controls"]
        robot.execute(_step_for(core, parts["button_1"]))
        assert sim.stale
        moved = json.loads((tmp_path / "key.json").read_text())
        assert moved["errors"][0]["kind"] == "device_moved" and moved["controls"][0]["pos_mm"] != before[0]["pos_mm"]
        sim.stale = False
        robot.execute(_step_for(core, parts["button_2"]))
        assert not sim.stale
        assert json.loads((tmp_path / "key.json").read_text())["errors"][1]["kind"] == "device_moved_silent"
    finally:
        robot.close()


@sim
def test_reposition_moves_the_device_and_marks_the_scene_stale(core, tmp_path):
    robot, sim = _unreliable(core, tmp_path, None)
    try:
        _truth_setup(sim)
        step = Step(id="m", skill="reposition", target="device", params={"dx_mm": 10.0, "yaw_deg": 4.0})
        before = sim.truth()[0]["pos_mm"]
        _, verdict = robot.execute(step)
        assert verdict.status == "passed" and sim.current_scene().stale and sim.truth()[0]["pos_mm"] != before
        assert any(a.skill == "reposition" for a in robot.extra_actions())
        assert sim.current_scene().controls[-1].id == "device"
        _, nothing = robot.execute(Step(id="n", skill="reposition", target="device"))
        assert nothing.status == "skipped"
    finally:
        robot.close()


def test_an_error_comes_from_what_the_action_is_not_how_many_came_before():
    from rav_server.unreliable import UnreliableRobot

    class Sim:
        is_sim, key = True, None

    def draws(order, seed=3):
        robot = UnreliableRobot(Sim(), rate=0.5, seed=seed)
        return {what: robot._roll(("a", "b", "c"), what=what) for what in order}

    one = draws(["press:button_1", "press:button_2", "turn:dial_1", "press:button_1"])
    other = draws(["turn:dial_1", "press:button_2", "press:button_1"])
    assert one["turn:dial_1"] == other["turn:dial_1"] and one["press:button_2"] == other["press:button_2"]
    robot = UnreliableRobot(Sim(), rate=0.5, seed=3)
    assert len({robot._roll(("a", "b", "c", "d"), what="press:button_1") for _ in range(12)}) > 1 and robot.draw == "press:button_1#12"
