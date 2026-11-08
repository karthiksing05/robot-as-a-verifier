"""Whether a caller who knows only the tools can run a device. Everything here comes from tool results: nothing is
imported from sim/ or core/, and no fallback plan is used. Each function is what a model would have to do.

    pytest tests/test_readiness.py                 # on the mock, always; with the sim, the slow ones are marked sim
    python tests/test_readiness.py --seed 7 --fault stuck_button:button_1 --depth
    python tests/test_readiness.py --hold-s 600    # hold at a stop that long with the server connected, then resume
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from rav_server.engine import RoutineEngine
from rav_server.mcp_server import build_server
from rav_server.mock_robot import MockRobot

QUIET = {"name": "quiet", "checkpoint_every": None, "retries_per_step": 0}


class Tools:
    def __init__(self, client):
        self.client = client

    async def __call__(self, tool, **args):
        result = await self.client.call_tool(tool, args)
        assert not result.is_error, f"{tool}: {result.content}"
        return result.structured_content

    async def refused(self, tool, **args) -> str:
        result = await self.client.call_tool(tool, args)
        assert result.is_error, f"{tool} should have refused: {result.structured_content}"
        return " ".join(c.text for c in result.content)

    async def stop(self, rid):
        while True:
            cp = await self("routine_wait", routine_id=rid, timeout_s=30)
            if cp["stop"]:
                return cp

    async def idle(self):
        while (await self("system_status"))["state"] != "idle":
            await anyio.sleep(0.05)

    async def explore(self):
        handle = await self("routine_start", routine="explore", policy={"name": "floor", "confidence_floor": 0.0})
        stop = await self.stop(handle["routine_id"])
        assert stop["status"] == "completed", stop
        await self.idle()
        return (await self("scene_get"))["scene"]


def step_for(n, control, actions):
    """A valid step for a control, from what the tools published. None if nothing acts on it."""
    if control["grip"] == "pinch":
        return None
    spec = next((a for a in actions if control["kind"] in a["kinds"]), None)
    if spec is None:
        return None
    params = {}
    for p in spec["params"]:
        if not p["required"]:
            continue
        if p["name"] == "to":
            params["to"] = 1.0 if (control["position"] or 0) < 0.5 else 0.0
        elif p["name"] == "angle":
            low, high = control["turn_range_deg"] or (-60, 60)
            params["angle"] = 30.0 if high > -low else -30.0
    return {"id": f"s{n}", "skill": spec["skill"], "target": control["id"], "params": params}


def plan_from(scene, status):
    steps = [step_for(n, c, status["actions"]) for n, c in enumerate(scene["controls"], 1)]
    return {"plan_id": "from-tools", "source": "model", "steps": [s for s in steps if s]}


async def readiness(tools: Tools, expect_failure: bool = True, hold_s: float = 0.0, check_moved=None) -> dict:
    """The checks, in order. Returns what it saw, for the caller to print."""
    status = await tools("system_status")
    assert status["state"] == "idle"
    assert "no scene" in await tools.refused("routine_start", routine="run_plan", plan={"plan_id": "x", "steps": []})

    scene = await tools.explore()
    status = await tools("system_status")  # a robot's own actions appear once it exists
    assert scene["controls"] and all(c["normal"] for c in scene["controls"])
    plan = plan_from(scene, status)
    assert plan["steps"]

    # a wrong skill and an unknown target: both named, and nothing moves
    first = plan["steps"][0]
    wrong = next(a["skill"] for a in status["actions"] if a["skill"] != first["skill"])
    bad = {"plan_id": "bad", "steps": [{**first, "skill": wrong}, {"id": "ghost", "skill": first["skill"], "target": "no_such_control"}]}
    why = await tools.refused("routine_start", routine="run_plan", plan=bad, policy=QUIET)
    assert first["id"] in why and "no_such_control" in why and (await tools("system_status"))["state"] == "idle"

    # a valid plan: any planted fault comes back as a failure with numbers that explain it
    handle = await tools("routine_start", routine="run_plan", plan=plan, policy=QUIET)
    rid, verdicts, stop, amended, held = handle["routine_id"], [], None, False, False
    while True:
        stop = await tools.stop(rid)
        verdicts += stop["verdicts"]
        if stop["status"] != "paused":
            break
        if hold_s and not held:
            held = True
            await hold(tools, rid, hold_s)
        answer = {"kind": "continue"}
        last = stop["verdicts"][-1] if stop["verdicts"] else None
        if last and last["verdict"]["status"] == "failed" and not amended:
            assert last["peak_force_n"] is not None and last["travel_mm"] is not None and stop["escalation"]["measured"]
            assert "measures" in last
            amended = True
            bad_amend = {"kind": "amend", "steps": [{"id": "ghost", "skill": first["skill"], "target": "no_such_control"}]}
            assert "no_such_control" in await tools.refused("routine_resume", routine_id=rid, decision=bad_amend)
            assert (await tools("system_status"))["state"] == "paused"  # still holding
            done = {v["verdict"]["step"] for v in verdicts}
            left = [s for s in plan["steps"] if s["id"] not in done]
            retest = {**next(s for s in plan["steps"] if s["id"] == last["verdict"]["step"]), "id": "retest"}
            answer = {"kind": "amend", "steps": [retest, *left], "note": "see it again before calling it"}
        await tools("routine_resume", routine_id=rid, decision=answer)
    assert stop["stop"] == "done", stop
    statuses = {v["verdict"]["step"]: v["verdict"]["status"] for v in verdicts}
    if expect_failure:
        assert "failed" in statuses.values() and amended, statuses
        assert "retest" in statuses  # the amendment ran
    await tools.idle()

    # evidence for a step, and its frames
    trace = (await tools("evidence_get", ref=verdicts[0]["trace_ref"]))["result"]
    seen_frames = list(scene["frames"]) + list(trace["frames"])
    for ref in seen_frames[:2]:
        frame = (await tools("evidence_get", ref=ref))["result"]
        assert frame["data_b64"] and frame["width"] > 0

    # home, then look again: a sensible inventory
    handle = await tools("routine_start", routine="home")
    assert (await tools.stop(handle["routine_id"]))["status"] == "completed"
    await tools.idle()
    again = await tools.explore()
    # the plan opened any door, and an open door is no longer a door to test: everything else has to still be there
    assert {c["kind"] for c in scene["controls"]} - {"door"} <= {c["kind"] for c in again["controls"]}
    return {"controls": [c["id"] for c in scene["controls"]], "verdicts": statuses, "frames": len(seen_frames), "stop": stop["stop"]}


async def hold(tools: Tools, rid: str, seconds: float) -> None:
    """A slow model turn: the routine has to still be there, and still holding, however long this takes."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        await anyio.sleep(min(30.0, seconds))
        status = await tools("system_status")
        assert status["state"] == "paused" and status["routine_id"] == rid, status
        waited = await tools("routine_wait", routine_id=rid, timeout_s=0.1)
        assert waited["stop"] is None and waited["status"] == "paused", waited


