"""A scripted robot, so the server and engine run with no sim or hardware. System 2 has its own fake of this server."""
from __future__ import annotations

from rav_interface import Control, Plan, SceneInventory, Step, StepTrace, StepVerdict


class MockRobot:
    """Results come from `script`: target -> a list of statuses, one per attempt. Anything else passes."""

    def __init__(self, script: dict[str, list[str]] | None = None, targets: tuple[str, ...] = ("button_1", "button_2", "button_3"), conf: float = 1.0):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.targets, self.conf = targets, conf
        self.executed: list[Step] = []
        self.closed = False

    def perceive(self) -> SceneInventory:
        return SceneInventory(controls=[Control(id=t, kind="button", pos_mm=(250.0, 25.0 * n, 60.0), normal=(0.0, 0.0, 1.0), conf=self.conf, source="mock")
                                        for n, t in enumerate(self.targets)])

    def default_plan(self, scene: SceneInventory) -> Plan:
        return Plan(plan_id="mock", source="mock", steps=[Step(id=f"s{n + 1}", skill="press", target=c.id) for n, c in enumerate(scene.controls)])

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        self.executed.append(step)
        planned = self.script.get(step.target)
        status = planned.pop(0) if planned else "passed"
        label = {"failed": "stuck", "wrong": "wrong_behavior", "inconclusive": "inconclusive", "unsafe": "unsafe"}.get(status)
        if status in ("wrong",):
            status = "failed"
        if status == "unsafe":
            status = "inconclusive"
        return (StepTrace(step=step.id, stop_reason="force_limit", peak_force_n=4.8, travel_mm=0.3, force_trace=[(0.0, 0.0), (1.0, 4.8)]),
                StepVerdict(step=step.id, target=step.target, status=status, label=label, reason=f"scripted {status}"))

    def close(self) -> None:
        self.closed = True
