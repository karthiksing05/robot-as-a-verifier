"""The seams inside System 2. Implement one of these and the rest of the system doesn't change."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rav_interface import (Checkpoint, Decision, EscalationPolicy, Plan, RoutineHandle, RoutineName, SceneReport, StepTrace,
                           SystemStatus)

from .models import CADPatch


@runtime_checkable
class System1(Protocol):
    """The seven tools, as the harness calls them. McpSystem1 reaches the real server; mock.FakeSystem1 stands in for tests."""

    def system_status(self) -> SystemStatus: ...

    def scene_get(self) -> SceneReport: ...

    def evidence_get(self, ref: str) -> StepTrace: ...

    def routine_start(self, routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle: ...

    def routine_wait(self, routine_id: str, timeout_s: float = 30.0) -> Checkpoint: ...

    def routine_resume(self, routine_id: str, decision: Decision) -> None: ...

    def routine_stop(self, routine_id: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class CadBackend(Protocol):
    """Applies a parameter patch and checks the result. CadQuery by default; a CAD MCP server is one option."""

    name: str

    def read_params(self) -> dict[str, Any]: ...

    def check(self, patch: CADPatch) -> list[str]:
        """Problems that block this patch. Empty means it may go to a teammate for approval."""
        ...

    def apply(self, patch: CADPatch) -> str:
        """Apply an approved patch. Returns a path or URL for the new revision."""
        ...
