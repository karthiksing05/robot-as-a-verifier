"""McpSystem1: the harness's side of the MCP tools, over HTTP. System 1 may be on another machine."""
from __future__ import annotations

import os
from typing import Any

import anyio
import anyio.abc
import httpx2
from anyio.from_thread import start_blocking_portal
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from rav_interface import (Checkpoint, Decision, EscalationPolicy, Plan, RoutineHandle, RoutineName, SceneReport, StepTrace,
                           SystemStatus)

DEFAULT_URL = "http://127.0.0.1:8780/mcp"
READ_TIMEOUT_S = 90.0  # longer than the server's longest routine_wait


class ToolFailed(RuntimeError):
    """System 1 refused a call or couldn't carry it out."""


class CantReachSystem1(ConnectionError):
    """The server is down, or it refused our token."""


class McpSystem1:
    """Sync calls, because the run loop is sync. One background event loop holds the connection open."""

    def __init__(self, url: str = DEFAULT_URL, token: str | None = None):
        token = token or os.environ.get("RAV_TOKEN")
        self.url, self.headers = url, {"Authorization": f"Bearer {token}"} if token else None
        self._portal_cm = start_blocking_portal()
        self.portal = self._portal_cm.__enter__()
        try:
            self._task, self.client = self.portal.start_task(self._hold_connection)
        except Exception as e:
            self._portal_cm.__exit__(None, None, None)
            raise CantReachSystem1(f"can't reach System 1 at {url}. Is rav-server running, and is RAV_TOKEN right?") from e

    async def _hold_connection(self, task_status: anyio.abc.TaskStatus) -> None:
        """The connection has to open and close in one task, so this task owns it for the client's whole life."""
        self._closing = anyio.Event()
        async with httpx2.AsyncClient(headers=self.headers, timeout=httpx2.Timeout(READ_TIMEOUT_S)) as http:
            async with Client(streamable_http_client(self.url, http_client=http), read_timeout_seconds=READ_TIMEOUT_S) as client:
                task_status.started(client)
                await self._closing.wait()

    def _call(self, tool: str, **args: Any) -> dict:
        result = self.portal.call(self.client.call_tool, tool, {k: v for k, v in args.items() if v is not None})
        if result.is_error:
            raise ToolFailed(f"{tool}: {' '.join(getattr(c, 'text', '') for c in result.content)}")
        return result.structured_content or {}

    def system_status(self) -> SystemStatus:
        return SystemStatus(**self._call("system_status"))

    def scene_get(self) -> SceneReport:
        return SceneReport(**self._call("scene_get"))

    def evidence_get(self, ref: str) -> StepTrace:
        return StepTrace(**self._call("evidence_get", ref=ref))

    def routine_start(self, routine: RoutineName, plan: Plan | None = None, policy: EscalationPolicy | None = None) -> RoutineHandle:
        return RoutineHandle(**self._call("routine_start", routine=routine, plan=plan.model_dump(mode="json") if plan else None,
                                          policy=policy.model_dump(mode="json") if policy else None))

    def routine_wait(self, routine_id: str, timeout_s: float = 30.0) -> Checkpoint:
        return Checkpoint(**self._call("routine_wait", routine_id=routine_id, timeout_s=timeout_s))

    def routine_resume(self, routine_id: str, decision: Decision) -> None:
        self._call("routine_resume", routine_id=routine_id, decision=decision.model_dump(mode="json"))

    def routine_stop(self, routine_id: str) -> None:
        self._call("routine_stop", routine_id=routine_id)

    def close(self) -> None:
        self.portal.call(self._closing.set)
        self._task.result(timeout=10)
        self._portal_cm.__exit__(None, None, None)
