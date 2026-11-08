"""The sim's words and units against the contracts. The mapping tests need no MuJoCo."""
import math
from types import SimpleNamespace

import pytest
from rav_interface import Step
from rav_server.robot import Robot
from rav_server.sim_backend import CORE_DIR, SIM_DIR, map_verdict, part_to_control

STEP = Step(id="s1", skill="press", target="button_1")


@pytest.mark.parametrize("raw, reason, stop, status, label", [
    ("PASS", "button_1 drives BTN1", "travel", "passed", None),
    ("FAIL", "pushed through but no reading changed", "travel", "failed", "no_actuation"),
    ("FAIL", "held at the limit but no reading changed", "force_limit", "failed", "stuck"),
    ("FAIL", "raises X, the opposite of what it did before", "travel", "failed", "wrong_behavior"),
    ("MISSED", "pad slipped off", "landed", "inconclusive", "inconclusive"),
    ("REFUSED", "needs a pinch grip", None, "skipped", "accessibility"),
    ("ABORTED", "safety stop: force", None, "inconclusive", "unsafe"),
])
def test_verdicts(raw, reason, stop, status, label):
    trace, verdict = map_verdict(STEP, {"verdict": raw, "reason": reason, "stop": stop})
    assert (verdict.status, verdict.label) == (status, label)
    assert trace.step == verdict.step == "s1"


def test_force_trace_and_readout_carry_over():
    trace, verdict = map_verdict(STEP, {"verdict": "PASS", "reason": "", "peak_force_n": 2.9, "travel_mm": 2.7, "channel": "BTN1",
                                        "force_trace": [(0.0, 0.1), (0.5, 2.9)], "readout_change": {"BTN1": [0, 1, 0]}})
    assert trace.force_trace[1] == (0.5, 2.9) and trace.readout_change == {"BTN1": [0, 1, 0]} and verdict.channel == "BTN1"


def test_metres_become_millimetres():
    part = SimpleNamespace(id="button_1", kind="button", pos=[0.25, -0.02, 0.06], normal=[0, 0, 1], size=[0.01, 0.01, 0.005],
                           motion="translation", grip="tip", score=0.9)
    control = part_to_control(part)
    assert control.pos_mm == pytest.approx((250, -20, 60)) and control.size_mm == pytest.approx((10, 10, 5))


def test_a_control_carries_what_a_plan_needs():
    base = dict(pos=[0, 0, 0], normal=[0, 0, 1], size=[0, 0, 0], motion="", grip="tip", score=1.0)
    slider = part_to_control(SimpleNamespace(id="s", kind="slider", state=0.25, range=(-0.01, 0.03), meta={"travel": 0.04}, **base))
    assert (slider.position, slider.travel_mm) == (0.25, 40.0)
    dial = part_to_control(SimpleNamespace(id="d", kind="dial", state=0.0, range=(math.radians(-90), math.radians(60)), meta={"detent_step": math.radians(30)}, **base))
    assert dial.turn_range_deg == (-90.0, 60.0) and dial.detent_deg == 30.0
    unknown = part_to_control(SimpleNamespace(id="d", kind="dial", state=0.0, range=(0.0, 0.0), meta={}, **base))
    assert unknown.turn_range_deg is None
    assert part_to_control(SimpleNamespace(id="t", kind="toggle", state=1.0, range=(0, 0), meta={"on": True}, **base)).on is True
    assert part_to_control(SimpleNamespace(id="o", kind="door", state=0.0, range=(0, 0), meta={"latched": True}, **base)).latched is True


def test_measurements_reach_the_trace_and_an_observation_counts():
    trace, _ = map_verdict(STEP, {"verdict": "MISSED", "reason": "", "contact_offset_mm": 4.2, "refined": True, "refine_shift_mm": 1.1, "landing_n": 1.3, "collisions": [], "lcd": "READY"})
    assert trace.measures == {"contact_offset_mm": 4.2, "refined": True, "refine_shift_mm": 1.1, "landing_n": 1.3, "collisions": [], "lcd": "READY"}
    _, verdict = map_verdict(Step(id="s", skill="observe", target="display_1"), {"verdict": "OBSERVED", "reason": 'shows "READY"', "channel": "LCD"})
    assert verdict.status == "observed"


def test_folders_are_where_the_adapter_looks():
    assert (CORE_DIR / "pipeline.py").is_file() and (SIM_DIR / "sim_rig.py").is_file()


@pytest.mark.sim
def test_sim_backend_fits_and_plans_on_real_parts():
    """Builds the MuJoCo scene and a backend; perception itself is the slow part, run through the server."""
    pytest.importorskip("mujoco")
    pytest.importorskip("cv2")
    from rav_server.sim_backend import SimBackend
    backend = SimBackend(seed=None, depth=True)
    try:
        assert isinstance(backend, Robot)
        import features
        assert "button" in features.KINDS
    finally:
        backend.close()
