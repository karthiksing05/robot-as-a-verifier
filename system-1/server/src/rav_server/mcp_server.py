"""The seven tools System 2 can call. There is no motor, joint or jog tool, on purpose: docs/system-boundary.md."""
from __future__ import annotations

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from rav_interface import (Checkpoint, Decision, EscalationPolicy, Plan, RoutineHandle, RoutineName, SceneReport, StepTrace,
                           SystemStatus)

from .engine import RoutineEngine, RoutineError

MAX_WAIT_S = 60.0


def build_server(engine: RoutineEngine) -> MCPServer:
    mcp = MCPServer("rav-system-1", instructions="Starts routines on the robot and reports when they stop. Never moves a joint directly.")

    @mcp.tool(description="State, health, the skills on offer, and the active routine.")
    def system_status() -> SystemStatus:
        return engine.status()

    @mcp.tool(description="The latest SceneInventory from explore, and a rule-based fallback plan.")
    def scene_get() -> SceneReport:
        return engine.report

    @mcp.tool(description="One step's full trace by the reference a Checkpoint gave. Ask only when the summary isn't enough.")
    def evidence_get(ref: str) -> StepTrace:
        try:
            return engine.evidence(ref)
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Starts explore, run_plan or home with an escalation policy. Returns at once with a handle.")
    def routine_start(routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        try:
            return engine.start(routine, plan, policy)
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Blocks until the routine's next stop or the timeout. stop is null if it timed out still running.")
    async def routine_wait(routine_id: str, timeout_s: float = 30.0) -> Checkpoint:
        try:
            return await anyio.to_thread.run_sync(engine.wait, routine_id, min(timeout_s, MAX_WAIT_S))
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Answers a stop: continue, amend the remaining steps, skip targets, or abort.")
    def routine_resume(routine_id: str, decision: Decision) -> Checkpoint:
        try:
            engine.resume(routine_id, decision)
        except RoutineError as e:
            raise ToolError(str(e)) from e
        return Checkpoint(routine_id=routine_id)

    @mcp.tool(description="Stops the routine at the next step boundary. The hardware E-stop is separate.")
    def routine_stop(routine_id: str) -> Checkpoint:
        try:
            engine.stop(routine_id)
        except RoutineError as e:
            raise ToolError(str(e)) from e
        return Checkpoint(routine_id=routine_id)

    return mcp
