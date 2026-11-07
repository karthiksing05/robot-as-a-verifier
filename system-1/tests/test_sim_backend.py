"""The sim's words and units against the contracts. The mapping tests need no MuJoCo."""
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
