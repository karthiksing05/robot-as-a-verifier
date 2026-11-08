"""The real iPhone camera, with the interface of sensors.PhoneCamera, and the run's video. The wrist camera's driver is
real_wrist.py. The pipeline runs on them unchanged.

    phone = PhoneCamera(arm)                          # iPhone on its tripod: Record3D over USB, RGB + LiDAR
    phone = PhoneCamera(arm, source="continuity", calib="phone_cam.json")  # or Continuity: RGB only, no survey
    wrist = real_wrist.WristCamera(arm)               # the USB module under the gripper, undistorted
    video = RunVideo("runs/<id>")                     # stills for StepTrace.frames, scan frames, per-camera mp4s

    scene = rgbperceive.perceive_rgb(arm, phone, wrist, on_frame=video.on_frame)
    plane_T, _ = touch.touch_plane(arm, scene)
    refine = touch.make_refine(wrist, plane_T)        # the last look before each test
    trace.frames.append(video.still(wrist.capture(), step.id))  # a path inside the run folder
    wrist.close(); phone.close(); video.close()

`arm` is anything with the SimArm calls the sim's cameras use: arm.m (the MuJoCo model, for forward kinematics),
arm.qadr and arm.read_q(). real_arm.RealArm has them, so does robot.SimArm. A capture returns a rig.Frame:
rgb (BGR uint8), depth (m, 0 = invalid, or None), K, T_base_cam (arm frame, OpenCV axes), t (time.monotonic(), as
the frame arrived), name, raw_depth.

Each camera is read by a background thread (Grabber) that keeps only the newest frame, so a capture never gets a
stale buffered one: capture() waits for a frame that arrived FRESH_S after the call, which is after the arm settled.
Grabber.subscribe(fn) gets every frame as fn(t, bgr), for a live view: viewer calls must only enqueue.

PhoneCamera's pose comes from the desk board, solved once on the first capture (vision.board_pose), as in the sim:
the tripod doesn't move. Set phone.T_base_cam = None to solve it again after a bump. With Record3D the depth is
ARKit's sceneDepth (256x192 on a LiDAR iPhone) filtered by its confidence map and upsampled to the RGB frame, which
is what perceive.survey reads. Record3D's USB streaming needs the Record3D app on the phone (USB Streaming mode on
in its settings) and `uv sync --extra phone`; record3d has no macOS wheel, so that builds it from source (CMake).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import warnings

import cv2
import numpy as np

from rig import Frame

FRESH_S = 0.1           # a capture uses a frame that arrived this long after the call (Continuity latency is ~2 frames)
CAPTURE_TIMEOUT_S = 2.0
PHONE_RES = (1920, 1080)     # Continuity Camera: 30.0 fps over 10 min at 1080p, worst gap 119 ms (cam_check fps)
MIN_CONFIDENCE = 1      # ARKit depth confidence 0 low, 1 medium, 2 high; lower pixels get depth 0
R3D_LIDAR = 1           # Record3DStream.get_device_type(): 0 is the front TrueDepth camera, 1 the rear LiDAR


class CameraError(RuntimeError):
    pass


def open_capture(index, size, mjpeg=False):
    """cv2.VideoCapture on AVFoundation (macOS) or the default backend, at a requested size. Returns it opened."""
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        raise CameraError(f"camera {index} didn't open. Check the index (tools/cam_check.py list) and the Camera "
                          "permission for your terminal in System Settings > Privacy & Security > Camera.")
    if mjpeg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
    return cap


class Grabber:
    """Reads a source on its own thread and keeps the newest frame. read() -> (ok, frame), as cv2.VideoCapture."""

    def __init__(self, source, name, clock=time.monotonic):
        self.source, self.name, self.clock = source, name, clock
        self.cond = threading.Condition()
        self.frame, self.t, self.count, self.failures = None, 0.0, 0, 0
        self.subscribers = []
        self.running = True
        self.thread = threading.Thread(target=self._run, name=f"grab-{name}", daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            ok, frame = self.source.read()
            if not ok or frame is None:
                self.failures += 1
                time.sleep(0.005)
                continue
            t = self.clock()
            with self.cond:
                self.frame, self.t = frame, t
                self.count += 1
                self.cond.notify_all()
            for fn in list(self.subscribers):
                try:
                    fn(t, frame)
                except Exception as e:  # a viewer must never stop the camera
                    warnings.warn(f"{self.name} subscriber failed: {e!r}")

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return fn

    def latest(self):
        """(t, frame) of the newest frame, or (0.0, None) before the first."""
        with self.cond:
            return self.t, self.frame

    def wait(self, after, timeout=CAPTURE_TIMEOUT_S):
        """(t, frame) of the first frame that arrived after `after` (clock time)."""
        end = self.clock() + timeout
        with self.cond:
            while self.frame is None or self.t <= after:
                left = end - self.clock()
                if left <= 0 or not self.running:
                    raise CameraError(f"{self.name}: no new frame in {timeout:.1f} s "
                                      f"({self.count} frames, {self.failures} failed reads so far)")
                self.cond.wait(left)
            return self.t, self.frame

    def fresh(self, fresh_s=FRESH_S, timeout=CAPTURE_TIMEOUT_S):
        return self.wait(self.clock() + fresh_s, timeout + fresh_s)

    def close(self):
        self.running = False
        self.thread.join(timeout=1.0)
        release = getattr(self.source, "release", None)
        if release:
            release()


def load_calibration(path):
    """A camera calibration file: {"size": [w, h], "K": 3x3, "dist": [5], "rms_px", "T_err": 4x4 (optional)}."""
    with open(path) as f:
        c = json.load(f)
    return (np.array(c["K"], float), np.array(c["dist"], float), tuple(c["size"]),
            np.array(c.get("T_err", np.eye(4)), float))


def save_calibration(path, K, dist, size, rms_px, T_err=None, **extra):
    c = {"size": list(size), "K": np.asarray(K).tolist(), "dist": np.asarray(dist).ravel().tolist(),
         "rms_px": float(rms_px), **extra}
    if T_err is not None:
        c["T_err"] = np.asarray(T_err).tolist()
    with open(path, "w") as f:
        json.dump(c, f, indent=2)


class Record3DSource:
    """The iPhone over USB through Record3D: read() -> (ok, (bgr, depth_m, confidence, K)), as Grabber wants."""

    def __init__(self, device=0, session=None):
        self.event = threading.Event()
        self.stopped = False
        if session is None:
            from record3d import Record3DStream  # uv sync --extra phone
            devs = Record3DStream.get_connected_devices()
            if len(devs) <= device:
                raise CameraError(f"Record3D: {len(devs)} device(s) found. Plug the iPhone in by USB, open Record3D, "
                                  "turn on USB Streaming in its settings and press record.")
            session = Record3DStream()
            session.on_new_frame = self.event.set
            session.on_stream_stopped = self._stopped
            session.connect(devs[device])
        else:
            session.on_new_frame = self.event.set
        self.session = session
        self.lidar = session.get_device_type() == R3D_LIDAR

    def _stopped(self):
        self.stopped = True
        self.event.set()

    def read(self):
        if not self.event.wait(1.0) or self.stopped:
            return False, None
        self.event.clear()
        s = self.session
        rgb = np.ascontiguousarray(s.get_rgb_frame())
        depth = np.array(s.get_depth_frame(), np.float32)
        conf = np.array(s.get_confidence_frame())
        c = s.get_intrinsic_mat()
        K = np.array([[c.fx, 0, c.tx], [0, c.fy, c.ty], [0, 0, 1]], float)
        return True, (cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), depth, conf, K)

    def release(self):
        self.stopped = True
        try:
            self.session.disconnect()
        except Exception:
            pass


def depth_to_rgb(depth, conf, size, min_conf=MIN_CONFIDENCE):
    """ARKit's depth map, low-confidence pixels zeroed, bilinear up to the RGB size; 0 next to missing pixels."""
    d = np.where(np.isfinite(depth) & (depth > 0), depth, 0).astype(np.float32)
    if conf is not None and conf.size and conf.shape == d.shape:
        d[conf < min_conf] = 0
    up = cv2.resize(d, size, interpolation=cv2.INTER_LINEAR)
    ok = cv2.resize((d > 0).astype(np.float32), size, interpolation=cv2.INTER_LINEAR) > 0.999
    return np.where(ok, up, 0).astype(np.float32), d


