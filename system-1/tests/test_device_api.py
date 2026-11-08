"""rav-server's /readout/<device>: the boards POST snapshots over WiFi with their own key, which can't reach the MCP tools."""
import asyncio
import sys

import pytest

from rav_server.sim_backend import CORE_DIR, HARDWARE_DIR

pytest.importorskip("mcp")
sys.path[:0] = [str(HARDWARE_DIR), str(CORE_DIR)]

import http_readout  # noqa: E402
from rav_server.engine import RoutineEngine  # noqa: E402
from rav_server.main import build_app  # noqa: E402
from rav_server.mcp_server import build_server  # noqa: E402
from rav_server.mock_robot import MockRobot  # noqa: E402
from rav_server.device_api import DeviceApi  # noqa: E402
from mcp import Client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

TOKEN, KEY = "arm-token", "board-key"


def test_system_status_reports_appliance_tool_only_when_registered():
    async def check():
        engine = RoutineEngine(MockRobot, "mock")
        devices = DeviceApi({"mw1": http_readout.HttpReadout("mw1")}, {"mw1": KEY})
        for config in (None, devices):
            async with Client(build_server(engine, config)) as mcp:
                result = await mcp.call_tool("system_status", {})
                assert not result.is_error
                assert ("appliance_readout" in result.structured_content["tools"]) == (config is not None)

    asyncio.run(check())


def client(host="0.0.0.0", token=TOKEN, key=KEY):
    r = http_readout.HttpReadout("mw1")
    app = build_app(RoutineEngine(MockRobot, "mock"), host, token, {"mw1": r}, key)
    return TestClient(app), r


def test_a_board_posts_and_the_readout_follows():
    c, r = client()
    auth = {"Authorization": f"Bearer {KEY}"}
    assert c.post("/readout/mw1", json={"BTN1": 0, "LCD": "READY"}, headers=auth).status_code == 204
    assert c.post("/readout/mw1", json={"BTN1": 1}, headers=auth).status_code == 204
    assert r.readings == {"BTN1": 1} and r.lcd == "READY" and [(ch, v) for _, ch, v in r.events] == [("BTN1", 1)]
    got = c.get("/readout/mw1", headers=auth).json()
    assert got["readings"] == {"BTN1": 1} and got["lcd"] == "READY" and got["age_s"] >= 0


@pytest.mark.parametrize("headers, body, status", [
    ({}, {"BTN1": 0}, 401),
    ({"Authorization": f"Bearer {TOKEN}"}, {"BTN1": 0}, 401),  # the arm's token is not the board's key
    ({"Authorization": f"Bearer {KEY}"}, b"not json", 400),
    ({"Authorization": f"Bearer {KEY}"}, [1, 2], 400),
    ({"Authorization": f"Bearer {KEY}"}, {"BTN1": {"nested": 1}}, 400),
    ({"Authorization": f"Bearer {KEY}"}, {"X": "a" * 5000}, 413),
])
def test_refused_posts_change_nothing(headers, body, status):
    c, r = client()
    kw = {"content": body} if isinstance(body, bytes) else {"json": body}
    assert c.post("/readout/mw1", headers=headers, **kw).status_code == status
    assert not r.started


def test_unknown_device_and_wrong_method():
    c, _ = client()
    auth = {"Authorization": f"Bearer {KEY}"}
    assert c.post("/readout/other", json={"BTN1": 0}, headers=auth).status_code == 404
    assert c.put("/readout/mw1", json={"BTN1": 0}, headers=auth).status_code == 405


def test_the_device_key_never_opens_the_tools():
    c, _ = client()
    assert c.post("/mcp", json={}, headers={"Authorization": f"Bearer {KEY}"}).status_code == 401


