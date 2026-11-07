"""system-1/hardware/real_cameras.py with no hardware: the sim's renders stand in for the iPhone's Record3D stream, and the
frames go through the same calls the pipeline makes on the rig."""
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from rav_server.sim_backend import CORE_DIR, HARDWARE_DIR, SIM_DIR

pytest.importorskip("mujoco")
pytest.importorskip("cv2")
pytestmark = pytest.mark.sim
sys.path[:0] = [str(CORE_DIR), str(SIM_DIR), str(HARDWARE_DIR)]

import cv2  # noqa: E402

import real_cameras  # noqa: E402


class Ticker:
    """A source that returns make() every period seconds, as a camera does."""

    def __init__(self, make, period=0.01):
        self.make, self.period, self.n = make, period, 0

    def read(self):
        time.sleep(self.period)
        self.n += 1
        return True, self.make(self.n)


class FakeRecord3D:
    """Record3DStream's calls, serving sim renders, with on_new_frame fired from another thread."""

    def __init__(self, rgb_bgr, depth, conf, K):
        self.rgb, self.depth, self.conf, self.K = rgb_bgr[:, :, ::-1].copy(), depth, conf, K
        self.on_new_frame, self.running = None, True
        threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self):
        while self.running:
            time.sleep(0.02)
            if self.on_new_frame:
                self.on_new_frame()

    def get_device_type(self):
        return real_cameras.R3D_LIDAR

    def get_rgb_frame(self):
        return self.rgb

    def get_depth_frame(self):
        return self.depth

    def get_confidence_frame(self):
        return self.conf

    def get_intrinsic_mat(self):
        return SimpleNamespace(fx=self.K[0, 0], fy=self.K[1, 1], tx=self.K[0, 2], ty=self.K[1, 2])

    def disconnect(self):
        self.running = False


@pytest.mark.filterwarnings("ignore:test subscriber failed")
def test_grabber_waits_for_a_fresh_frame_and_survives_a_bad_subscriber():
    g = real_cameras.Grabber(Ticker(lambda n: np.full((4, 4, 3), n % 255, np.uint8)), "test")
    try:
        g.subscribe(lambda t, f: 1 / 0)
        seen = []
        g.subscribe(lambda t, f: seen.append(t))
        t0 = g.clock()
        t, frame = g.fresh(0.05)
        assert t > t0 + 0.05 and frame.shape == (4, 4, 3)
        assert len(seen) >= 3 and g.thread.is_alive()
    finally:
        g.close()


def test_grabber_times_out_without_frames():
    g = real_cameras.Grabber(SimpleNamespace(read=lambda: (time.sleep(0.01), (False, None))[1]), "dead")
    try:
        with pytest.raises(real_cameras.CameraError, match="no new frame"):
            g.fresh(0.0, timeout=0.2)
    finally:
        g.close()


def test_depth_upsampling_drops_low_confidence_and_edges():
    depth = np.full((192, 256), 0.6, np.float32)
    conf = np.full((192, 256), 2, np.uint8)
    conf[:, :10] = 0
    depth[100, 100] = np.nan
    up, raw = real_cameras.depth_to_rgb(depth, conf, (1280, 960))
    assert up.shape == (960, 1280) and raw[0, 5] == 0 and raw[100, 100] == 0
    assert up[480, 640] == pytest.approx(0.6) and up[480, 10] == 0


@pytest.fixture(scope="module")
def sim():
    import robot
    import sensors
    import world
    arm = robot.SimArm(world=world.build_world(None))
    phone = sensors.PhoneCamera(arm, seed=1)
    wrist = sensors.WristCamera(arm, seed=2, usb=True)
    yield SimpleNamespace(arm=arm, phone=phone, wrist=wrist, sensors=sensors)
    phone.close()
    wrist.close()


def test_phone_over_record3d_runs_the_survey(sim):
    """The real PhoneCamera on a Record3D-shaped stream solves the desk board and feeds perceive.survey."""
    import perceive
    s, p = sim.sensors, sim.phone
    rgb, _ = p._render(p.fovy_43, p._renderer(s.STILL_RES))  # the 4:3 RGB Record3D sends, at 1920x1440
    _, z = p._render(p.fovy_43)
    raw = p._lidar(z)  # ARKit-style 256x192 depth over the same 4:3 frame
    session = FakeRecord3D(rgb, raw, np.full(raw.shape, 2, np.uint8), s._K(p.fovy_43, *s.STILL_RES))
    phone = real_cameras.PhoneCamera(sim.arm, stream=real_cameras.Record3DSource(session=session))
    try:
        f = phone.capture()
        assert f.rgb.shape == (960, 1280, 3) and f.depth.shape == (960, 1280) and f.raw_depth.shape == (192, 256)
        assert np.allclose(f.K, s._K(p.fovy_43, 1280, 960), atol=1e-6)
        err_mm = np.linalg.norm(f.T_base_cam[:3, 3] - p.true_pose()[:3, 3]) * 1000
        assert err_mm < 10, f"board pose {err_mm:.1f} mm off"
        survey = perceive.survey(sim.arm, f)
        truth = perceive.survey(sim.arm, s.Frame(f.rgb, cv2.resize(z, (1280, 960), interpolation=cv2.INTER_NEAREST),
                                                 f.K, p.true_pose(), 0.0, "phone"))
        assert np.linalg.norm(survey["panel"][:3, 3] - truth["panel"][:3, 3]) < 0.02
    finally:
        phone.close()


def test_continuity_needs_intrinsics(sim):
    phone = real_cameras.PhoneCamera(sim.arm, source="continuity",
                                     stream=Ticker(lambda n: np.zeros((1080, 1920, 3), np.uint8)))
    try:
        with pytest.raises(real_cameras.CameraError, match="calib"):
            phone.capture()
    finally:
        phone.close()


def test_run_video_writes_step_frames_and_mp4(sim, tmp_path):
    from rav_interface import StepTrace
    rgb = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), np.uint8)
    video = real_cameras.RunVideo(tmp_path)
    g = real_cameras.Grabber(Ticker(lambda n: rgb), "wrist")
    try:
        mp4 = video.record(g)
        f = sim.sensors.Frame(rgb, None, np.eye(3), np.eye(4), 0.0, "wrist")
        trace = StepTrace(step="s1", frames=[video.still(f, "s1"), video.on_frame(f)])
        time.sleep(0.2)
    finally:
        g.close()
        video.close()
    assert trace.frames == ["frames/s1_wrist.jpg", "frames/scan_001.jpg"]
    assert all((tmp_path / p).stat().st_size > 0 for p in trace.frames)
    cap = cv2.VideoCapture(str(tmp_path / mp4))
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) >= 5
