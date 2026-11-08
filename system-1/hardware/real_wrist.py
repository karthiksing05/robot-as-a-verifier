"""The real wrist camera, an Innomaker U20CAM-1080P, with sensors.WristCamera(usb=True)'s interface.

    wrist = WristCamera(arm)        # arm: real_arm.RealArm or robot.SimArm (anything with m, qadr and read_q())
    frame = wrist.capture()         # rig.Frame: undistorted BGR, depth None, K, T_base_cam
    wrist.close()

Frames come through ffmpeg's DirectShow input, by the camera's name, as the module's own MJPEG at 30 fps. That makes
this Windows only. OpenCV's DirectShow backend can't switch this module to MJPEG and gets uncompressed frames at
10 fps. A background thread keeps the newest frame, and capture() waits for one that started after the call, so it
never returns a frame taken while the arm was still moving. It captures at 1920x1080 unless told otherwise.

Each frame is undistorted with the ChArUco calibration (system-1/arm/camera/camera_out/calib.json, from
camera_test.py calib), scaled to the capture size, so it is a pinhole image that claims K, as the sim's frames do.
The pose is forward kinematics of the joint readings at the model's wrist_cam, times T_hand_eye from HAND_EYE, which
tools/hand_eye.py writes (identity until the mount is measured). On the SO-101 that pose is only good to about a
degree, too coarse for the plane sweep, which needs each photo's pose to about 0.1 deg (system-1/arm/camera/results.md).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import cv2
import mujoco
import numpy as np

from rig import Frame, _cv_pose

HERE = os.path.dirname(os.path.abspath(__file__))
CALIB = os.path.join(HERE, "..", "arm", "camera", "camera_out", "calib.json")
HAND_EYE = os.path.join(os.path.dirname(CALIB), "hand_eye.json")
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
NOT_IT = ("integrated", "pixel", "obs", "virtual")  # the laptop's own camera, a phone's, virtual ones
SIZE = (1920, 1080)
TIMEOUT_S = 8.0
STILL_DIFF = 2.0  # grey levels, mean over a frame at 1/8 size: two frames in a row this close, and the camera has stopped
STILL_S = 1.0     # waiting that long for it


class CameraError(RuntimeError):
    pass


def find_camera():
    """(DirectShow index, name) of the first camera that isn't the laptop's own or a virtual one."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                         capture_output=True, text=True, errors="ignore").stderr
    names = re.findall(r'"([^"]+)" \(video\)', out)
    for i, n in enumerate(names):
        if not any(k in n.lower() for k in NOT_IT):
            return i, n
    raise CameraError(f"No USB camera found among {names}. Is it plugged in, and is no other app using it?")


class Capture:
    """The camera's MJPEG stream through ffmpeg. read() returns the newest frame and how many have arrived."""

    def __init__(self, size=SIZE):
        self.size = tuple(size)
        _, self.name = find_camera()
        self.proc = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "dshow", "-rtbufsize", "64M",
                                      "-vcodec", "mjpeg", "-video_size", f"{size[0]}x{size[1]}", "-framerate", "30",
                                      "-i", f"video={self.name}", "-c:v", "copy", "-f", "image2pipe", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.jpeg, self.count, self.lock = None, 0, threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()
        t0 = time.time()
        while self.jpeg is None:
            if time.time() - t0 > TIMEOUT_S:
                err = self.proc.stderr.read().decode(errors="ignore") if self.proc.poll() is not None else ""
                self.close()
                raise CameraError(f"No frames from '{self.name}'. Is another app using it? {err}")
            time.sleep(0.05)

    def _pump(self):
        buf = b""
        while True:
            chunk = self.proc.stdout.read(65536)
            if not chunk:
                return
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2)
                if s < 0 or e < 0:
                    break
                with self.lock:
                    self.jpeg, self.count = buf[s:e + 2], self.count + 1
                buf = buf[e + 2:]

    def read(self):
        with self.lock:
            data, n = self.jpeg, self.count
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), n

    def close(self):
        self.proc.kill()


def load_calib(width, path=CALIB):
    """K and distortion from calib.json, scaled to images of this width. The camera's modes are one view at
    different scales, so the focal length and centre scale and the distortion coefficients don't."""
    c = json.load(open(path))
    K = np.array(c["K"], float)
    K[:2] *= width / c["size"][0]
    return K, np.array(c["dist"], float)


