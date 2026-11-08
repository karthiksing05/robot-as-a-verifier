"""The real SO-101 and its USB wrist camera (hardware/hw_rig.py) as a Robot, on the RGB route: the real rig has no depth
camera. Building it connects with torque off, and main.py asks before turning torque on. Both happen once, on the main
thread at startup, and the engine's worker then uses this backend. close() turns torque off and the arm goes limp."""
from __future__ import annotations

from .sim_backend import CORE_DIR, HARDWARE_DIR, PipelineRobot, on_path


class RealBackend(PipelineRobot):
    """arm_port is the servo bus's serial port and calibration the file lerobot-calibrate wrote. The device's readout is
    the appliance's Pico on readout_port (pico_readout.PicoReadout), or with readout_device the board that POSTs to
    /readout/<readout_device> over WiFi (http_readout.HttpReadout, kept as self.http_readout for the server to feed), or
    else real_arm.OperatorReadout: after each test motion, the server's terminal asks what changed on the device."""

    def __init__(self, arm_port: str, calibration: str, refine: bool = True, readout_port: str | None = None,
                 readout_device: str | None = None, readout_url: str | None = None):
        on_path(CORE_DIR, HARDWARE_DIR)
        import hw_rig

        self.http_readout = None
        if readout_device:
            import http_readout
            self.http_readout = http_readout.HttpReadout(readout_device, readout_url)
        rig = hw_rig.make_rig(arm_port, calibration, app=self.http_readout, readout_port=readout_port)
        super().__init__(rig, refine=refine, plan_id="rules-real")
