"""The tool surface itself, over the protocol."""
import json

import anyio
import pytest
from mcp import Client
from rav_interface import TOOLS, Plan, Step
from rav_server.engine import RoutineEngine
from rav_server.main import build_app
from rav_server.mcp_server import build_server
from rav_server.mock_robot import MockRobot
from starlette.testclient import TestClient

MOTORISH = ("motor", "joint", "jog", "servo", "waypoint")


async def call(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    return result.structured_content


def test_exactly_the_agreed_tools_and_no_way_to_move_a_joint():
    async def go():
        async with Client(build_server(RoutineEngine(MockRobot, "mock"))) as client:
            return await client.list_tools()
    tools = anyio.run(go).tools
    assert {t.name for t in tools} == set(TOOLS)
    for t in tools:
        assert not any(word in t.name for word in MOTORISH)
        assert all(c.isalnum() or c == "_" for c in t.name)  # Claude's API refuses dots in tool names


def test_a_whole_routine_over_the_protocol():
    plan = Plan(plan_id="p", steps=[Step(id="s1", skill="press", target="button_1"), Step(id="s2", skill="press", target="button_2")])
    engine = RoutineEngine(lambda: MockRobot(script={"button_1": ["failed"]}), "mock")

    async def go():
        async with Client(build_server(engine)) as client:
            assert (await call(client, "system_status"))["state"] == "idle"
            explore = await call(client, "routine_start", routine="explore")
            assert (await call(client, "routine_wait", routine_id=explore["routine_id"], timeout_s=5))["stop"] == "done"
            await anyio.sleep(0.05)
            handle = await call(client, "routine_start", routine="run_plan", plan=plan.model_dump(mode="json"), policy={"checkpoint_every": None})
            rid = handle["routine_id"]
            stop = await call(client, "routine_wait", routine_id=rid, timeout_s=5)
            assert stop["escalation"]["code"] == "step_failed"
            trace = await call(client, "evidence_get", ref=stop["verdicts"][0]["trace_ref"])
            assert trace["result"]["force_trace"]
            bad_plan = await client.call_tool("routine_resume", {"routine_id": rid, "decision": {"kind": "amend", "steps": [{"id": "x", "skill": "press", "target": "nope"}]}})
            assert bad_plan.is_error and "no control called nope" in bad_plan.content[0].text
            await call(client, "routine_resume", routine_id=rid, decision={"kind": "continue"})
            end = await call(client, "routine_wait", routine_id=rid, timeout_s=5)
            assert (end["stop"], end["status"]) == ("done", "completed")
            bad = await client.call_tool("evidence_get", {"ref": "nope"})
            assert bad.is_error
    anyio.run(go)


def test_it_wont_listen_on_the_network_without_a_token():
    with pytest.raises(SystemExit):
        build_app(RoutineEngine(MockRobot, "mock"), "0.0.0.0", None)


def test_a_token_is_required_when_set():
    app = build_app(RoutineEngine(MockRobot, "mock"), "0.0.0.0", "secret")
    client = TestClient(app, raise_server_exceptions=False)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert client.post("/mcp", content=body, headers={"content-type": "application/json"}).status_code == 401
    assert client.post("/mcp", content=body, headers={"content-type": "application/json", "authorization": "Bearer nope"}).status_code == 401
