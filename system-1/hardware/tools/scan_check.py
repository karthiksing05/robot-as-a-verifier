"""Scan a real device with the pipeline's RGB route (pipeline.scan_device on hw_rig's rig) and list the parts it finds.
The arm moves itself: home, the wrist survey around home, then the scan's views. It touches nothing. Saves every wrist
frame and the parts to scan_check/ in the current folder.

    python tools/scan_check.py COM11 CAL.json

Put the device in front of the arm first, its panel 22-26 cm out and facing the arm (tilted back about 45 deg reaches
best). The scan needs the panel's printing for features: a plain panel fails the survey.
"""
import os
import pickle
import sys
import time

import cv2
import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import hw_rig  # noqa: E402
import pipeline  # noqa: E402
import skills  # noqa: E402
from rig import SafetyStop  # noqa: E402


def main(argv=None, ask=input):
    port, cal = (argv or sys.argv[1:])[:2]
    out = os.path.join(os.getcwd(), "scan_check")
    os.makedirs(out, exist_ok=True)
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    rig = hw_rig.make_rig(port, cal)
    arm, wrist = rig.arm, rig.wrist
    try:
        arm.tick()
        if ask("The arm will go home, then move itself through the survey and scan views in front of it, touching "
               "nothing (a few minutes). Is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        scene, t0 = None, time.time()
        try:
            skills.go_home(arm)
            scene = pipeline.scan_device(arm, None, wrist, on_stage=lambda s, *a: print(f"  {time.time() - t0:5.0f} s  "
                                                                                       f"{s}", flush=True))
            skills.go_home(arm)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {type(e).__name__}: {e or 'Ctrl+C'}")
        if scene is not None:
            for k, f in enumerate(scene.frames):
                cv2.imwrite(os.path.join(out, f"frame_{k:02d}.jpg"), f.rgb)
            with open(os.path.join(out, "scene.pkl"), "wb") as fh:
                pickle.dump(scene, fh)
            print(f"\n{len(scene.parts)} parts found in {time.time() - t0:.0f} s:")
            for p in scene.parts:
                print(f"  {p.id:12s} {p.kind:8s} at {np.round(p.pos * 1000)} mm, size {np.round(p.size * 1000, 1)} mm, "
                      f"score {p.score:.2f}")
            print(f"Frames and scene.pkl in {out}")
        ask("Hold the arm, then press Enter: torque goes off. ")
    finally:
        rig.close()


if __name__ == "__main__":
    main()
