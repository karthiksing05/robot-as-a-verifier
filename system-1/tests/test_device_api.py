"""rav-server's /readout/<device>: the boards POST snapshots over WiFi with their own key, which can't reach the MCP tools."""
import sys

import pytest

from rav_server.sim_backend import CORE_DIR, HARDWARE_DIR

pytest.importorskip("mcp")
sys.path[:0] = [str(HARDWARE_DIR), str(CORE_DIR)]

import http_readout  # noqa: E402
from rav_server.engine import RoutineEngine  # noqa: E402
from rav_server.main import build_app  # noqa: E402
from rav_server.mock_robot import MockRobot  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

TOKEN, KEY = "arm-token", "board-key"


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
