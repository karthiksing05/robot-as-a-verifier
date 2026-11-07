"""The real wrist camera, an Innomaker U20CAM-1080P, with sensors.WristCamera(usb=True)'s interface.

    wrist = WristCamera(arm)        # arm: real_arm.RealArm or robot.SimArm (anything with m, qadr and read_q())
    frame = wrist.capture()         # sensors.Frame: undistorted BGR, depth None, K, T_base_cam
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
        """The first frame that started after this call, undistorted, with the pose read at the call."""
        T = self.believed_pose()
        _, n0 = self.grab.read()
        t0 = time.monotonic()
        while True:  # the frame arriving next may have started before the call, so wait for the one after it
            bgr, n = self.grab.read()
            if n >= n0 + 2:
                break
            if time.monotonic() - t0 > TIMEOUT_S:
                raise CameraError(f"'{self.grab.name}' stopped sending frames")
            time.sleep(0.002)
        return Frame(cv2.remap(bgr, *self.maps, cv2.INTER_LINEAR), None, self.K, T, time.monotonic(), "wrist")

    def close(self):
        self.grab.close()
