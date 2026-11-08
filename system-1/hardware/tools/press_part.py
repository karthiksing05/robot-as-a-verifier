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
import skills  # noqa: E402


# taken off every part along the panel, in the arm frame: on Nov 8 presses aimed at the camera's position landed 3-5 mm
# up the slope from the cap's centre and slid further up. 5.4 mm clicked TIME+ (2 and 3 landed high, 8 on the lower edge).
# Hand touches read more, but the arm flexes under a hand; the last look agrees with the scan to 1-3.5 mm
SHIFT = np.array([-0.0054, 0.0, -0.00225])


def shift(p):
    p.T = p.T.copy()
    p.T[:3, 3] += SHIFT - (SHIFT @ p.normal) * p.normal
    return p


# a toggle's push came 1 cm above the POWER lever (the scan put its pivot 7 mm over the panel and its tip at 18): lowered.
# And the jaw passed the lever on its side nearer the buttons, and 5 mm further on its other side: moved this far toward +y
TOGGLE_DROP = 0.005
TOGGLE_Y = 0.002
# the jaw came down on the lever's top part and slid along it: it starts this much further back and pushes on further
GRIP_OPEN, GRIP_ABOVE = 0.2, 0.025  # 0.45 opened far wider than the 12 mm dial
# the jaw tips go this far over the panel (from the dial's top they stopped short), with the knob's axis this far in from
# the fixed jaw's tip: midway to the open moving jaw, about on the roll axis
GRIP_FLOOR, GRIP_MID = 0.003, 0.010
# the camera over the SPEED dial saw it this far uphill of the scan's position (the scan read it as a toggle's base)
GRIP_UPHILL = 0.0067  # 10.7 came in high; the look's two corrections had come to about 4 mm
GRIP_LOOKS = 4  # looks from above the knob before going down  # a knob grip: opening, jaw tips this far down its side, start above
KNOB_GAP, KNOB_IN = 0.004, 0.001  # a knob turn comes down this far off its side, then presses this far into it
FLIP_HOVER = 0.015  # above the push's start: 30 mm along the tilted axis was out of reach
FLIP_BEHIND, FLIP_ON = 0.015, 0.003  # 6 mm back still came down on the lever tip (held 11 mm up)


def slope_swing(p):
    """A toggle's swing turned to the panel's slope or across it, whichever the scan's is nearer: the scan read the
    POWER lever's 36 deg off the slope it swings along, and a push that far off can slide off the lever's side."""
    n, x = p.normal, p.x
    down = np.cross(n, np.cross([0.0, 0.0, -1.0], n))
    down /= np.linalg.norm(down)
    across = np.cross(n, down)
    snap = max((down, -down, across, -across), key=lambda a: a @ x)
    p.T = p.T.copy()
    p.T[:3, :3] = np.c_[snap, np.cross(n, snap), n]
    y = np.array([0.0, 1.0, 0.0]) - n[1] * n
    move = -TOGGLE_DROP * n + TOGGLE_Y * y / np.linalg.norm(y)
    p.T[:3, 3] += move
    p.meta = {**p.meta, "tip": p.meta["tip"] + move}
    return p


def flip(arm, p, parts, snap=None):
    """A toggle flipped in four straight moves, the gripper held as for a press (tilt and roll): to just above where the push starts, down to it, across the lever (the
    flip plan's push, past its centre), and up. No look, guarded descent or let-go moves: on the real arm those were
    ten waypoints, and contact sensing can't feel this lever anyway. The operator says whether it flipped."""
    plan = affordances._flip_plan(arm, p, parts)
    if isinstance(plan, str):
        raise RuntimeError(plan)
    n, label = plan.n, f"flip {p.id}"
    a, b = plan.path(0, None)[0], plan.path(plan.length, None)[0]
    m = (b - a) / np.linalg.norm(b - a)
    a, b = a - FLIP_BEHIND * m, b + FLIP_ON * m  # down behind the lever, not on its top; and on far enough to go over
    ax, q0 = affordances._press_axis(arm, p), plan.qs[0].copy()  # the gripper held as for a press
    q0[4] = arm.home_q[4]  # the IK keeps the roll
    _, bias = affordances._approach(arm, a + FLIP_HOVER * ax, -ax, label, q0)
    for name, to, speed in (("down", a, 0.05), ("push", b, 0.03), ("up", b + FLIP_HOVER * ax, 0.05)):
        arm.status = f"{label}: {name}"
        affordances._line(arm, to, -ax, speed, bias)
        if name == "down":  # the arm trailed the command 11 mm here and the push swept over the lever: let it arrive
            for _ in range(50):
                if np.linalg.norm(arm.tip_pose()[0] - a) < 0.0015:
                    break
                arm.send(arm.cmd)
                arm.tick()
            if snap:
                snap()  # beside the lever, about to push
    return {"verdict": "ask the operator", "stop": "done"}


