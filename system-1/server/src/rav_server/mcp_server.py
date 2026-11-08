"""The seven tools System 2 can call. There is no motor, joint or jog tool, on purpose: docs/system-boundary.md."""
from __future__ import annotations

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from rav_interface import (Checkpoint, Decision, EscalationPolicy, Frame, Plan, RoutineHandle, RoutineName, SceneReport, StepTrace,
                           SystemStatus)

from .engine import RoutineEngine, RoutineError

MAX_WAIT_S = 60.0


class ApplianceList(BaseModel):
    devices: list[str]


class ButtonEdge(BaseModel):
    seq: int
    channel: str
    value: int


class ApplianceSnapshot(BaseModel):
    device_id: str
    readings: dict[str, int | float | str | bool | None]
    lcd: int | float | str | bool | None
    age_s: float | None
    fresh: bool
    button_edges: list[ButtonEdge] = Field(default_factory=list)


def build_server(engine: RoutineEngine, devices=None) -> MCPServer:
    mcp = MCPServer("rav-system-1", instructions="Starts routines on the robot and reports when they stop. Never moves a joint directly.")

    @mcp.tool(description="State, the skills on offer with what each acts on and takes, the force limit, and the active routine.")
    def system_status() -> SystemStatus:
        status = engine.status()
        if devices:
            status.tools.append("appliance_readout")
        return status

    if devices:
        @mcp.tool(description="Latest appliance snapshot and freshness. Omit device_id to list registered appliances.")
        def appliance_readout(device_id: str | None = None) -> ApplianceList | ApplianceSnapshot:
            if device_id is None:
                return ApplianceList(devices=sorted(devices.readouts))
            if device_id not in devices.readouts:
                raise ToolError(f"unknown appliance '{device_id}'")
            return ApplianceSnapshot(**devices.snapshot(device_id))

    @mcp.tool(description="The current SceneInventory from explore, updated as steps move parts, and a rule-based fallback plan.")
    def scene_get() -> SceneReport:
        return engine.report

    @mcp.tool(description="One step's full trace, or one camera frame, by the reference a Checkpoint, trace or scene gave. Ask only when the summary isn't enough.")
    def evidence_get(ref: str) -> StepTrace | Frame:
        try:
            return engine.evidence(ref)
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Starts explore, run_plan or home with an escalation policy. Returns at once with a handle. A bad plan fails here, naming every problem, before anything moves.")
    async def routine_start(routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        try:
            return await anyio.to_thread.run_sync(engine.start, routine, plan, policy)
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Blocks until the routine's next stop or the timeout. stop is null if it timed out still running.")
    async def routine_wait(routine_id: str, timeout_s: float = 30.0) -> Checkpoint:
        try:
            return await anyio.to_thread.run_sync(engine.wait, routine_id, min(timeout_s, MAX_WAIT_S))
        except RoutineError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(description="Answers a stop: continue, amend the remaining steps, skip targets, or abort. A bad amendment fails here, and the routine keeps holding.")
    async def routine_resume(routine_id: str, decision: Decision) -> Checkpoint:
        try:
            await anyio.to_thread.run_sync(engine.resume, routine_id, decision)
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
