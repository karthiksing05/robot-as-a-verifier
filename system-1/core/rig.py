"""The rig: everything the pipeline needs from the world, and what the sim and the real arm share.

A Rig is an arm and its cameras, with the calls listed by the Arm, Camera and Readout protocols below. The pipeline
takes a Rig and never builds one: the sim builds one from its simulated arm and cameras, and the real arm from its
drivers, so swapping the rig is the only change between them. Also here: the SO-101's model, limits and IK, the safety
stop, the desk's height, the force estimate both arms run on their servo readings, and the camera frame with its
geometry.
"""
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cv2
import mujoco
import numpy as np

# The arm's model file. It stays with the sim's assets: the scenes the sim generates include it by relative path.
ARM_XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sim", "assets", "so101",
                       "so101_new_calib.xml")
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
IK_JOINTS = 4  # wrist_roll spins about the tool axis, so it can't help point the probe

CONTROL_HZ = 50
MAX_STEP_RAD = 0.06        # per control tick, like LeRobot's max_relative_target
HARD_FORCE_CAP_N = 15.0    # never crossed, in any mode
WORKSPACE = np.array([[0.05, 0.42], [-0.25, 0.25], [-0.12, 0.35]])
CONTACT_N = 0.3            # tip force that counts as touching
IK_SEEDS = [np.array(s, float) for s in
            ([0, -1.0, 0.9, 0.9, 0], [0, -1.4, 1.4, 0.6, 0], [0, -0.4, 0.4, 1.2, 0], [0, -1.6, 0.6, 1.4, 0])]
TICK_RAD = 2 * np.pi / 4096
# The desk in the arm frame: the sim's arm stands on a 140 mm post. Perception takes the desk as this plane (the survey
# box, the scan's crop) and the sim builds its desk here. An arm's table_z, workspace and standoff default to these.
TABLE_Z = -0.14
STANDOFF = 0.12            # wrist camera to panel in the scan's views (m): the fingertip then clears the panel by a few cm
# The force estimate from the servos' own readings, as SimArm(sensing=...) and RealArm both run it. robot.py has the
# sim's servo model and its noise.
SERVO_KV = 1.0             # servo damping (N.m.s/rad). The model file's was tuned for its stiff servo, so it is lowered
SENSE_AVG = 5              # samples averaged for tip_force(); the newest is left out, as one sample of bus latency
CAP_AVG = 1                # and for the hard cap, which must see short impacts
DEADBAND_EST_TICKS = 1     # the dead zone the rig believes (register default); the sim's servo ignores 5
TARE_S = 0.2               # tare() zeroes the estimate on this much of the latest readings
SENSED_NOISE_N = 2.5       # with sensing, skills keep contact thresholds above this (arm.noise_n), in the estimate's units


class SafetyStop(Exception):
    pass


@runtime_checkable
class Readout(Protocol):
    """The device's readout, which every verdict reads: the sim's device.DeviceMCU, or real_arm.OperatorReadout."""
    readings: dict  # {channel: value}. affordances reads it mid-step, so it should follow the device as it changes
    events: list    # [(time, channel, value)]
    lcd: object     # the display's text, or None


@runtime_checkable
class Arm(Protocol):
    """What the pipeline reads and calls on an arm: robot.SimArm and real_arm.RealArm have it. Joint angles are radians
    in the model's frame, positions metres in the arm frame, forces newtons."""
    m: mujoco.MjModel       # the SO-101's model, for kinematics
    d: mujoco.MjData        # the pipeline reads only d.time, the clock (s)
    ik: "IK"
    qadr: np.ndarray        # the arm joints' qpos addresses in m
    home_q: np.ndarray      # joint angles of the home pose
    arm_bodies: set         # the arm's body ids, cropped out of what the cameras see
    cmd: np.ndarray         # the joint command, as send() last clipped it
    status: str             # what the arm is doing, for logs and the operator
    sensing: object         # None with the sim's perfect sensor, else "current", "tactile" or "loadcell"
    axial_sensor: bool      # a pad or load cell reads the force along the probe
    noise_n: float          # force the estimate can't tell from noise
    noise_axial: float      # the same along the probe
    force_log: list         # (t, force) per tick
    seen_collisions: set    # arm parts that touched the scene (always empty on the real arm)
    app: Readout
    table_z: float          # the desk's height (m)
    workspace: np.ndarray   # 3x2 box (m) that check_workspace allows
    standoff: float         # wrist camera to panel in the scan's views (m)
    stall_m: float          # None, or guarded moves take contact as the pad stalling this far (m), not the force estimate
    guard_speed: float      # guarded moves run at least this fast (m/s)

    def read_q(self):
        """Joint readings."""

    def send(self, q):
        """Command joint angles, clipped to the limits and to MAX_STEP_RAD."""

    def tick(self):
        """One control tick: returns the tip force, and raises SafetyStop over HARD_FORCE_CAP_N."""

    def tip_pose(self):
        """(tip position, probe axis) from the joint readings."""

    def tip_force(self):
        """Force along the probe."""

    def tip_force_vec(self):
        """Force on the probe, arm frame."""

    def tare(self, on=True):
        """Zero the force estimate, or with on=False drop the zero."""

    def check_workspace(self, pos):
        """Raise SafetyStop if pos is outside workspace."""


