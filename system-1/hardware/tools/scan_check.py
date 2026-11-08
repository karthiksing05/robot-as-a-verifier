"""Scan a real device with the pipeline's RGB route (pipeline.scan_device on hw_rig's rig) and list the parts it finds.
The arm moves itself: home, the wrist survey around home, then the scan's views. It touches nothing. Saves every wrist
frame and the parts to scan_check/ in the current folder. A window shows the wrist camera live while it works (the
gripper mask outlined), then what the segmentation found: every candidate outlined, the parts circled and named.

    python tools/scan_check.py COM11 CAL.json

Put the device in front of the arm first, its panel 22-26 cm out and facing the arm (tilted back about 45 deg reaches
best). The scan needs the panel's printing for features: a plain panel fails the survey.
"""
import os
import pickle
import sys
import threading
import time

import cv2
import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import hw_rig  # noqa: E402
import pipeline  # noqa: E402
import rgbperceive  # noqa: E402
import skills  # noqa: E402
from rig import SafetyStop  # noqa: E402


class Live(threading.Thread):
    """A window with the wrist camera's newest frame at half size, the gripper mask and the scan's stage; once result
    is set it shows that picture instead. Reads frames only, never the arm, so it can run beside the scan."""

    def __init__(self, wrist):
        super().__init__(daemon=True)
        self.wrist, self.stage, self.result, self.done = wrist, "starting", None, threading.Event()
        self.start()

    def run(self):
        while not self.done.is_set():
            if self.result is not None:
                img = self.result
            else:
                bgr, _ = self.wrist.grab.read()
                img = cv2.resize(bgr, None, fx=0.5, fy=0.5)
                cv2.polylines(img, [rgbperceive._gripper(img.shape[1])], True, (0, 200, 255), 2)
                cv2.putText(img, self.stage, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
                cv2.putText(img, self.stage, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            cv2.imshow("scan_check: wrist camera", img)
            cv2.waitKey(80)
        cv2.destroyAllWindows()


def results_image(scene):
    """The last scan frame with every candidate's outline (grey: rejected, with why) and the parts circled in red."""
    f = (scene.frames or [None])[-1]
    if f is None:
        return None
    img, inv = f.rgb.copy(), np.linalg.inv(f.T_base_cam)

    def px(P):
        c = (inv @ np.c_[P, np.ones(len(P))].T)[:3]
        return (f.K @ (c / c[2]))[:2].T.astype(np.int32)
    for b in scene.blobs:
        colour = (0, 0, 255) if b.get("part") else (160, 160, 160)
        if b.get("outline") is not None and len(b["outline"]):
            cv2.polylines(img, [px(np.asarray(b["outline"]))], True, colour, 3)
    for p in scene.parts:
        u, v = px(p.pos[None])[0]
        cv2.putText(img, f"{p.id} {p.score:.2f}", (int(u) + 15, int(v) - 15), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 3)
    return cv2.resize(img, None, fx=0.5, fy=0.5)


def main(argv=None, ask=input):
    port, cal = (argv or sys.argv[1:])[:2]
    out = os.path.join(os.getcwd(), "scan_check")
    os.makedirs(out, exist_ok=True)
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    rig = hw_rig.make_rig(port, cal)
    arm, wrist = rig.arm, rig.wrist
    try:
        arm.tick()
        rest = arm.read_q()  # where the arm rests limp: it goes back here before torque goes off
        if ask("The arm will go home, then move itself through the survey and scan views in front of it, touching "
               "nothing (a few minutes). Is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        scene, t0 = None, time.time()
        live = Live(wrist)

        def stage(name, *_):
            live.stage = f"{time.time() - t0:.0f} s  {name}"
            print(f"  {live.stage}", flush=True)
        try:
            skills.go_home(arm)
            scene = pipeline.scan_device(arm, None, wrist, on_stage=stage)
            skills.go_home(arm)
            skills.move_joints(arm, rest)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {type(e).__name__}: {e or 'Ctrl+C'}")
            try:
                skills.move_joints(arm, rest)  # back to where it rests limp, so torque-off doesn't drop it
            except (Exception, KeyboardInterrupt) as e2:
                print(f"Couldn't get back to rest ({e2}): it holds here")
        if scene is not None:
            for k, f in enumerate(scene.survey.get("captures", [])):
                cv2.imwrite(os.path.join(out, f"survey_{k:02d}.jpg"), getattr(f, "frame", f).rgb)
            for k, f in enumerate(scene.frames):
                cv2.imwrite(os.path.join(out, f"frame_{k:02d}.jpg"), f.rgb)
            with open(os.path.join(out, "scene.pkl"), "wb") as fh:
                pickle.dump(scene, fh)
            print(f"\n{len(scene.parts)} parts found in {time.time() - t0:.0f} s:")
            for p in scene.parts:
                print(f"  {p.id:12s} {p.kind:8s} at {np.round(p.pos * 1000)} mm, size {np.round(p.size * 1000, 1)} mm, "
                      f"score {p.score:.2f}")
            print(f"Frames and scene.pkl in {out}")
            res = results_image(scene)
            if res is not None:
                cv2.imwrite(os.path.join(out, "results.jpg"), res)
                live.result = res  # the window now shows it
                print("The window shows what it found: red outlines are parts, grey ones candidates it rejected.")
        ask("Hold the arm, then press Enter: torque goes off. ")
        live.done.set()
    finally:
        rig.close()


if __name__ == "__main__":
    main()