class PhoneCamera:
    """The iPhone on its tripod: a real sensors.PhoneCamera. source "record3d" (RGB + LiDAR, USB) or "continuity" (RGB).

    width: the RGB frame is scaled to this width (K scaled with it) after the board pose is solved at full size, as
    the sim solves on a still and works on 1280-wide video. raw_K is the native depth map's intrinsics."""

    def __init__(self, arm, source="record3d", index=0, device=0, width=1280, min_conf=MIN_CONFIDENCE,
                 calib=None, board_pose=None, stream=None, fresh_s=FRESH_S):
        self.arm, self.kind, self.width, self.min_conf, self.fresh_s = arm, source, width, min_conf, fresh_s
        if board_pose is None:
            import vision
            board_pose = lambda gray, K: vision.board_pose(gray, K)[0]  # noqa: E731
        self.board_pose = board_pose
        if source == "record3d":
            stream = stream or Record3DSource(device)
            if not stream.lidar:
                warnings.warn("Record3D is streaming the front TrueDepth camera, not the rear LiDAR")
        elif source == "continuity":
            stream = stream or open_capture(index, PHONE_RES)
        else:
            raise ValueError(f"source must be 'record3d' or 'continuity', not {source!r}")
        # Continuity frames carry no intrinsics: they come from cam_check.py calibrate --out phone_cam.json
        self.K_native = load_calibration(calib)[0] if calib else None
        self.grab = Grabber(stream, "phone")
        self.T_base_cam, self.K, self.raw_K = None, None, None

    def _unpack(self, item):
        if self.kind == "record3d":
            return item
        if self.K_native is None:
            raise CameraError("Continuity Camera frames carry no intrinsics: pass calib= (tools/cam_check.py "
                              f"calibrate at {PHONE_RES[0]}x{PHONE_RES[1]}), or use Record3D")
        return item, None, None, self.K_native

    def capture(self):
        t, item = self.grab.fresh(self.fresh_s)
        bgr, depth, conf, K = self._unpack(item)
        if self.T_base_cam is None:  # the tripod doesn't move: solve the board once, at full resolution
            self.T_base_cam = self.board_pose(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), K)
        s = self.width / bgr.shape[1]
        size = (self.width, round(bgr.shape[0] * s))
        self.K = np.diag([s, s, 1.0]) @ K
        self.K[:2, 2] = (K[:2, 2] + 0.5) * s - 0.5  # pixel centres at whole numbers, as sensors._K
        rgb = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA) if s != 1 else bgr
        if depth is None:
            return Frame(rgb, None, self.K, self.T_base_cam, t, "phone")
        up, raw = depth_to_rgb(depth, conf, size, self.min_conf)
        r = raw.shape[1] / bgr.shape[1]
        self.raw_K = np.diag([r, r, 1.0]) @ K
        self.raw_K[:2, 2] = (K[:2, 2] + 0.5) * r - 0.5
        return Frame(rgb, up, self.K, self.T_base_cam, t, "phone", raw)

    def close(self):
        self.grab.close()


