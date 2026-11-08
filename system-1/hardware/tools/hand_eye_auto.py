"""tools/hand_eye.py with the arm moving itself through the views: the same solve, report and save.

    python tools/hand_eye_auto.py COM11 CAL.json                        # 30 views at about 10 deg/s
    python tools/hand_eye_auto.py COM11 CAL.json --views 40 --speed 5

Torque is off at first: pose the arm by hand with the camera on the board, 15 to 25 cm away, and press Enter. That
pose is the first view and the centre of the rest. The others swing the camera around the board's centre by up to
TILT_DEG toward any side and roll the wrist, with no joint more than JOINT_DEG and the tip no more than TIP_M from the
start, and most of the board's corners predicted well inside the image by the model's camera. They are picked to
spread the camera's tilt and roll, as views turned about one axis alone leave the mount undetermined, and ordered to
keep moves short. The script asks before torque goes on. The arm then moves to each with a cosine profile, settles
for SETTLE_S and takes a view; one that fails is tried once more, then skipped. At the end it goes back to the start
and asks before torque goes off. A SafetyStop, Ctrl+C or any other error stops it where it is, holding, and asks the
same. The solve uses whatever views it got.
"""
import argparse
import json

import cv2
import numpy as np
from scipy.optimize import least_squares

import hand_eye  # puts hardware, core and sim on the path
import real_arm
import real_wrist
import vision
from rig import CONTROL_HZ

TILT_DEG = 25               # the camera swung around the board's centre by up to this, toward any side
ROLL_DEG = 30               # and wrist_roll seeded at up to this, capped by JOINT_DEG
MARGIN_RAD = np.radians(5)  # planned poses stay this far inside the joint limits
JOINT_DEG = 45              # and no joint further than this from the start
TIP_M = 0.08
IN_VIEW = 0.8               # at least MIN_IN_VIEW corners predicted inside this middle part of the image
MIN_IN_VIEW = 18
CANDIDATES = 300
SETTLE_S = 1.0
MAX_SPEED_DEG_S = 30


def plan(arm, q0, T_board, K, n, rng):
    """Up to n joint poses near q0 that look at the board, spread in how the camera turns from its start pose, in the
    order to visit them. T_board: the board's pose in the arm frame. Each candidate swings the model's camera around
    the board's centre, at the start's distance, with wrist_roll turned: five joints can't hit a position and a
    pointing exactly, so least squares gets as near as it can and the board's predicted corners decide."""
    corners = T_board @ np.c_[vision.BOARD.getChessboardCorners(), np.ones(24)].T
    centre = corners[:3].mean(axis=1)
    half = K[:2, 2]  # the frames are undistorted onto K, centred
    tip0, C0 = arm.ik.fk(q0)[0], hand_eye.fk(arm, q0)
    cam = arm.m.site("wrist_cam").id  # its -z is the camera's axis
    lo = np.maximum(arm.ik.lo + MARGIN_RAD, q0 - np.radians(JOINT_DEG))
    hi = np.minimum(arm.ik.hi - MARGIN_RAD, q0 + np.radians(JOINT_DEG))

    def miss(q, at, roll):
        p, axis = arm.ik.fk(q, cam)
        r = np.linalg.norm(centre - at)
        return np.r_[(p - at) / r, axis - (centre - at) / r, 0.1 * (q[4] - roll)]
    poses, turns = [], []
    for tx, ty, roll in rng.uniform(-1, 1, (CANDIDATES, 3)) * np.radians([TILT_DEG, TILT_DEG, ROLL_DEG]):
        at = centre + cv2.Rodrigues(C0[:3, :3] @ [tx, ty, 0])[0] @ (C0[:3, 3] - centre)
        seed = np.clip(q0 + [0, 0, 0, 0, roll], lo, hi)
        q = least_squares(miss, seed, args=(at, seed[4]), bounds=(lo, hi)).x
        C = hand_eye.fk(arm, q)
        p = (np.linalg.inv(C) @ corners)[:3]
        uv = (K @ (p / p[2]))[:2].T
        if (np.linalg.norm(arm.ik.fk(q)[0] - tip0) <= TIP_M
                and np.sum(np.all(np.abs(uv - half) < IN_VIEW * half, axis=1)) >= MIN_IN_VIEW):
            poses.append(q)
            turns.append(cv2.Rodrigues(C0[:3, :3].T @ C[:3, :3])[0].ravel())
    # farthest first: each pick is the pose turned furthest from the start and from every pick so far
    turns, picked = np.array(turns).reshape(-1, 3), []
    gap = np.linalg.norm(turns, axis=1)
    for _ in range(min(n, len(poses))):
        i = int(np.argmax(gap))
        picked.append(poses[i])
        gap = np.minimum(gap, np.linalg.norm(turns - turns[i], axis=1))
    order, at = [], q0  # then the nearest unvisited each time, by the largest joint change
    while picked:
        at = picked.pop(min(range(len(picked)), key=lambda i: np.abs(picked[i] - at).max()))
        order.append(at)
    return order


