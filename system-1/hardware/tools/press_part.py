"""Press (or flip, slide, turn: the part's own skill) one part from scan_check's last scan with the pipeline's own press (affordances.run_step), the last look on:
from the approach pose it re-finds the part in a fresh photo first. Contact is by stall. You say what changed on the
device after the press (the operator readout), which gives the verdict. The arm returns to where it rested limp before
torque goes off. Don't move the device between scan_check and this.

    python tools/press_part.py COM11 CAL.json button_1
    python tools/press_part.py COM11 CAL.json button_1,button_2,button_3
    python tools/press_part.py COM11 CAL.json toggle_1 --lean-other
    python tools/press_part.py COM11 CAL.json toggle_2 --knob --angle 60
    python tools/press_part.py COM11 CAL.json toggle_1 --grip --angle 60
    python tools/press_part.py COM11 CAL.json button_1 --no-look
    python tools/press_part.py COM11 CAL.json button_1 --no-shift
    python tools/press_part.py COM11 CAL.json button_1 --stall 2.5
    python tools/press_part.py COM11 CAL.json button_1 --down 0.5
    python tools/press_part.py COM11 CAL.json button_1 --shift-scale 2
"""
import logging
import os
import pickle
import sys
import threading
import time

import cv2
import numpy as np

logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)  # Windows noise

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import affordances  # noqa: E402
import hw_rig  # noqa: E402
import pipeline  # noqa: E402
import real_arm  # noqa: E402
from real_skills import flip, grip_turn, slope_swing, turn  # noqa: E402
import skills  # noqa: E402


SHIFT = real_arm.RealArm.part_shift.copy()  # a copy: --no-shift and --shift-scale change it in place


def shift(p):
    p.T = p.T.copy()
    p.T[:3, 3] += SHIFT - (SHIFT @ p.normal) * p.normal
    return p


def save(rig, out, name):
    """The wrist camera's newest frame and the joint readings, for working out afterwards where things were."""
    path = os.path.join(out, f"{name}_{sum(f.startswith(name) and f.endswith('.jpg') for f in os.listdir(out))}")
    cv2.imwrite(path + ".jpg", rig.wrist.grab.read()[0])
    np.save(path + ".npy", rig.arm.read_q())
    print(f"  saved {path}.jpg")