def turn(arm, p, plane, angle):
    """A round knob (the SPEED dial) turned by friction: down beside its side halfway up, 1 mm into it so the grippy jaw
    presses, around its axis by angle (radians, + counter-clockwise seen from above the panel), then out and up. The
    gripper is held as for a press. The scan's knobs have no fin for affordances' turn to push."""
    n, o = plane[:3, 2], plane[:3, 3]
    c = p.pos - ((p.pos - o) @ n) * n  # the axis, on the panel
    r, h = min(p.size[:2]) / 2, p.size[2]
    down = np.cross(n, np.cross([0.0, 0.0, -1.0], n))
    down /= np.linalg.norm(down)
    side = np.cross(n, down)
    at = lambda th, rr: c + (h / 2) * n + rr * (np.cos(th) * down + np.sin(th) * side)  # from the downhill side
    ax, label = affordances._press_axis(arm, p), f"turn {p.id}"
    q0 = arm.cmd.copy()
    q0[4] = arm.home_q[4]
    start = at(0.0, r + KNOB_GAP)
    _, bias = affordances._approach(arm, start + FLIP_HOVER * ax, -ax, label, q0)
    moves = [("down", start, 0.05), ("in", at(0.0, r - KNOB_IN), 0.01)]
    k = max(2, int(abs(angle) / np.radians(10)))
    moves += [("turn", at(angle * i / k, r - KNOB_IN), 0.01) for i in range(1, k + 1)]
    moves += [("out", at(angle, r + KNOB_GAP), 0.02), ("up", at(angle, r + KNOB_GAP) + FLIP_HOVER * ax, 0.05)]
    for name, to, speed in moves:
        arm.status = f"{label}: {name}"
        affordances._line(arm, to, -ax, speed, bias)
    return {"verdict": "ask the operator", "stop": "done"}


def gripper(arm, frac, hold_s=0.6):
    """Gripper to frac of its calibrated range (0 closed, 1 open), holding the arm still while it moves."""
    cal = arm.bus.calibration["gripper"]
    arm.bus.sync_write("Goal_Position", {"gripper": int(cal.range_min + frac * (cal.range_max - cal.range_min))},
                       normalize=False)
    for _ in range(int(hold_s * real_arm.CONTROL_HZ)):
        arm.send(arm.cmd)
        arm.tick()


def grip_turn(arm, p, plane, angle, wrist=None, snap=None):
    """A round knob gripped and twisted: the gripper straight down its axis, jaws open around it, closed, the wrist
    rolled by angle (radians), opened, lifted. The jaws close on the knob about where the roll axis runs, so the roll
    turns it. The jaw tips go GRIP_FLOOR over the panel. With wrist, it first looks from above, finds the knob's round
    top (touch.locate, as a button of the knob's size) and moves over it, up to GRIP_LOOKS times."""
    import copy
    import segmodels
    import touch
    n, o = plane[:3, 2], plane[:3, 3]
    r, top = min(p.size[:2]) / 2, max((p.pos - o) @ n, p.size[2])  # the knob's radius, and its top over the panel
    axis = p.pos - ((p.pos - o) @ n) * n - (SHIFT - (SHIFT @ n) * n)  # on the panel; a press's correction taken off
    up = np.cross(n, np.cross([0.0, 0.0, 1.0], n))
    axis += GRIP_UPHILL * up / np.linalg.norm(up)
    label, q = f"grip {p.id}", arm.cmd.copy()
    q[4] = arm.home_q[4]
    seen = copy.deepcopy(p)
    seen.kind, seen.meta = "button", {**p.meta, "radius": r}
    seen.size = np.array([2 * r, 2 * r, top])

    def place(axis, q):  # the tip's target so the knob's axis sits midway between the open jaws, GRIP_FLOOR up
        c = axis + GRIP_FLOOR * n
        for _ in range(3):
            arm.ik.fk(q)
            R = arm.ik.d.xmat[arm.ik.m.body("gripper").id].reshape(3, 3)
            target = c - GRIP_MID * R[:, 0]
            q, ok, err, _ = arm.ik.solve(target, -n, q)
        if not ok:
            raise RuntimeError(f"{label}: out of reach ({err * 1000:.0f} mm)")
        return target, q

    gripper(arm, GRIP_OPEN)
    for k in range(GRIP_LOOKS if wrist else 1):
        target, q = place(axis, q)
        _, bias = affordances._approach(arm, target + GRIP_ABOVE * n, -n, label, q)
        if snap:
            snap()
        if not wrist:
            break
        seen.T = seen.T.copy()
        seen.T[:3, 3] = axis + top * n
        pos, why = touch.locate(wrist.capture(), seen, plane, segmodels.sam_boxes())
        if pos is None:
            print(f"  look {k}: {why}")
            break
        move = (pos - ((pos - o) @ n) * n) - axis
        print(f"  look {k}: the knob is {np.linalg.norm(move) * 1000:.1f} mm from where the grip aims")
        axis = axis + move
        if np.linalg.norm(move) < 0.001:
            break
    arm.status = f"{label}: down"
    affordances._line(arm, target, -n, 0.02, bias)
    for _ in range(50):  # the arm trails the command at the bottom; closed early, the jaws hovered over the knob
        if np.linalg.norm(arm.tip_pose()[0] - target) < 0.0015:
            break
        arm.send(arm.cmd)
        arm.tick()
    arm.bus.sync_write("Torque_Limit", {"gripper": 1000}, normalize=False)  # at LeRobot's 500 the knob slipped
    gripper(arm, 0.0)
    if snap:
        snap()  # the jaws closed on the knob, or not
    arm.status = f"{label}: turn"
    dq = np.zeros(5)
    dq[4] = angle
    skills.move_joints(arm, arm.cmd + dq)
    gripper(arm, GRIP_OPEN, 0.4)
    arm.bus.sync_write("Torque_Limit", {"gripper": 500}, normalize=False)
    arm.status = f"{label}: up"
    affordances._line(arm, arm.tip_pose()[0] + GRIP_ABOVE * n, -n, 0.03, bias)
    gripper(arm, 0.0, 0.3)
    return {"verdict": "ask the operator", "stop": "done"}


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
