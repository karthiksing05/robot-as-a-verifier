"""What the routine engine drives: the sim today, the real arm next."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from rav_interface import Plan, SceneInventory, Step, StepTrace, StepVerdict


@runtime_checkable
class Robot(Protocol):
    def perceive(self) -> SceneInventory: ...

    def default_plan(self, scene: SceneInventory) -> Plan:
        """Rule-based plan with no model call: the fallback when the planner or network fails."""
        ...

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]: ...

    def close(self) -> None: ...
