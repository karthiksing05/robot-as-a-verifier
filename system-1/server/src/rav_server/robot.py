"""What the routine engine drives: the sim today, the real arm next."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from rav_interface import Plan, SceneInventory, Step, StepTrace, StepVerdict


class PipelineFailure(RuntimeError):
    """Perception couldn't do its job, and nothing is dangerous. Becomes a pipeline_error stop, which needs no person. Only
    perceive raises it: anything else a robot raises, mid-motion or from a driver, is a safety_abort, because then we
    can't be sure the arm is safe."""


@runtime_checkable
class Robot(Protocol):
    def perceive(self) -> SceneInventory: ...

    def default_plan(self, scene: SceneInventory) -> Plan:
        """Rule-based plan with no model call: the fallback when the planner or network fails."""
        ...

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]: ...

    def close(self) -> None: ...