def test_readiness_on_the_mock():
    engine = RoutineEngine(lambda: MockRobot(script={"button_2": ["failed", "passed"]}), "mock")

    async def go():
        async with Client(build_server(engine)) as client:
            return await readiness(Tools(client))
    saw = anyio.run(go)
    assert saw["verdicts"]["s2"] == "failed" and saw["verdicts"]["retest"] == "passed"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """rav-server as its own process, so everything crosses the network."""

    def __init__(self, *flags: str):
        self.port = _free_port()
        exe = Path(sys.executable).parent / "rav-server"
        self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        self.proc = subprocess.Popen([str(exe), "--robot", "sim", "--port", str(self.port), "--telemetry-port", "0", *flags], stdout=self.log, stderr=subprocess.STDOUT, env=os.environ)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def wait_up(self, timeout_s: float = 60.0) -> None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if self.proc.poll() is not None:
                raise RuntimeError(f"rav-server exited: {Path(self.log.name).read_text()[-2000:]}")
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.2)
        raise TimeoutError("rav-server didn't come up")

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


async def _over_http(url: str, fn):
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(120.0)) as http:
        async with Client(streamable_http_client(url, http_client=http), read_timeout_seconds=120.0) as client:
            return await fn(Tools(client))


def run_on_sim(*flags: str, expect_failure: bool = True, hold_s: float = 0.0) -> dict:
    server = Server(*flags)
    try:
        server.wait_up()
        return asyncio.run(_over_http(server.url, lambda tools: readiness(tools, expect_failure, hold_s)))
    finally:
        server.close()


@pytest.mark.sim
@pytest.mark.parametrize("flags", [("--fault", "stuck_button"), ("--seed", "3", "--fault", "random", "--fault-seed", "2")])
def test_readiness_on_the_sim_depth_route(flags):
    pytest.importorskip("mujoco")
    saw = run_on_sim("--depth", "--effector", "probe", *flags)  # the boundary, not the gripper: on the probe the plan's steps all act
    assert "failed" in saw["verdicts"].values() and saw["frames"]


