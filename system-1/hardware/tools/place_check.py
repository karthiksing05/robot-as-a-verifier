"""Touch a flat surface at five spots and once more at the first, with the pipeline's own guarded touch (touch.touch),
straight down. On a flat surface every contact should read the same height: the spread is how well the arm places the
fingertip under load, the repeat is its repeatability, and the gap to the height read with the arm limp is the sag.

    python tools/place_check.py COM11 CAL.json

Put a flat, stiff surface (a riser at least 3 cm tall) in front of the arm. With torque off you rest the fixed jaw's
tip on its middle, then lift the arm a few cm and hold it there; after yes the arm holds itself and does the rest.
"""
import argparse
import os
import sys

import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import real_arm  # noqa: E402
import touch  # noqa: E402
from rig import CONTROL_HZ, SafetyStop  # noqa: E402

SPOTS_M = [(0, 0), (0.04, 0), (-0.04, 0), (0, 0.04), (0, -0.04), (0, 0)]  # around the middle, then the middle again
UP = np.array([0.0, 0.0, 1.0])
TILT = np.radians(30)  # straight down is out of the wrist's reach at 26 cm; 20-40 deg reaches every spot
N = np.array([-np.sin(TILT), 0.0, np.cos(TILT)])  # touches come in along -N, leaning forward
MAX_TURN_DEG = 90  # refuse a plan that turns any joint further than this from where the arm is


def plan(arm, points):
    """Joint angles for each (label, tip position), pointing along -N, or the first that the IK can't reach."""
    rows, q = [], arm.read_q()
    for label, p in points:
        q, ok, err, _ = arm.ik.solve(p, -N, q)
        rows.append((label, p, q, err))
        if not ok:
            return rows, f"{label} is out of reach ({err * 1000:.0f} mm short)"
    turn = max(np.degrees(np.abs(r[2] - arm.read_q()).max()) for r in rows)
    return rows, (f"a joint would turn {turn:.0f} deg from here (limit {MAX_TURN_DEG})" if turn > MAX_TURN_DEG else "")


def tip_now(arm):
    pts = []
    for _ in range(CONTROL_HZ // 2):
        arm.tick()
        pts.append(arm.tip_pose()[0])
    return np.mean(pts, axis=0)


def main(argv=None, bus=None, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port")
    ap.add_argument("calibration")
    args = ap.parse_args(argv)
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        ask("Rest the fixed jaw's tip on the middle of the surface, gripper pointing down, jaws closed. Hold still and "
            "press Enter: ")
        mid = tip_now(arm)
        print(f"Surface middle with the arm limp: {np.round(mid * 1000, 1)} mm")
        ask("Lift the arm 3 to 5 cm and tip the gripper forward a little, not folded tight. Hold it and press Enter: ")
        floor = arm.workspace[2][0] + 0.002  # the creep may not aim below the workspace floor
        bottom = max(-0.05, (floor - mid[2]) / N[2] - 0.03)
        points = [("search start", mid + (0.03 + touch.skills.APPROACH_M) * N), ("search end", mid + (0.03 + bottom) * N)]
        points += [(f"spot {k + 1}", mid + [dx, dy, 0] + touch.skills.APPROACH_M * N) for k, (dx, dy) in enumerate(SPOTS_M)]
        rows, why = plan(arm, points)
        print("Planned poses (tip mm; joints deg: pan lift elbow wflex roll):")
        for label, p, q, err in rows:
            print(f"  {label:12s} tip {np.round(p * 1000)}  joints {np.round(np.degrees(q))}")
        if why:
            print(f"Not moving: {why}.")
            return
        if ask(f"The arm will touch the surface {len(SPOTS_M) + 1} times, leaning {np.degrees(TILT):.0f} deg forward, "
               f"slowly. Do those joint angles look sane, and is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        hits = []
        try:
            # The limp reading isn't where the arm under torque finds the surface (the offsets were fitted under load),
            # so the first touch creeps a long way down from 3 cm over it, and the rest start from where it landed
            s, why = touch.touch(arm, mid + 0.03 * N, N, top=0.015, bottom=bottom, label="place_check")
            if s is None:
                raise SafetyStop(f"no surface found near the middle: {why}")
            print(f"Surface found under torque at z {s[2] * 1000:.1f} mm ({(s[2] - mid[2]) * 1000:+.1f} vs limp)")
            mid = np.r_[mid[:2], s[2]]
            for dx, dy in SPOTS_M:
                at = mid + np.array([dx, dy, 0.0])
                s, why = touch.touch(arm, at, N, top=0.01, bottom=-0.015, label="place_check")
                print(f"  at {np.round(at[:2] * 1000)} mm: " + (f"contact z {s[2] * 1000:6.1f} mm "
                      f"({(s[2] - mid[2]) * 1000:+.1f} vs the first touch)" if s is not None else why), flush=True)
                hits.append(s)
        except (SafetyStop, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {str(e) or 'Ctrl+C'}")
        z = np.array([s[2] for s in hits if s is not None]) * 1000
        if len(z) > 1:
            print(f"Contacts {len(z)}/{len(SPOTS_M)}: spread {np.ptp(z):.1f} mm, mean {np.mean(z) - mid[2] * 1000:+.1f} mm "
                  f"vs the first touch" + (f", repeat at the middle {abs(z[-1] - z[0]):.1f} mm" if hits[0] is not None
                                            and hits[-1] is not None else ""))
        ask("Hold the arm, then press Enter: torque goes off. ")


if __name__ == "__main__":
    main()
