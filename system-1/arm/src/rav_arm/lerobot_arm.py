"""SUPERSEDED: the real-arm backend is system-1/sim/real_arm.py (RealArm), which reuses robot.py's IK and force estimate.
This skeleton stays as the interface notes it was written as.

The real SO-101 behind the interface system-1/sim's skills already use.

Kanban: "LeRobot arm backend". Implementing this lets affordances.py, skills.py and touch.py run on the real
arm unchanged. Method meanings are in the SimArm docstring (system-1/sim/robot.py). All values are SI: metres,
radians, newtons.

Besides these methods, the sim's code reads:
  arm.d.time                 the clock. Give the real arm a small object with a monotonic .time.
  arm.app                    the device readout (.readings, .events). On the printed appliance this is the
                             ground-truth Pico (system-1/subjects/appliance/firmware), read over serial.
  arm.ik, arm.noise_n, arm.noise_axial, arm.axial_sensor, arm.on_tick
robot.IK solves on the MuJoCo model, so the real arm can reuse it for IK: no placo (docs/decisions.md D6).
Keep LeRobot's max_relative_target on, and lower the servo torque limit during contact moves.
"""
from __future__ import annotations


class LeRobotArm:
    noise_n = 2.5        # robot.SENSED_NOISE_N until the bench test measures it
    noise_axial = 0.1    # robot.PAD_NOISE_N for the SensX pad
    axial_sensor = True  # True with the SensX pad or a load cell

    def __init__(self, port: str, pad_port: str | None = None, readout_port: str | None = None):
        self.port, self.pad_port, self.readout_port = port, pad_port, readout_port

    def _todo(self):
        raise NotImplementedError("LeRobotArm is superseded: use RealArm in system-1/sim/real_arm.py")

    def read_q(self):
        """Joint angles (rad) as believed, from lerobot's SO follower."""
        self._todo()

    def send(self, q):
        """Command joint targets (rad), through the safety limits."""
        self._todo()

    def tick(self):
        """Wait one control period (50 Hz), and run on_tick if set."""
        self._todo()

    def tip_force(self):
        """Force along the probe (N), from the pad; the hard force cap also reads this."""
        self._todo()

    def tip_force_vec(self):
        """3D force at the tip (N): the pad along the probe, the servo estimate across it."""
        self._todo()

    def tip_pose(self):
        """4x4 tip pose from forward kinematics on read_q()."""
        self._todo()

    def tare(self, on=True):
        """Zero the servo force estimate; tare(False) drops the zero."""
        self._todo()
