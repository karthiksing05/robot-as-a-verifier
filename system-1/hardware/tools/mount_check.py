"""One wrist frame with the fixed jaw's tip drawn where the model expects it: green with hand_eye.json's mount, red with
the CAD camera. Torque stays off. Writes mount_check.png and prints the pixels.

    python tools/mount_check.py COM11 CAL.json
"""
import os
import sys

import cv2
import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import mujoco  # noqa: E402
import real_arm  # noqa: E402
import real_wrist  # noqa: E402


def project(T_base_cam, K, p):
    c = np.linalg.inv(T_base_cam) @ np.r_[p, 1]
    return None if c[2] <= 0 else (K @ (c[:3] / c[2]))[:2]


def main(argv=None):
    port, cal = (argv or sys.argv[1:])[:2]
    input("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(real_arm.make_bus(port, cal)) as arm:
        cad = real_wrist.WristCamera(arm, T_hand_eye=np.eye(4))  # the model as built: CAD camera
        try:
            arm.tick()
            f = cad.capture()
            d = mujoco.MjData(arm.m)
            d.qpos[arm.qadr] = arm.read_q()
            mujoco.mj_kinematics(arm.m, d)
            jaw = d.site("gripperframe").xpos.copy()
            T_cad = f.T_base_cam
            T_he = T_cad @ np.asarray(__import__("json").load(open(real_wrist.HAND_EYE))["T_hand_eye"])
        finally:
            cad.close()
    img = f.rgb.copy()
    for T, colour, name in ((T_cad, (0, 0, 255), "CAD"), (T_he, (0, 255, 0), "hand-eye")):
        uv = project(T, f.K, jaw)
        print(f"{name:8s} mount puts the fixed jaw tip at pixel", "behind the camera" if uv is None else np.round(uv))
        if uv is not None and abs(uv[0]) < 5000 and abs(uv[1]) < 5000:
            cv2.drawMarker(img, tuple(int(v) for v in uv), colour, cv2.MARKER_CROSS, 60, 4)
            cv2.putText(img, name, (int(uv[0]) + 20, int(uv[1]) - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, colour, 3)
    out = os.path.join(os.getcwd(), "mount_check.png")
    cv2.imwrite(out, img)
    print("Wrote", out, "- the real fixed jaw tip should sit under the green cross if hand_eye.json is right")


if __name__ == "__main__":
    main()