class RunVideo:
    """What the cameras leave in a run folder: frames/<step>_<camera>.jpg for StepTrace.frames, frames/scan_NNN.jpg
    from perceive_rgb's on_frame, and video/<camera>.mp4 from record(grabber)."""

    def __init__(self, run_dir, jpeg_quality=90):
        self.run_dir, self.q = str(run_dir), jpeg_quality
        os.makedirs(os.path.join(self.run_dir, "frames"), exist_ok=True)
        self.scan_n, self.writers, self.lock, self.closed = 0, {}, threading.Lock(), False

    def _save(self, name, bgr):
        rel = os.path.join("frames", name)
        cv2.imwrite(os.path.join(self.run_dir, rel), bgr, [cv2.IMWRITE_JPEG_QUALITY, self.q])
        return rel

    def still(self, frame, step_id, tag=None):
        """Save a Frame as evidence for one step. Returns the path inside the run folder, for StepTrace.frames."""
        return self._save(f"{step_id}_{tag or frame.name}.jpg", frame.rgb)

    def on_frame(self, frame, cloud=None):
        """perceive_rgb(..., on_frame=video.on_frame): keeps every scan frame."""
        self.scan_n += 1
        return self._save(f"scan_{self.scan_n:03d}.jpg", frame.rgb)

    def record(self, grabber, fps=30.0, name=None):
        """Write every frame the grabber gets to video/<name>.mp4, until close()."""
        name = name or grabber.name
        os.makedirs(os.path.join(self.run_dir, "video"), exist_ok=True)
        path = os.path.join(self.run_dir, "video", f"{name}.mp4")

        def write(t, item):
            bgr = item[0] if isinstance(item, tuple) else item
            with self.lock:
                if self.closed:
                    return
                w = self.writers.get(name)
                if w is None:
                    w = self.writers[name] = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, bgr.shape[1::-1])
                w.write(bgr)

        grabber.subscribe(write)
        return os.path.relpath(path, self.run_dir)

    def close(self):
        with self.lock:
            self.closed = True
            for w in self.writers.values():
                w.release()
            self.writers.clear()