@pytest.mark.sim
def test_a_repeat_explore_finds_the_device_where_it_moved_to(tmp_path):
    """A caller moves the device, the scene goes stale and plans are refused, and a new explore matches the true poses."""
    pytest.importorskip("mujoco")
    key = tmp_path / "key.json"
    server = Server("--depth", "--answer-key", str(key))

    async def go(tools: Tools):
        scene = await tools.explore()
        move = {"plan_id": "move", "source": "model", "steps": [{"id": "m", "skill": "reposition", "target": "device", "params": {"dx_mm": 15.0, "dy_mm": -10.0, "yaw_deg": 5.0}}]}
        stop = await tools.stop((await tools("routine_start", routine="run_plan", plan=move, policy=QUIET))["routine_id"])
        assert stop["status"] == "completed" and stop["verdicts"][0]["verdict"]["status"] == "passed"
        await tools.idle()
        assert (await tools("scene_get"))["scene"]["stale"]
        assert "run explore first" in await tools.refused("routine_start", routine="run_plan", plan=plan_from(scene, await tools("system_status")), policy=QUIET)
        return scene, await tools.explore()
    try:
        server.wait_up()
        before, after = asyncio.run(_over_http(server.url, go))
    finally:
        server.close()
    truth = {c["id"]: c["pos_mm"] for c in json.loads(key.read_text())["controls"]}
    assert not after["stale"]
    errors = [max(abs(a - b) for a, b in zip(c["pos_mm"], truth[c["id"]], strict=True)) for c in after["controls"] if c["id"] in truth]
    moved = [max(abs(a - b) for a, b in zip(c["pos_mm"], truth[c["id"]], strict=True)) for c in before["controls"] if c["id"] in truth]
    assert len(errors) >= len(truth) - 2 and max(moved) > 8 and max(errors) < 6, (errors, moved)


@pytest.mark.sim
def test_a_device_moved_with_no_warning_shows_up_as_pose_unstable(tmp_path):
    """Nothing says it moved: only the corrections each step needs. The numbers come with the stop, and a new explore recovers."""
    pytest.importorskip("mujoco")
    key = tmp_path / "key.json"
    server = Server("--depth", "--effector", "probe", "--answer-key", str(key), "--error-schedule", "5:device_moved_silent", "--error-seed", "4")

    async def go(tools: Tools):
        scene = await tools.explore()
        plan = plan_from(scene, await tools("system_status"))
        stop, stops = None, []
        rid = (await tools("routine_start", routine="run_plan", plan=plan, policy=QUIET))["routine_id"]
        while True:
            stop = await tools.stop(rid)
            stops.append(stop)
            if stop["status"] != "paused":
                break
            if stop["escalation"]["code"] == "pose_unstable":
                await tools("routine_resume", routine_id=rid, decision={"kind": "abort"})
            else:
                await tools("routine_resume", routine_id=rid, decision={"kind": "continue"})
        await tools.idle()
        return stops, await tools.explore()
    try:
        server.wait_up()
        stops, after = asyncio.run(_over_http(server.url, go))
    finally:
        server.close()
    found = [s["escalation"] for s in stops if s["escalation"] and s["escalation"]["code"] == "pose_unstable"]
    assert found, [(s["stop"], s["escalation"] and s["escalation"]["code"], [v["measures"] for v in s["verdicts"]]) for s in stops]
    assert found[0]["measured"]["values_mm"] and found[0]["measured"]["pattern"] in ("growing", "jump")
    data = json.loads(key.read_text())
    truth = {c["id"]: c["pos_mm"] for c in data["controls"]}
    errors = [max(abs(a - b) for a, b in zip(c["pos_mm"], truth[c["id"]], strict=True)) for c in after["controls"] if c["id"] in truth]
    assert data["errors"][0]["kind"] == "device_moved_silent" and errors and max(errors) < 6, errors


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed")
    ap.add_argument("--fault", default="stuck_button")
    ap.add_argument("--depth", action="store_true")
    ap.add_argument("--hold-s", type=float, default=0.0)
    args = ap.parse_args()
    flags = [*(["--seed", args.seed] if args.seed else []), *(["--depth"] if args.depth else []), "--fault", args.fault]
    print(json.dumps(run_on_sim(*flags, hold_s=args.hold_s), indent=2))