@runtime_checkable
class Camera(Protocol):
    """A camera on the rig: the sim's sensors.WristCamera and PhoneCamera, or real_wrist.WristCamera."""
    K: np.ndarray  # 3x3 intrinsics of its frames

    def capture(self):
        """A Frame, with the camera pose the controller believes."""

    def close(self):
        """Release the camera."""


@dataclass
class Rig:
    """The arm and its cameras: everything the pipeline needs from the world."""
    arm: Arm
    wrist: Camera            # on the gripper: the survey, the scan and the last looks
    phone: Camera = None     # the depth route's survey camera; the RGB route surveys with the wrist
    name: str = ""           # what the rig is, for logs

    def close(self):
        """Close the cameras, then the arm if it has a close() (the real arm's turns torque off)."""
        for cam in (self.phone, self.wrist):
            if cam is not None:
                cam.close()
        if hasattr(self.arm, "close"):
            self.arm.close()


class IK:
    """Damped least squares on a private MjData, so solving never disturbs the sim."""

    def __init__(self, model):
        self.m = model
        self.d = mujoco.MjData(model)
        self.tip = model.site("tip").id
        self.qadr = np.array([model.joint(j).qposadr[0] for j in ARM_JOINTS])
        self.dadr = np.array([model.joint(j).dofadr[0] for j in ARM_JOINTS])
        self.lo = model.jnt_range[[model.joint(j).id for j in ARM_JOINTS], 0]
        self.hi = model.jnt_range[[model.joint(j).id for j in ARM_JOINTS], 1]

    def fk(self, q, site=None):
        """Position and pointing axis (the site's -z) of the tip, or of another site."""
        site = self.tip if site is None else site
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        R = self.d.site_xmat[site].reshape(3, 3)
        return self.d.site_xpos[site].copy(), -R[:, 2].copy()

    def solve(self, pos, axis, q0, iters=200, tol=5e-4, site=None):
        """Tip at `pos` (primary), probe pointing along `axis` as well as the nullspace allows.
        `site` (an id) aims another site instead, e.g. the wrist camera.

        Returns (q, ok, pos_err_m, axis_err_deg).
        """
        axis = np.asarray(axis, float) / np.linalg.norm(axis)
        best = None
        for seed in [q0, *IK_SEEDS]:
            q = self._iterate(np.array(seed, float), pos, axis, iters, tol, site)
            p, a = self.fk(q, site)
            err = np.linalg.norm(p - pos)
            ang = np.degrees(np.arccos(np.clip(a @ axis, -1, 1)))
            if best is None or err < best[2] - 1e-4 or (abs(err - best[2]) < 1e-4 and ang < best[3]):
                best = (q, err < 1e-3, err, ang)
            if err < tol and ang < 15:
                break
        return best

    def _iterate(self, q, pos, axis, iters, tol, site=None):
        jacp = np.zeros((3, self.m.nv))
        jacr = np.zeros((3, self.m.nv))
        n = IK_JOINTS
        lam = 1e-2
        for _ in range(iters):
            p, a = self.fk(q, site)
            mujoco.mj_comPos(self.m, self.d)
            mujoco.mj_jacSite(self.m, self.d, jacp, jacr, self.tip if site is None else site)
            Jp = jacp[:, self.dadr[:n]]
            # d(axis)/dq = w x axis, so the axis Jacobian is -[axis]x @ Jr
            Ja = -np.cross(a, jacr[:, self.dadr[:n]].T).T
            ep = pos - p
            ea = axis - a
            Jp_pinv = Jp.T @ np.linalg.inv(Jp @ Jp.T + lam**2 * np.eye(3))
            dq1 = Jp_pinv @ ep
            N = np.eye(n) - Jp_pinv @ Jp
            JaN = Ja @ N
            dq2 = JaN.T @ np.linalg.inv(JaN @ JaN.T + 1e-2 * np.eye(3)) @ (ea - Ja @ dq1)
            dq = dq1 + N @ dq2
            dq = np.clip(dq, -0.2, 0.2)
            q[:n] = np.clip(q[:n] + dq, self.lo[:n], self.hi[:n])
            if np.linalg.norm(ep) < tol * 0.2 and np.linalg.norm(dq) < 1e-5:
                break
        return q


def arm_bodies(m):
    """Ids of the arm's bodies: its base and everything under it."""
    root = m.body("base").id

    def under(b):
        while b > 0:
            if b == root:
                return True
            b = m.body_parentid[b]
        return False

    return {b for b in range(m.nbody) if under(b)}


