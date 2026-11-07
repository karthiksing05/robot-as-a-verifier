"""The real SO-101 and its USB wrist camera (hardware/hw_rig.py) as a Robot, on the RGB route: the real rig has no depth
camera. Building it connects with torque off, and main.py asks before turning torque on. Both happen once, on the main
thread at startup, and the engine's worker then uses this backend. close() turns torque off and the arm goes limp."""
from __future__ import annotations

from .sim_backend import CORE_DIR, HARDWARE_DIR, PipelineRobot, on_path


class RealBackend(PipelineRobot):
    """arm_port is the servo bus's serial port and calibration the file lerobot-calibrate wrote. The device's readout is
    real_arm.OperatorReadout: after each test motion, the server's terminal asks what changed on the device."""

    def __init__(self, arm_port: str, calibration: str, refine: bool = True):
        on_path(CORE_DIR, HARDWARE_DIR)
        import hw_rig

        super().__init__(hw_rig.make_rig(arm_port, calibration), refine=refine, plan_id="rules-real")
