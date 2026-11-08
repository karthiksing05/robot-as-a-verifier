"""Find where the gripper sits in the wrist camera's picture, for the scan to ignore (rgbperceive.GRIPPER_PX). The gripper
moves with the camera, so across frames of different scenes it stays put while everything else changes. Torque stays off:
you point the camera somewhere new before each frame. Writes gripper_px.json next to hand_eye.json, which hw_rig loads,
and gripper_mask.png in the current folder to check by eye.

    python tools/gripper_mask.py COM11 CAL.json
"""
import json
import os
import sys

import cv2
import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import real_arm  # noqa: E402
import real_wrist  # noqa: E402

FRAMES = 6
STILL = 18          # grey levels: a pixel whose largest change across the frames is under this belongs to the gripper
GROW_PX = 30        # margin around it, as the jaws flex and the moving jaw isn't exactly where it was
OUT = os.path.join(os.path.dirname(real_wrist.HAND_EYE), "gripper_px.json")


def mask_from(frames):
    """The gripper's outline (convex hull, grown GROW_PX) from frames of different scenes, as an Nx2 int array."""
    g = np.array([cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (21, 21), 0) for f in frames], float)
    still = ((g.max(axis=0) - g.min(axis=0)) < STILL).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(still)
    h, w = still.shape
    # the gripper enters from the frame's edge: keep the biggest still region that touches it
    best = max((i for i in range(1, n) if stats[i, 0] == 0 or stats[i, 1] == 0 or stats[i, 0] + stats[i, 2] == w
                or stats[i, 1] + stats[i, 3] == h), key=lambda i: stats[i, 4], default=None)
    if best is None:
        raise RuntimeError("nothing stayed still across the frames: is the gripper in view?")
    region = cv2.dilate((lab == best).astype(np.uint8), np.ones((2 * GROW_PX + 1,) * 2, np.uint8))
    hull = cv2.convexHull(cv2.findNonZero(region)).reshape(-1, 2)
    return hull, (lab == best).mean()


def main(argv=None, ask=input):
    port, cal = (argv or sys.argv[1:])[:2]
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(real_arm.make_bus(port, cal)) as arm:
        cam = real_wrist.WristCamera(arm, T_hand_eye=np.eye(4))
        try:
            frames = []
            for k in range(FRAMES):
                ask(f"Frame {k + 1} of {FRAMES}: point the camera at something different (desk, wall, floor, a busy "
                    f"shelf), hold still, press Enter: ")
                frames.append(cam.capture().rgb)
        finally:
            cam.close()
    hull, share = mask_from(frames)
    img = frames[-1].copy()
    cv2.polylines(img, [hull.astype(np.int32)], True, (0, 0, 255), 4)
    cv2.imwrite(os.path.join(os.getcwd(), "gripper_mask.png"), img)
    print(f"The gripper covers {share * 100:.0f}% of the frame; outline with a {GROW_PX} px margin has {len(hull)} points. "
          f"Check gripper_mask.png: the red outline should hug the jaws with a little room.")
    if ask(f"Save it to {OUT} for the real rig's scans? Type yes: ").strip() == "yes":
        json.dump({"gripper_px": hull.tolist(), "width": int(img.shape[1])}, open(OUT, "w"))
        print("Wrote", OUT)


if __name__ == "__main__":
    main()