class ArmBase:
    """What SimArm and RealArm share: the force estimate's least-squares fit and its part along the probe, the force
    vector it gives (with a pad or load cell, axial_sensor, their reading along the probe), and the workspace check.
    The arm keeps W, zero, axis_est and est_vec up to date, and has axial_sensor and tip_force()."""
    table_z, workspace, standoff = TABLE_Z, WORKSPACE, STANDOFF
    stall_m, guard_speed = None, 0.0  # see affordances._guarded
    view_tilts = None  # radians, perceive.plan_views' tilts when set (default perceive.VIEW_TILTS)
    view_tol = None  # m: rgbperceive._settle re-commands a view until the camera is this close (default SAG_TOL)
    view_looks = None  # (down, left) offsets on the panel for plan_views' views (default perceive.VIEW_LOOKS, a 3x3 grid)

    def _fit(self, tau, zero=None):
        # 5 joint torques, 3 force components: least squares (wrist_roll turns about the probe, so carries none). A fit
        # along the probe alone let the force across it leak in, as the arm can't always point the probe along a normal.
        return np.linalg.lstsq(self.W, tau - (self.zero if zero is None else zero), rcond=None)[0]

    def _axial(self, F):
        return max(-float(F @ self.axis_est), 0.0)  # along the probe; a push reads positive

    def tip_force_vec(self):
        """The force on the probe from the estimate, arm frame (N)."""
        if self.axial_sensor:  # the pad's or load cell's reading along the probe, the servo estimate across it
            a = self.axis_est
            return self.est_vec - (self.est_vec @ a) * a - self.tip_force() * a
        return self.est_vec.copy()

    def check_workspace(self, pos):
        if np.any(pos < self.workspace[:, 0]) or np.any(pos > self.workspace[:, 1]):
            raise SafetyStop(f"target {np.round(pos, 3).tolist()} is outside the workspace box")


@dataclass
class Frame:
    rgb: np.ndarray         # HxWx3 uint8, BGR
    depth: np.ndarray       # HxW float32, metres along the optical axis, 0 where invalid; or None
    K: np.ndarray           # 3x3 intrinsics of rgb and depth
    T_base_cam: np.ndarray  # 4x4 camera pose in the arm frame, OpenCV axes, as the controller believes it
    t: float                # sim time (s)
    name: str
    raw_depth: np.ndarray = None  # phone only: the LiDAR's native 256x192 map, full 4:3 frame,
                                  # intrinsics: focal length K[0, 0] / 5, centre (127.5, 95.5)


def _cv_pose(data, cam):
    """4x4 camera pose with OpenCV axes. A MuJoCo camera looks along its -z with +y up."""
    T = np.eye(4)
    T[:3, :3] = data.cam_xmat[cam].reshape(3, 3) @ np.diag([1.0, -1.0, -1.0])
    T[:3, 3] = data.cam_xpos[cam]
    return T


def backproject(frame, stride=1):
    """Valid depth pixels as arm-frame points: (Nx3 points, Nx3 RGB uint8, Nx2 pixel (u, v))."""
    h, w = frame.depth.shape
    v, u = np.mgrid[0:h:stride, 0:w:stride]
    z = frame.depth[v, u]
    ok = z > 0
    u, v, z = u[ok], v[ok], z[ok]
    K, T = frame.K, frame.T_base_cam
    p = np.c_[(u - K[0, 2]) / K[0, 0] * z, (v - K[1, 2]) / K[1, 1] * z, z]
    return p @ T[:3, :3].T + T[:3, 3], frame.rgb[v, u, ::-1], np.c_[u, v]


def normals(frame, sigma_px=2.0):
    """Unit surface normals in the arm frame (HxWx3, facing the camera), 0 where depth is missing.
    Depth is first smoothed over valid pixels (sigma_px), or noise swamps per-pixel normals."""
    valid = (frame.depth > 0).astype(np.float32)
    wsum = cv2.GaussianBlur(valid, (0, 0), sigma_px)
    z = cv2.GaussianBlur(frame.depth, (0, 0), sigma_px) / np.maximum(wsum, 1e-6)
    h, w = z.shape
    v, u = np.mgrid[0:h, 0:w]
    K = frame.K
    P = np.dstack([(u - K[0, 2]) / K[0, 0] * z, (v - K[1, 2]) / K[1, 1] * z, z])
    du, dv = np.zeros_like(P), np.zeros_like(P)
    du[:, 1:-1] = P[:, 2:] - P[:, :-2]
    dv[1:-1] = P[2:] - P[:-2]
    n = np.cross(dv, du)  # toward the camera for a surface facing it
    n[(wsum < 0.9) | (valid == 0)] = 0
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-12)
    return n @ frame.T_base_cam[:3, :3].T