def move_mount(m, path=HAND_EYE):
    """Moves model m's wrist_cam camera and site to the mount tools/hand_eye.py measured, so IK aims the real camera
    and forward kinematics give its pose. A WristCamera on m then takes T_hand_eye=np.eye(4). No hand_eye.json, no
    change. Returns whether it moved them."""
    if not os.path.exists(path):
        print(f"No {os.path.normpath(path)}, so the wrist camera mount is the model's")
        return False
    T = np.asarray(json.load(open(path))["T_hand_eye"], float)
    cam, site = m.camera("wrist_cam").id, m.site("wrist_cam").id
    F = np.diag([1.0, -1.0, -1.0])  # OpenCV axes from MuJoCo's camera axes
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, m.cam_quat[cam])
    R = R.reshape(3, 3) @ F
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, (R @ T[:3, :3] @ F).ravel())
    m.cam_pos[cam] = m.site_pos[site] = m.cam_pos[cam] + R @ T[:3, 3]
    m.cam_quat[cam] = m.site_quat[site] = quat
    m.site_sameframe[site] = 0  # the compiler marked the site as at its body's origin, and kinematics would skip it
    print(f"Wrist camera mount from {os.path.normpath(path)}")
    return True


class WristCamera:
    """The real wrist camera, with the calls the pipeline makes on sensors.WristCamera: capture(), K and close()."""

    def __init__(self, arm, size=SIZE, calib=CALIB, T_hand_eye=None):
        self.arm, self.m = arm, arm.m
        self.cam = arm.m.camera("wrist_cam").id
        self.fk = mujoco.MjData(self.m)
        if T_hand_eye is None:
            found = os.path.exists(HAND_EYE)
            T_hand_eye = json.load(open(HAND_EYE))["T_hand_eye"] if found else np.eye(4)
            print(f"WristCamera: mount from {os.path.normpath(HAND_EYE)}" if found else
                  f"WristCamera: no {os.path.normpath(HAND_EYE)}, so the mount is the model's")
        self.T_hand_eye = np.asarray(T_hand_eye, float)
        self.K, dist = load_calib(size[0], calib)
        self.maps = cv2.initUndistortRectifyMap(self.K, dist, None, self.K, tuple(size), cv2.CV_16SC2)
        self.grab = Capture(size)

    def believed_pose(self):
        """Camera pose (4x4, arm frame, OpenCV axes) from forward kinematics of the joint readings."""
        self.fk.qpos[self.arm.qadr] = self.arm.read_q()
        mujoco.mj_kinematics(self.m, self.fk)
        mujoco.mj_camlight(self.m, self.fk)
        return _cv_pose(self.fk, self.cam) @ self.T_hand_eye

    def capture(self):
        """The first frame that started after this call and matches the one before it (the arm has stopped shaking: it
        shook on arriving at the scan's views), undistorted, with the pose read then. After STILL_S it takes the newest
        frame and says so."""
        _, n0 = self.grab.read()
        t0, seen, before = time.monotonic(), n0, None
        while True:  # the frame arriving next may have started before the call, so wait for the one after it
            bgr, n = self.grab.read()
            if n != seen and n >= n0 + 2:
                seen = n
                small = cv2.cvtColor(cv2.resize(bgr, None, fx=0.125, fy=0.125), cv2.COLOR_BGR2GRAY).astype(np.float32)
                diff = None if before is None else float(np.abs(small - before).mean())
                if diff is not None and diff < STILL_DIFF:
                    break
                if diff is not None and time.monotonic() - t0 > STILL_S:
                    print(f"WristCamera: still moving after {STILL_S:.0f} s (frames differ by {diff:.1f}): using the newest")
                    break
                before = small
            if time.monotonic() - t0 > TIMEOUT_S:
                raise CameraError(f"'{self.grab.name}' stopped sending frames")
            time.sleep(0.002)
        if hasattr(self.arm, "_read"):  # RealArm: the joints now, so the pose is the frame's
            self.arm._read()
        return Frame(cv2.remap(bgr, *self.maps, cv2.INTER_LINEAR), None, self.K, self.believed_pose(), time.monotonic(),
                     "wrist")

    def close(self):
        self.grab.close()
