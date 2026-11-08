"""Press a surface by stall instead of force: the arm moves the fingertip toward it at a steady speed and stops when the
tip falls STALL_M further behind its command than it did moving freely. The servo force estimate drifts several N on
any downward move, but in free air this lag grew at most 2 mm at 20 mm/s (creep_log, Nov 7), and against something
solid it grows at the full commanded speed. Presses five spots on a flat surface, then the first again, so the stall
heights also show placement accuracy and repeatability.

    python tools/press_check.py COM11 CAL.json

You rest the fixed jaw's tip on the surface (torque off), then lift the arm about 10 cm; after yes it does the rest.
"""
import argparse
import os
import sys

import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "tools"), os.path.join(HARDWARE, "..", "core")]
import place_check  # noqa: E402
import real_arm  # noqa: E402
import skills  # noqa: E402
from rig import CONTROL_HZ, SafetyStop  # noqa: E402

SPEED = 0.015       # m/s along the press: free-air tracking was clean at 20 mm/s and stick-slipped at 2
STALL_M = 0.004     # lag growth past the free-air baseline that counts as pressed (free air: up to 2 mm at 20 mm/s)
BASELINE_S = 0.5    # moving this long first, so the start-up lag is over before the baseline is taken
START_M = 0.06      # start this far over the limp surface reading (that reading is 1.5-2.5 cm low)
UP = np.array([0.0, 0.0, 1.0])  # presses move straight down, with the gripper leaning TILT for reach: no sideways push to slip
SPOTS_M = [(0, 0), (0.04, 0), (-0.04, 0), (0, 0.04), (0, -0.04), (0, 0)]


LEANS_DEG = range(0, 45, 5)  # a leaning jaw tip skids on a smooth top, so each press leans as little as reach allows


def least_lean(arm, top, end, seed):
    """Joint angles at top and end with the gripper leaned as little as both allow, outward from the base: (q_top,
    q_end, lean deg), or Nones."""
    out = np.r_[top[:2] / np.linalg.norm(top[:2]), 0.0]
    for lean in LEANS_DEG:
        axis = np.sin(np.radians(lean)) * out - np.cos(np.radians(lean)) * UP
        q0, ok0, _, _ = arm.ik.solve(top, axis, seed)
        q1, ok1, _, _ = arm.ik.solve(end, axis, q0)
        if ok0 and ok1:
            return q0, q1, lean
    return None, None, None


def press(arm, q_start, q_end):
    """Move from q_start toward q_end along the joint-space line at SPEED (measured at the tip) until the lag along
    the motion grows STALL_M past its value after BASELINE_S. Returns (tip at the stall, lag growth) or (None, why)."""
    p0, p1 = arm.ik.fk(q_start)[0], arm.ik.fk(q_end)[0]
    u = (p1 - p0) / np.linalg.norm(p1 - p0)
    n = max(1, round(np.linalg.norm(p1 - p0) / SPEED * CONTROL_HZ))
    base, run = None, 0
    for k in range(1, n + 1):
        arm.send(q_start + (q_end - q_start) * k / n)
        arm.tick()
        lag = (arm.ik.fk(arm.cmd)[0] - arm.tip_pose()[0]) @ u
        if k == round(BASELINE_S * CONTROL_HZ):
            base = lag
        elif base is not None:
            run = run + 1 if lag - base > STALL_M else 0
            if run >= 3:  # three ticks in a row, so one encoder flicker can't end a press
                return arm.tip_pose()[0], lag - base
    return None, f"no stall within {np.linalg.norm(p1 - p0) * 1000:.0f} mm"


def main(argv=None, bus=None, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port")
    ap.add_argument("calibration")
    args = ap.parse_args(argv)
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        ask("Rest the fixed jaw's tip on the middle of the surface, jaws closed. Hold still and press Enter: ")
        mid = place_check.tip_now(arm)
        ask("Lift the arm about 10 cm and tip the gripper forward a little. Hold it and press Enter: ")
        arm.tick()  # read_q() is the last tick's reading: this one is the lifted pose, not the surface
        floor = arm.workspace[2][0] + 0.002
        depth = min(START_M, mid[2] + START_M - floor)  # ends at the limp reading (a missed stall stays under ~12 N), never below the floor
        rows, now = [], arm.read_q()
        print("Planned presses (tip mm; lean from vertical; joints deg):")
        for k, (dx, dy) in enumerate(SPOTS_M):
            top = mid + [dx, dy, 0] + START_M * UP
            q0, q1, lean = least_lean(arm, top, top - depth * UP, now)
            if q0 is None:
                print(f"Not moving: press {k + 1} is out of reach at any lean up to {LEANS_DEG[-1]} deg.")
                return
            rows += [(f"press {k + 1} start", top, q0), (f"press {k + 1} end", top - depth * UP, q1)]
            print(f"  press {k + 1}: tip {np.round(top * 1000)} down {depth * 1000:.0f} mm, lean {lean} deg, "
                  f"joints {np.round(np.degrees(q0))}")
        turn = max(np.degrees(np.abs(r[2] - now).max()) for r in rows)
        if turn > place_check.MAX_TURN_DEG:
            print(f"Not moving: a joint would turn {turn:.0f} deg from here (limit {place_check.MAX_TURN_DEG}).")
            return
        if ask(f"The arm will press the surface {len(SPOTS_M)} times straight down at {SPEED * 1000:.0f} mm/s, stopping "
               f"when it stalls. Do the joint angles look sane, and is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        start = arm.read_q()
        hits = []
        try:
            for i in range(0, len(rows), 2):
                q0, q1 = rows[i][2], rows[i + 1][2]
                skills.move_joints(arm, q0)
                for _ in range(CONTROL_HZ // 2):
                    arm.send(q0)
                    arm.tick()
                tip, info = press(arm, q0, q1)
                label = rows[i][0].replace(" start", "")
                print(f"  {label}: " + (f"stalled at z {tip[2] * 1000:6.1f} mm (lag grew {info * 1000:.1f} mm)"
                                        if tip is not None else info), flush=True)
                hits.append(tip)
                skills.move_joints(arm, q0)  # back up to the start
            skills.move_joints(arm, start)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {str(e) or 'Ctrl+C'}")
        z = np.array([h[2] for h in hits if h is not None]) * 1000
        if len(z) > 1:
            print(f"Stalls {len(z)}/{len(SPOTS_M)}: heights spread {np.ptp(z):.1f} mm, mean {np.mean(z):.1f} mm"
                  + (f", repeat at the middle {abs(hits[-1][2] - hits[0][2]) * 1000:.1f} mm"
                     if hits[0] is not None and hits[-1] is not None and len(hits) == len(SPOTS_M) else ""))
        ask("Hold the arm, then press Enter: torque goes off. ")


if __name__ == "__main__":
    main()
