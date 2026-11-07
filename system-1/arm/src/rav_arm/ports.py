"""What the sim's skills call on an arm. Internal to System 1: this never crosses to System 2."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ArmBackend(Protocol):
    """What system-1/sim's skills call on an arm: robot.SimArm's interface, SI units.

    A real arm implements this so that affordances.py, skills.py and touch.py run on it unchanged.
    system-1/arm/src/rav_arm/lerobot_arm.py is the skeleton. The sim also reads arm.d.time (the clock)
    and arm.app (the device readout); see that file."""

    noise_n: float
    noise_axial: float
    axial_sensor: bool

    def read_q(self) -> Any: ...

    def send(self, q: Any) -> None: ...

    def tick(self) -> None: ...

    def tip_force(self) -> float: ...

    def tip_force_vec(self) -> Any: ...

    def tip_pose(self) -> Any: ...

    def tare(self, on: bool = True) -> None: ...
