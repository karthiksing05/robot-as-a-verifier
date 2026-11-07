"""Hand-eye calibration of the wrist camera: where the camera really sits relative to the model's wrist_cam.

It shows the result and, if you type yes, writes real_wrist.HAND_EYE, which real_wrist.WristCamera multiplies onto
every frame's pose. Torque stays off the whole time: you pose the arm by hand, and at each pose the script reads the
joints and takes a frame of the desk board.

    python tools/hand_eye.py COM5 CAL.json              # 50 views, the solve, then asks before writing HAND_EYE
    python tools/hand_eye.py COM5 CAL.json --views 70

CAL.json is lerobot-calibrate's file. Run arm_check.py first: the joint mapping has to be right. The board is the desk
board (vision.BOARD, which `tools/cam_check.py board` prints), left where it is fixed. At each pose, hold the arm still
with at least half the board in the frame from 15 to 25 cm, and press Enter. Spread the poses: tilt the camera 20 to 30
deg toward each side and roll the wrist both ways. Views turned about one axis alone leave the mount undetermined.

Each view gives the model's wrist_cam pose, by forward kinematics of the joint readings, and the board's pose in the
camera, by PnP. Park's method (OpenCV's calibrateHandEye, eye in hand) gives a first mount from those, and least
squares then fits the mount and the board's pose to every corner seen. The encoders' 0.088 deg steps are what limit
it, and they leave about 1.5 px of reprojection error in each view. More views, well spread, is what brings the error
down: in the sim, 20 views left it 0.09 deg and 0.47 mm rms, 50 views 0.05 deg and 0.24 mm (sim/docs/real-arm.md).
Solving again with each view left out in turn gives the result's expected error, and the script says when that is
over TARGET.

Hand-eye only fixes the mount. A joint offset that real_arm.OFFSET_RAD doesn't know moves the camera differently at
each pose, so the mount can't absorb it, except wrist_roll's, which folds in. Such offsets show as views well over
1.5 px and as the board found millimetres from vision.T_BASE_BOARD, which only means something if the printed board
sits there to well under a millimetre. shoulder_pan's shows only in the board's place.
"""
import argparse
import json
import os
import sys

import cv2
import mujoco
import numpy as np
from scipy.optimize import least_squares

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE] + [os.path.join(HARDWARE, "..", d) for d in ("core", "sim")]  # sim: the desk board, vision.py
import real_arm  # noqa: E402
import real_wrist  # noqa: E402
import vision  # noqa: E402
from rig import TICK_RAD, _cv_pose  # noqa: E402

MIN_CORNERS = 12   # of the board's 24
READS = 5          # joint readings before the frame and again after it, averaged
STILL_RAD = 2 * TICK_RAD  # the readings after the frame moved this far from those before: the arm moved
TARGET = (0.1, 0.5)  # deg, mm: under the per-photo error that lost the scan (system-1/arm/camera/results.md)


def fk(arm, q):
    """The model's wrist_cam pose at joint angles q (4x4, arm frame, OpenCV axes), as WristCamera.believed_pose."""
    d = mujoco.MjData(arm.m)
    d.qpos[arm.qadr] = q
    mujoco.mj_kinematics(arm.m, d)
    mujoco.mj_camlight(arm.m, d)
    return _cv_pose(d, arm.m.camera("wrist_cam").id)