def test_board_credentials_are_scoped_to_one_id():
    readouts = {name: http_readout.HttpReadout(name) for name in ("mc6-01", "mw1-01")}
    app = build_app(RoutineEngine(MockRobot, "mock"), "127.0.0.1", TOKEN, readouts,
                    {"mc6-01": "centrifuge-key", "mw1-01": "microwave-key"})
    c = TestClient(app)
    auth = {"Authorization": "Bearer centrifuge-key"}
    assert c.post("/readout/mw1-01", json={"door": 1}, headers=auth).status_code == 401
    assert not readouts["mw1-01"].started
    assert c.post("/readout/mc6-01", json={"speed": 1000}, headers=auth).status_code == 204
    assert c.get("/readout/mc6-01", headers=auth).json()["fresh"]
    mw1_auth = {"Authorization": "Bearer microwave-key"}
    assert c.post("/readout/mw1-01", json={"door": 1, "time": 0, "LCD": "READY"}, headers=mw1_auth).status_code == 204
    assert readouts["mw1-01"].snapshot()["readings"] == {"door": 1, "time": 0}
    assert readouts["mc6-01"].snapshot()["readings"] == {"speed": 1000}
    assert c.post("/readout/mc6-01", json={}, headers=auth).status_code == 400
    assert c.post("/readout/mc6-01", json={"lid": 1}, headers=auth).status_code == 204
    assert readouts["mc6-01"].readings == {"lid": 1}


def test_appliance_listener_is_separate_from_mcp():
    readout = http_readout.HttpReadout("mw1")
    app = build_app(RoutineEngine(MockRobot, "mock"), "127.0.0.1", TOKEN,
                    {"mw1": readout}, {"mw1": KEY}, device_port=8782)
    c = TestClient(app)
    board = {"Authorization": f"Bearer {KEY}", "Host": "127.0.0.1:8782"}
    assert c.post("http://127.0.0.1:8780/readout/mw1", json={"door": 1}, headers=board).status_code == 404
    assert c.post("http://127.0.0.1:8782/readout/mw1", json={"door": 1}, headers=board).status_code == 204
    assert c.post("http://127.0.0.1:8782/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 404


def test_cloud_readout_is_publish_only_and_requires_a_per_device_key():
    readout = http_readout.HttpReadout("mw1-01")
    engine = RoutineEngine(MockRobot, "mock")
    route = "/cloud/readout/mw1-01"
    auth = {"Authorization": f"Bearer {KEY}"}
    c = TestClient(build_app(engine, "127.0.0.1", TOKEN, {"mw1-01": readout}, {"mw1-01": KEY}))
    assert c.post(route, json={"door": 1}).status_code == 401
    assert c.post(route, json={"door": 1}, headers=auth).status_code == 204
    assert readout.readings == {"door": 1}
    assert c.get(route, headers=auth).status_code == 404
    legacy = TestClient(build_app(engine, "127.0.0.1", TOKEN, {"mw1-01": readout}))
    assert legacy.post(route, json={"door": 0}).status_code == 404
    assert readout.readings == {"door": 1}


def test_refuses_to_start_without_a_separate_key_off_loopback():
    with pytest.raises(SystemExit, match="RAV_DEVICE_KEY"):
        client(key=None)
    with pytest.raises(SystemExit, match="must differ"):
        client(key=TOKEN)
    c, r = client(host="127.0.0.1", token=None, key=None)  # on loopback, as with RAV_TOKEN, no key is needed
    assert c.post("/readout/mw1", json={"BTN1": 0}).status_code == 204 and r.started


def test_real_backend_puts_the_wifi_readout_on_the_rig(monkeypatch):
    import types

    from rav_server import real_backend

    made = {}

    class Rig:
        arm = None

    def make_rig(arm_port, calibration, app=None, pad=None, readout_port=None):
        made.update(app=app, readout_port=readout_port)
        return Rig()

    monkeypatch.setitem(sys.modules, "hw_rig", types.SimpleNamespace(make_rig=make_rig))  # no LeRobot needed
    robot = real_backend.RealBackend("COM5", "cal.json", readout_device="mw1", readout_url="http://lab:8780/readout/mw1")
    assert made == {"app": robot.http_readout, "readout_port": None} and robot.http_readout.device == "mw1"
    robot = real_backend.RealBackend("COM5", "cal.json", readout_port="COM7")
    assert made == {"app": None, "readout_port": "COM7"} and robot.http_readout is None
