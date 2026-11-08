"""The telemetry channel: what it serves, who it answers, and that watching changes nothing about a run."""
import http.client
import json
import struct
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from rav_interface import Step
from rav_server.engine import RoutineEngine
from rav_server.main import main as _main  # noqa: F401  (the flags import cleanly without a sim)
from rav_server.mock_robot import MockRobot
from rav_server.telemetry import Recorder, Telemetry

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


class FakeArm:
    """Enough of rig.Arm for the hooks: a clock, two bodies, a force log and a display."""

    def __init__(self):
        self.d = SimpleNamespace(time=0.0, xpos=np.zeros((3, 3)), xquat=np.tile([1.0, 0, 0, 0], (3, 1)))
        self.force_log, self.status, self.on_tick = [], "idle", None
        self.app = SimpleNamespace(lcd="READY")

    def step(self, dt=0.01, force=1.0):
        self.d.time += dt
        self.force_log.append((self.d.time, force))
        self.on_tick(self)


def attached(**kw):
    tel = Telemetry(**kw)
    robot = SimpleNamespace(arm=FakeArm(), rig=None, depth=True)
    tel.instrument(robot)
    tel.moving = [1, 2]
    return tel, robot.arm


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    return r.status, json.loads(r.read())


def post(port, path, body, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, json.dumps(body), headers={"Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    return r.status, r.read()


def first_event(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=ORIGIN)
    r = c.getresponse()
    assert r.getheader("Access-Control-Allow-Origin") == ORIGIN["Origin"]
    lines = []
    while True:
        line = r.fp.readline().decode()
        if line.startswith(":"):
            continue
        if line == "\n" and lines:
            c.close()
            return lines
        lines.append(line.strip())


@pytest.fixture
def served():
    tel, arm = attached()
    port = tel.serve(0)
    yield tel, arm, port
    tel.close()


def test_health_says_what_is_there_before_any_routine():
    tel = Telemetry(run_id="abc")
    port = tel.serve(0)
    try:
        assert get(port, "/health")[1]["run_id"] == "abc"
        assert get(port, "/scene.json")[1] == {"run_id": None}
        assert get(port, "/nope")[0] == 404
        assert get(port, "/feed/wrist")[0] == 404
    finally:
        tel.close()


def test_only_the_console_may_read_from_a_page_or_change_the_speed(served):
    tel, _, port = served
    assert get(port, "/health", {"Origin": "http://evil.example"})[0] == 403
    assert post(port, "/speed", {"rate": 4})[0] == 403
    assert post(port, "/speed", {"rate": 4}, {"Origin": "http://evil.example"})[0] == 403
    assert post(port, "/speed", {"rate": 3}, ORIGIN)[0] == 400
    assert post(port, "/speed", {"rate": 4}, ORIGIN)[0] == 200 and tel.speed == 4


def test_poses_stream_latest_body_values(served):
    tel, arm, port = served
    tel.watching["poses"] = 1  # so the arm publishes before the stream connects
    arm.d.xpos[1] = [0.1, 0.2, 0.3]
    arm.step()
    data = first_event(port, "/poses")
    body = json.loads(data[0].removeprefix("data: "))
    assert len(body) == 14 and body[:3] == [0.1, 0.2, 0.3]


def test_telemetry_has_the_consoles_shape(served):
    tel, arm, port = served
    tel.watching["telemetry"] = 1
    tel.set_stage("TEST", "press button_1")
    arm.step(force=2.5)
    tel.next_telemetry = 0
    arm.step(force=2.5)
    event, data = first_event(port, "/telemetry")
    assert event == "event: telemetry"
    body = json.loads(data.removeprefix("data: "))
    assert {"wall", "sim_t", "stage", "status", "rate", "feeds", "force", "paused", "step", "substage", "lcd", "probe_n"} <= set(body)
    assert body["stage"] == "TEST" and body["lcd"] == ["READY"] and body["probe_n"] == 2.5


def test_nothing_is_published_with_nobody_watching():
    tel, arm = attached()
    for _ in range(5):
        arm.step()
        time.sleep(0.04)
    assert tel.poses[0] == 0 and tel.telemetry[0] == 0 and tel.frames == {}


def test_the_depth_route_folds_segmenting_into_map():
    tel, _ = attached()
    assert tel.meta["stages"] == ["SURVEY", "SCAN", "MAP", "PLAN", "TEST", "REPORT"]
    tel.set_stage("SEGMENT", "segment")
    assert tel.stage == "MAP"


def test_camera_renders_are_capped_however_fast_the_sim_runs():
    tel, _ = attached()
    renders = []
    cam = SimpleNamespace(_render=lambda depth: renders.append(1) or (np.zeros((2, 2, 3), np.uint8), None))
    for _ in range(100):
        assert tel._preview("wrist", cam) is not None
    assert len(renders) == 1
    tel.views["wrist"] = (0.0, tel.views["wrist"][1])
    tel._preview("wrist", cam)
    assert len(renders) == 2


def test_speed_holds_sim_time_to_the_rate():
    tel, arm = attached(speed=4)
    start = time.monotonic()
    for _ in range(40):
        arm.step(dt=0.01)  # 0.4 sim seconds
    assert 0.08 < time.monotonic() - start < 0.3


def test_unpaced_doesnt_wait():
    _, arm = attached()
    start = time.monotonic()
    for _ in range(1000):
        arm.step(dt=0.01)
    assert time.monotonic() - start < 0.2


def test_a_hook_that_raises_is_switched_off_and_the_run_goes_on():
    tel, arm = attached()
    arm.force_log = [("not", "a number")]
    arm.on_tick(arm)  # raises inside tel.tick
    assert not tel.hooks_on
    arm.on_tick(arm)


def test_recording_writes_one_frame_per_thirtieth_of_a_sim_second(tmp_path):
    tel, arm = attached(record_dir=tmp_path / "run-1")
    assert tel.run_id == "run-1"
    tel.set_stage("SURVEY")
    for _ in range(100):
        arm.step(dt=0.01, force=3.0)  # one sim second
    tel.close()
    raw = (tmp_path / "run-1/poses.bin").read_bytes()
    stride = 1 + 2 * 7
    frames = len(raw) // (stride * 4)
    assert frames == pytest.approx(30, abs=1) and len(raw) % (stride * 4) == 0
    assert struct.unpack_from("<f", raw, 0)[0] == 3.0
    t = json.loads((tmp_path / "run-1/timeline.json").read_text())
    assert t["fps"] == 30 and t["stages"][0]["name"] == "SURVEY" and t["lcd"][0]["lines"] == ["READY"] and t["events"] == {} and t["anchors"]


def test_a_routine_reports_its_stage_and_step_through_the_robots_methods():
    tel = Telemetry()
    seen = []
    tel.set_stage = lambda s, sub=None: seen.append((s, sub))
    robot = MockRobot()
    engine = RoutineEngine(lambda: tel.instrument(robot), "mock")
    tel.status_fn = engine.status
    handle = engine.start("explore")
    assert engine.wait(handle.routine_id, 5).stop == "done"
    robot.execute(Step(id="s1", skill="press", target="button_1"))
    assert ("SURVEY", "survey") in seen and ("TEST", "press button_1") in seen
    engine.shutdown()


@pytest.mark.sim
def test_scene_comes_from_a_compiled_model_with_mesh_files(tmp_path):
    mujoco = pytest.importorskip("mujoco")
    pytest.importorskip("cv2")
    from rav_server.telemetry import build_scene, write_scene

    stl = tmp_path / "part.obj"
    stl.write_text("v 0 0 0\nv .01 0 0\nv 0 .01 0\nv 0 0 .01\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n")
    xml = f"""<mujoco><asset><mesh name="part" file="{stl}"/></asset><worldbody>
      <body name="lid"><joint type="hinge"/><geom type="mesh" mesh="part"/></body>
      <geom name="base" type="box" size=".1 .1 .01"/></worldbody></mujoco>"""
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_kinematics(m, d)
    scene, blobs = build_scene(m, d, "r")
    assert scene["moving"] == [1] and any(g["type"] == "mesh" for g in scene["geoms"]) and any(p.startswith("mesh/") for p in blobs)
    write_scene(tmp_path / "out", scene, blobs)
    assert json.loads((tmp_path / "out/scene/scene.json").read_text())["run_id"] == "r"