def board_in_cam(bgr, K):
    """The board's pose in the camera (4x4) and the corners it used (object Nx3, image Nx2), or None."""
    cc, ci, _, _ = vision.CHARUCO.detectBoard(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    if ci is None or len(ci) < MIN_CORNERS:
        return None
    obj, img = vision.BOARD.getChessboardCorners()[ci.ravel()], cc.reshape(-1, 2)
    _, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    return vision._T(cv2.Rodrigues(rvec)[0], tvec.ravel()), obj, img


def hand_eye(hand, board):
    """X with hand[i] @ X @ board[i] the same for every view, by Park and Martin's method (OpenCV's
    CALIB_HAND_EYE_PARK: opencv-contrib-python 5.0 has the constant but not calibrateHandEye). Each pair of views gives
    a hand motion A and a camera motion B with A X = X B: their rotation vectors give R by least squares (Kabsch), and
    then (R_A - I) t = R t_B - t_A gives t."""
    pairs = [(i, j) for i in range(len(hand)) for j in range(i + 1, len(hand))]
    A = [np.linalg.inv(hand[i]) @ hand[j] for i, j in pairs]
    B = [board[i] @ np.linalg.inv(board[j]) for i, j in pairs]
    rv = lambda T: cv2.Rodrigues(T[:3, :3])[0].ravel()  # noqa: E731
    u, _, vt = np.linalg.svd(sum(np.outer(rv(a), rv(b)) for a, b in zip(A, B)))
    R = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    t = np.linalg.lstsq(np.vstack([a[:3, :3] - np.eye(3) for a in A]),
                        np.concatenate([R @ b[:3, 3] - a[:3, 3] for a, b in zip(A, B)]), rcond=None)[0]
    return vision._T(R, t)


def _errors(X, T_board, views, K):
    """Per view, its corners where X and T_board put them less where they were seen (px). The frames are pinhole
    images, so this is K alone (cv2.projectPoints would need a rotation vector, which is imprecise near 180 deg)."""
    out = []
    for v in views:
        p = (np.linalg.inv(v["hand"] @ X) @ T_board @ np.c_[v["obj"], np.ones(len(v["obj"]))].T)[:3]
        out.append((K @ (p / p[2]))[:2].T - v["img"])
    return out


def solve(views, K):
    """T_hand_eye, the board's pose in the arm frame, and each view's reprojection rms (px). Park's method gives the
    start, then least squares fits both to every corner seen: one view's PnP alone is only good to a few tenths of a
    degree. views: dicts of hand (fk), board (board_in_cam's pose), obj and img (its corners)."""
    hand, board = [v["hand"] for v in views], [v["board"] for v in views]
    X0 = hand_eye(hand, board)
    each = [H @ X0 @ B for H, B in zip(hand, board)]
    u, _, vt = np.linalg.svd(sum(T[:3, :3] for T in each))
    B0 = vision._T(u @ vt, np.mean([T[:3, 3] for T in each], axis=0))
    # small corrections on the start, as rotation vectors and shifts: the board's own rotation is near 180 deg,
    # where a rotation vector wraps
    nudge = lambda T, p: T @ vision._T(cv2.Rodrigues(p[:3])[0], p[3:])  # noqa: E731
    p = least_squares(lambda p: np.concatenate(_errors(nudge(X0, p[:6]), nudge(B0, p[6:]), views, K)).ravel(),
                      np.zeros(12)).x
    X, T_board = nudge(X0, p[:6]), nudge(B0, p[6:])
    rms = [np.sqrt(np.mean(np.sum(e ** 2, axis=1))) for e in _errors(X, T_board, views, K)]
    return X, T_board, np.array(rms)


def expected_error(X, views, K):
    """X's expected error (deg, mm), by the jackknife: X solved again with each view left out in turn. On the sim's
    views it came within about 10% of the true rms error."""
    d = []
    for i in range(len(views)):
        D = np.linalg.inv(X) @ solve(views[:i] + views[i + 1:], K)[0]
        d.append(np.r_[cv2.Rodrigues(D[:3, :3])[0].ravel(), D[:3, 3]])
    d = np.array(d)
    var = (len(d) - 1) / len(d) * np.sum((d - d.mean(axis=0)) ** 2, axis=0)
    return np.degrees(np.sqrt(var[:3].sum())), np.sqrt(var[3:].sum()) * 1000


def _read(arm):
    arm.tick()  # torque off: this only reads the joints
    return arm.read_q()


def collect(arm, wrist, n, ask):
    """n views: at each, ask() waits for the arm to be posed, then the joints are read around one frame."""
    views = []
    while len(views) < n:
        ask(f"View {len(views) + 1} of {n}: pose the arm with the board in view, hold it still, press Enter: ")
        before = [_read(arm) for _ in range(READS)]
        frame = wrist.capture()
        after = [_read(arm) for _ in range(READS)]
        moved = np.abs(np.mean(after, axis=0) - np.mean(before, axis=0)).max()
        if moved > STILL_RAD:
            print(f"  the arm moved {np.degrees(moved):.2f} deg during the shot: again")
            continue
        seen = board_in_cam(frame.rgb, frame.K)
        if seen is None:
            print(f"  fewer than {MIN_CORNERS} board corners in view: again")
            continue
        q = np.mean(before + after, axis=0)
        views.append(dict(q=q, hand=fk(arm, q), board=seen[0], obj=seen[1], img=seen[2]))
        print(f"  {len(seen[1])} corners, board {np.linalg.norm(seen[0][:3, 3]) * 1000:.0f} mm away")
    return views


def report(X, T_board, rms, err):
    print("Reprojection rms per view (px): " + " ".join(f"{e:.2f}" for e in rms))
    off = np.linalg.inv(vision.T_BASE_BOARD) @ T_board
    deg = lambda T: np.degrees(np.linalg.norm(cv2.Rodrigues(T[:3, :3])[0]))  # noqa: E731
    print(f"All views {np.sqrt(np.mean(rms ** 2)):.2f} px rms, worst {rms.max():.2f}. Mount: {deg(X):.2f} deg and "
          f"{np.linalg.norm(X[:3, 3]) * 1000:.1f} mm from the model's wrist_cam. Board: {deg(off):.2f} deg and "
          f"{np.linalg.norm(off[:3, 3]) * 1000:.1f} mm from vision.T_BASE_BOARD.")
    print(f"Expected error of the mount: {err[0]:.3f} deg and {err[1]:.2f} mm.")
    if err[0] > TARGET[0] or err[1] > TARGET[1]:
        print(f"That is over the target of {TARGET[0]} deg and {TARGET[1]} mm, so this mount isn't good enough for "
              f"the scan. Run again with more views, turned further apart.")


def main(argv=None, bus=None, ask=input, camera=real_wrist.WristCamera):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port", help="the follower's serial port, e.g. COM5")
    ap.add_argument("calibration", help="lerobot-calibrate's JSON file for this arm")
    ap.add_argument("--views", type=int, default=50, help="how many poses (default 50)")
    ap.add_argument("--out", default=real_wrist.HAND_EYE, help="where to write the result (default real_wrist's)")
    args = ap.parse_args(argv)
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        wrist = camera(arm)
        try:
            views = collect(arm, wrist, args.views, ask)
        finally:
            wrist.close()
    X, T_board, rms = solve(views, wrist.K)
    report(X, T_board, rms, expected_error(X, views, wrist.K))
    if ask(f"Write this to {args.out}, for WristCamera to use? Type yes to save: ").strip().lower() != "yes":
        print("Not saved.")
        return X, views
    with open(args.out, "w") as f:
        json.dump({"T_hand_eye": X.tolist(), "T_base_board": T_board.tolist(), "rms_px": rms.tolist(),
                   "views": [{k: v[k].tolist() for k in ("q", "obj", "img")} for v in views]}, f)
    print(f"Wrote {args.out}")
    return X, views


if __name__ == "__main__":
    main()
