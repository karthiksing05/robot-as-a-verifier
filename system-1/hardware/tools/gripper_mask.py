"""Mark where the gripper sits in the wrist camera's picture, for the scan to ignore (rgbperceive.GRIPPER_PX). Torque stays
off. It takes one frame and shows it: click points around the gripper (left click adds, r restarts), then Enter. The outline
grows GROW_PX for margin and goes to gripper_px.json next to hand_eye.json, which hw_rig loads; gripper_mask.png in the
current folder shows it. (Finding it automatically from several frames failed on auto exposure and saturated plastic.)

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

GROW_PX = 30        # margin around the clicked outline, as the jaws flex and the moving jaw isn't exactly where it was
OUT = os.path.join(os.path.dirname(real_wrist.HAND_EYE), "gripper_px.json")


def outline(points, shape):
    """Convex hull of the clicked points, grown GROW_PX and kept inside the frame, as an Nx2 int array."""
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(np.array(points, np.int32))], 1)
    m = cv2.dilate(m, np.ones((2 * GROW_PX + 1,) * 2, np.uint8))
    return cv2.convexHull(cv2.findNonZero(m)).reshape(-1, 2)


def click(frame):
    pts, view = [], cv2.resize(frame, None, fx=0.5, fy=0.5)

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            pts.append((2 * x, 2 * y))
    cv2.namedWindow("gripper_mask")
    cv2.setMouseCallback("gripper_mask", on_mouse)
    while True:
        img = view.copy()
        for p in pts:
            cv2.circle(img, (p[0] // 2, p[1] // 2), 5, (0, 0, 255), -1)
        if len(pts) > 2:
            cv2.polylines(img, [cv2.convexHull(np.array(pts) // 2)], True, (0, 0, 255), 2)
        cv2.putText(img, "Click around the gripper. r: restart, Enter: done", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 0, 255), 2)
        cv2.imshow("gripper_mask", img)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("r"):
            pts.clear()
        elif k in (13, 10) and len(pts) > 2:
            cv2.destroyAllWindows()
            return pts


def main(argv=None, ask=input):
    port, cal = (argv or sys.argv[1:])[:2]
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(real_arm.make_bus(port, cal)) as arm:
        cam = real_wrist.WristCamera(arm, T_hand_eye=np.eye(4))
        try:
            ask("Point the camera at something plain so the gripper stands out, hold still, press Enter: ")
            frame = cam.capture().rgb
        finally:
            cam.close()
    hull = outline(click(frame), frame.shape)
    img = frame.copy()
    cv2.polylines(img, [hull.astype(np.int32)], True, (0, 0, 255), 4)
    cv2.imwrite(os.path.join(os.getcwd(), "gripper_mask.png"), img)
    print(f"Outline with a {GROW_PX} px margin: {len(hull)} points. gripper_mask.png shows it.")
    if ask(f"Save it to {OUT} for the real rig's scans? Type yes: ").strip() == "yes":
        json.dump({"gripper_px": hull.tolist(), "width": int(frame.shape[1])}, open(OUT, "w"))
        print("Wrote", OUT)


if __name__ == "__main__":
    main()
