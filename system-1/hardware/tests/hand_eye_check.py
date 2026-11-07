"""A one-off check of tools/hand_eye.py on the sim, about 2 minutes, so not in test_real_arm.py (whose
test_hand_eye_solve_finds_a_moved_camera checks the solver alone). The sim's USB wrist camera, with its lens, noise and
MJPEG, renders from a wrist_cam turned 1 deg and moved 2 mm. RealArm reads the joints through tests/fake_bus.py, as
encoder steps, and hand_eye.main runs as it would on the real arm. The same views are then solved again with joint
offsets added to the readings, as the arm would read them with real_arm.OFFSET_RAD wrong.

    python tests/hand_eye_check.py         # from system-1/hardware
"""
import os
import sys
import tempfile
import types

import cv2
import mujoco
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE, os.path.join(os.path.dirname(HERE), "tools")] + [
    os.path.join(HERE, "..", "..", d) for d in ("core", "sim")]
import appliance  # noqa: E402
import rig  # noqa: E402
import vision  # noqa: E402

_axis = np.array([1.0, 2.0, -1.0]) / np.sqrt(6)
T_MOUNT = vision._T(cv2.Rodrigues(_axis * np.radians(1.0))[0], 0.002 * _axis)  # the camera's move, in its own frame


def clean_arm():
    """The model as RealArm loads it, with the nominal wrist_cam: what hand_eye.fk needs (m and qadr)."""
    m = mujoco.MjModel.from_xml_path(rig.ARM_XML)
    return types.SimpleNamespace(m=m, qadr=rig.IK(m).qadr)


def board_poses(arm, K, size, n, rng):
    """n poses a person might hold: a view straight down on the board from 22 cm, every joint turned at random, with at
    least 18 of the board's 24 corners in frame."""
    import hand_eye
    ik = rig.IK(arm.m)
    home, *_ = ik.solve(np.array([0.2, 0.0, 0.14]), np.array([0.7, 0, -0.7]), np.zeros(5))
    q_c, *_ = ik.solve(appliance.BOARD_CENTER + [0, 0, 0.22], [0, 0, -1], home, site=arm.m.site("wrist_cam").id)
    corners = vision.T_BASE_BOARD @ np.c_[vision.BOARD.getChessboardCorners(), np.ones(24)].T
    poses = []
    while len(poses) < n:
        q = np.clip(q_c + rng.normal(0, [0.3, 0.2, 0.2, 0.4, 0.8]), ik.lo, ik.hi)
        p = (np.linalg.inv(hand_eye.fk(arm, q)) @ corners)[:3]
        u, v = (K @ (p / p[2]))[:2]
        if ((p[2] > 0.12) & (u > 20) & (u < size[0] - 20) & (v > 20) & (v < size[1] - 20)).sum() >= 18:
            poses.append(q)
    return poses


def off_by(T, T_true):
    """(deg, mm) between two poses."""
    D = np.linalg.inv(T_true) @ T
    return np.degrees(np.linalg.norm(cv2.Rodrigues(D[:3, :3])[0])), np.linalg.norm(D[:3, 3]) * 1000


def main():
    import fake_bus
    import hand_eye
    import robot
    import sensors
    import world
    sim = robot.SimArm(world=world.build_world(None))
    cam, F = sim.m.camera("wrist_cam").id, np.diag([1.0, -1.0, -1.0])  # F: MuJoCo's camera axes to OpenCV's
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, sim.m.cam_quat[cam])
    R = R.reshape(3, 3)
    sim.m.cam_pos[cam] += R @ F @ T_MOUNT[:3, 3]
    mujoco.mju_mat2Quat(sim.m.cam_quat[cam], (R @ F @ T_MOUNT[:3, :3] @ F).ravel())
    wrist = sensors.WristCamera(sim, usb=True)
    arm, rng = clean_arm(), np.random.default_rng(0)
    poses = board_poses(arm, wrist.K, sensors.USB_RES, 40, rng)

    def ask(prompt):  # the person: poses the limp arm at each view
        if prompt.startswith("View"):
            sim.d.qpos[sim.qadr] = poses.pop()
            mujoco.mj_forward(sim.m, sim.d)
        return ""
    tmp = tempfile.mkdtemp()
    X, views = hand_eye.main(["FAKE", "cal.json", "--out", os.path.join(tmp, "hand_eye.json")],
                             bus=fake_bus.make(sim, tmp), ask=ask, camera=lambda _: wrist)
    print("Found the mount to within %.3f deg and %.2f mm.\n" % off_by(X, T_MOUNT))
    held = board_poses(arm, wrist.K, sensors.USB_RES, 200, rng)
    print("joint offsets (deg)      mount off by    px rms   board off by     photo poses off by (median of 200)")
    J = np.eye(5)
    for name, off in [("none", np.zeros(5))] + [(f"{j} +0.5", 0.5 * J[i]) for i, j in enumerate(rig.ARM_JOINTS)] + [
            ("elbow_flex +2", 2 * J[2]), ("all five within 2", np.random.default_rng(3).uniform(-2, 2, 5))]:
        off = np.radians(off)
        X, T_board, rms = hand_eye.solve([dict(v, hand=hand_eye.fk(arm, v["q"] + off)) for v in views], wrist.K)
        photo = np.median([off_by(hand_eye.fk(arm, q + off) @ X, hand_eye.fk(arm, q) @ T_MOUNT) for q in held], axis=0)
        print(f"{name:22s} %6.3f deg %5.2f mm  %5.2f   %5.3f deg %5.2f mm   %5.3f deg %5.2f mm" % (
            *off_by(X, T_MOUNT), np.sqrt(np.mean(rms ** 2)), *off_by(T_board, vision.T_BASE_BOARD), *photo))


if __name__ == "__main__":
    main()
