"""rav-server --robot real with the sim behind LeRobot's bus (hardware/tests/fake_bus.py) and no camera: torque goes on
only after a yes, Ctrl+C stops the arm mid-routine, and torque is off again with the port closed however the server ends."""
import signal
import sys
import time

import pytest

from rav_server.sim_backend import CORE_DIR, HARDWARE_DIR, SIM_DIR

pytest.importorskip("mujoco")
pytest.importorskip("draccus")  # LeRobot's
pytest.importorskip("mcp")
pytestmark = pytest.mark.sim
sys.path[:0] = [str(HARDWARE_DIR / "tests"), str(HARDWARE_DIR), str(CORE_DIR), str(SIM_DIR)]

import fake_bus  # noqa: E402
import pipeline  # noqa: E402
import real_arm  # noqa: E402
import real_wrist  # noqa: E402
import robot  # noqa: E402
import world  # noqa: E402
from rav_server import main  # noqa: E402


class NoStream:
    """real_wrist.Capture with no camera."""

    def __init__(self, size):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("answer", ["no", "yes"])
def test_torque_only_after_a_yes_and_off_after_ctrl_c(answer, monkeypatch, tmp_path):
    bus = fake_bus.make(robot.SimArm(world=world.build_world(None), slop=True, sensing="current"), str(tmp_path))
    monkeypatch.setattr(real_arm, "make_bus", lambda port, calibration: bus)
    monkeypatch.setattr(real_wrist, "Capture", NoStream)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    turned_on, serving, stopped, set_torque = [], [], [], bus.fake.set_torque

    def record(ids, enabled, retries=0):
        if enabled:
            turned_on.append(list(ids))
        return set_torque(ids, enabled, retries)

    def scan(arm, *args, **kwargs):  # drives the arm until something stops it
        while True:
            arm.send(arm.read_q())
            arm.tick()

    def ctrl_c(server, sockets):
        serving.append(dict(bus.fake.torque))
        server.engine.start("explore")
        while len(bus.fake.qs) < 5:
            time.sleep(0.05)
        server.handle_exit(signal.SIGINT, None)
        stopped.append((server.engine.wait("r1", timeout_s=5), len(bus.fake.qs)))
        raise KeyboardInterrupt

    bus.fake.set_torque = record
    monkeypatch.setattr(pipeline, "scan_device", scan)
    monkeypatch.setattr(main.Server, "run", ctrl_c)
    with pytest.raises(KeyboardInterrupt if answer == "yes" else SystemExit):
        main.main(["--robot", "real", "--arm-port", "COM9", "--calibration", "unused.json", "--port", "0"])
    if answer == "yes":
        assert turned_on == [[1, 2, 3, 4, 5]] and serving == [{1: True, 2: True, 3: True, 4: True, 5: True, 6: False}]
        (checkpoint, goals), = stopped
        assert checkpoint.stop == "safety_abort" and "torque is off" in checkpoint.reason and len(bus.fake.qs) == goals
    else:
        assert turned_on == [] and serving == []
    assert not any(bus.fake.torque.values()) and not bus.fake.open