def main(argv=None, ask=input):
    args = argv or sys.argv[1:]
    port, cal, targets = args[0], args[1], args[2].split(",")
    scene = pickle.load(open(os.path.join(os.getcwd(), "scan_check", "scene.pkl"), "rb"))
    missing = [t for t in targets if t not in {p.id for p in scene.parts}]
    if missing:
        print(f"No {missing} in the last scan: it has {[p.id for p in scene.parts]}")
        return
    if "--no-shift" in args:
        SHIFT[:] = 0
    if "--shift-scale" in args:  # SHIFT times this, to try a bigger or smaller correction
        SHIFT[:] *= float(args[args.index("--shift-scale") + 1])
    for p in scene.parts:
        shift(p)
        if p.kind == "toggle":
            slope_swing(p)
            if "--lean-other" in args:  # the lever was flipped by hand since the scan: it leans the other way now
                n, v = p.normal, p.meta["tip"] - p.pos
                p.meta = {**p.meta, "tip": p.pos + 2 * (v @ n) * n - v}
                p.T[:3, :2] *= -1  # _flip_plan pushes toward -x from the +x side it leans to
    for p in scene.parts:
        if p.id in targets:
            print(f"{p.id}: {p.kind} at {np.round(p.pos * 1000)} mm (after the {np.round(SHIFT * 1000, 1)} mm correction)")
    if "--no-look" not in args:  # torch and SAM load while the arm connects and goes home
        loading = threading.Thread(target=lambda: __import__("segmodels").sam_boxes(), daemon=True)
        loading.start()
    rig = hw_rig.make_rig(port, cal)
    arm = rig.arm
    if "--stall" in args:  # mm the command may run ahead before it counts as contact (default RealArm.stall_m)
        arm.stall_m = float(args[args.index("--stall") + 1]) / 1000
    if "--down" in args:  # 0 presses along the panel's normal, 1 straight down (affordances._press_axis)
        arm.press_down = float(args[args.index("--down") + 1])
    if "--depth" in args:  # mm past the expected top for a fixed-depth press (RealArm.press_depth)
        arm.press_depth = float(args[args.index("--depth") + 1]) / 1000
    if "--close" in args:  # mm out for a second last look (affordances._refine)
        arm.look_close = float(args[args.index("--close") + 1]) / 1000
    arm.app = real_arm.OperatorReadout(arm, ask=ask)  # the same prompt as the rest, so a script can answer it
    try:
        arm.tick()
        rest = arm.read_q()
        if ask(f"The arm will go home, press {', '.join(targets)}, and come back here. Is it clear? Type yes to go: "
               ).strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        try:
            skills.go_home(arm)
            if "--no-look" not in args:
                loading.join()
            look = None if "--no-look" in args else pipeline.last_look(rig.wrist, scene.plane[0])
            if look is not None:
                look0 = look
                out = os.path.join(os.getcwd(), "scan_check")

                def look(arm, p):  # the camera's offset is in the last look's answer too
                    save(rig, out, f"look_{p.id}")
                    q = look0(arm, p)
                    return shift(q) if q.meta.get("refined") else q
            line, now = affordances._line, [targets[0]]

            def snap_then_line(a, *rest, **kw):  # a photo at the bottom of the press: the jaw is in view
                if a.status.endswith("retreat"):
                    save(rig, os.path.join(os.getcwd(), "scan_check"), f"press_{now[0]}")
                return line(a, *rest, **kw)
            affordances._line = snap_then_line
            film, stop = os.path.join(os.getcwd(), "scan_check", "push"), threading.Event()
            os.makedirs(film, exist_ok=True)
            for f in os.listdir(film):
                os.remove(os.path.join(film, f))

            def filming():  # the wrist camera through the push, about 10 a second, to see first contact and any slip
                k = 0
                while not stop.wait(0.1):
                    if arm.status.endswith(("push", ": down", ": turn", ": up", ": in")):
                        cv2.imwrite(os.path.join(film, f"{k:03d}.jpg"), cv2.resize(rig.wrist.grab.read()[0], None, fx=0.5, fy=0.5))
                        k += 1
            threading.Thread(target=filming, daemon=True).start()
            t0 = time.time()
            for target in targets:  # one after another, no going home between
                now[0] = target
                part = next(p for p in scene.parts if p.id == target)
                if "--grip" in args:  # grip this part as a round knob and twist it by --angle degrees
                    angle = float(args[args.index("--angle") + 1]) if "--angle" in args else 60.0
                    r = grip_turn(arm, part, scene.plane[0], np.radians(angle), rig.wrist,
                                  lambda: save(rig, os.path.join(os.getcwd(), "scan_check"), f"grip_{target}"))
                elif "--knob" in args:  # turn this part as a round knob, by --angle degrees (+ counter-clockwise)
                    angle = float(args[args.index("--angle") + 1]) if "--angle" in args else 60.0
                    r = turn(arm, part, scene.plane[0], np.radians(angle))
                elif part.kind == "toggle" and "--guarded" not in args:
                    r = flip(arm, part, scene.parts, lambda: save(rig, os.path.join(os.getcwd(), "scan_check"), f"flip_{target}"))
                else:
                    r = affordances.run_step(arm, scene.parts, {"skill": affordances.SKILL_FOR[part.kind], "target": target},
                                             None, look)
                print(f"{target}:")
                for k in ("verdict", "reason", "stop", "contact_offset_mm", "refined", "refine_why", "duration_s"):
                    print(f"  {k}: {r.get(k)}")
            stop.set()
            print(f"{len(targets)} presses in {time.time() - t0:.1f} s")
            skills.go_home(arm)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds
            print(f"Stopped: {type(e).__name__}: {e or 'Ctrl+C'}")
        skills.move_joints(arm, rest)
        ask("Hold the arm, then press Enter: torque goes off. ")
    finally:
        rig.close()


if __name__ == "__main__":
    main()