def move(arm, q, speed):
    """From the command to q with a cosine profile, the largest joint change at about speed deg/s on average."""
    q0 = arm.cmd.copy()
    n = max(1, round(np.degrees(np.abs(q - q0).max()) / speed * CONTROL_HZ))
    for k in range(1, n + 1):
        arm.send(q0 + (q - q0) * (0.5 - 0.5 * np.cos(np.pi * k / n)))
        arm.tick()


def settle(arm):
    for _ in range(round(SETTLE_S * CONTROL_HZ)):
        arm.tick()


def collect(arm, wrist, n, speed, ask):
    """The start view, posed by hand, then the arm's own views around it, n in all."""
    while True:
        ask("Pose the arm by hand with the camera on the board, 15 to 25 cm away: the views spread around this pose. "
            "Hold it still and press Enter: ")
        start, what = hand_eye._take(arm, wrist)
        print("  " + what)
        if start:
            break
    poses = plan(arm, start["q"], start["hand"] @ start["board"], wrist.K, n - 1, np.random.default_rng(0))
    if len(poses) < 4:
        print(f"Only {len(poses)} poses near this one keep the board in view. Centre the board in the picture, "
              f"about 20 cm away, and run again.")
        return [start]
    far = np.degrees(max(np.abs(q - start["q"]).max() for q in poses))
    if ask(f"Torque goes on for the five arm joints, which hold this pose. The arm then moves itself through "
           f"{len(poses)} poses, no joint more than {far:.0f} deg and the tip no more than {TIP_M * 100:.0f} cm from "
           f"here, at about {speed:g} deg/s, comes back and waits for you before torque goes off. Ctrl+C stops it and "
           f"it holds. Is it clear to move? Type yes to go: ").strip() != "yes":
        print("Not moved.")
        return [start]
    arm.enable(confirm=True)
    views = [start]
    try:
        for i, q in enumerate(poses):
            move(arm, q, speed)
            for attempt in (1, 2):
                settle(arm)
                view, what = hand_eye._take(arm, wrist)
                if view or attempt == 2:
                    break
                print("  " + what)
            print(f"View {i + 2} of {len(poses) + 1}: " + (what if view else what.split(":")[0] + ", skipped"))
            if view:
                views.append(view)
        move(arm, start["q"], speed)
    except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
        print(f"Stopped: {str(e) or type(e).__name__}. The arm holds where it is.")
    while True:  # a second Ctrl+C here must not drop the arm
        try:
            ask("Hold the arm, then press Enter: torque goes off. ")
            break
        except KeyboardInterrupt:
            print("Torque stays on until you press Enter.")
    return views


def main(argv=None, bus=None, ask=input, camera=real_wrist.WristCamera):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port", help="the follower's serial port, e.g. COM11")
    ap.add_argument("calibration", help="lerobot-calibrate's JSON file for this arm")
    ap.add_argument("--views", type=int, default=30, help="how many views, the start's included (default 30)")
    ap.add_argument("--speed", type=float, default=10.0,
                    help=f"the largest joint's average speed in deg/s, at most {MAX_SPEED_DEG_S} (default 10)")
    ap.add_argument("--out", default=real_wrist.HAND_EYE, help="where to write the result (default real_wrist's)")
    args = ap.parse_args(argv)
    if not 0 < args.speed <= MAX_SPEED_DEG_S:
        ap.error(f"--speed must be over 0 and at most {MAX_SPEED_DEG_S}")
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        wrist = camera(arm)
        try:
            views = collect(arm, wrist, args.views, args.speed, ask)
        finally:
            wrist.close()
    if len(views) < 5:
        print(f"Only {len(views)} views: too few to solve.")
        return None, views
    X, T_board, rms = hand_eye.solve(views, wrist.K)
    hand_eye.report(X, T_board, rms, hand_eye.expected_error(X, views, wrist.K))
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
