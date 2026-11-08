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
        if mid[2] < arm.workspace[2][0] + 0.02:
            print(f"That is only {(mid[2] - arm.workspace[2][0]) * 1000:.0f} mm over the workspace floor: use a taller "
                  f"riser, or touches below it are refused.")
        ask("Lift the arm 3 to 5 cm straight up and hold it there, not folded tight. Press Enter: ")
        if ask(f"The arm will touch the surface {len(SPOTS_M)} times, 4 cm apart, slowly. Is it clear? Type yes to "
               f"go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        hits = []
        try:
            for dx, dy in SPOTS_M:
                at = mid + np.array([dx, dy, 0.0])
                s, why = touch.touch(arm, at, UP, top=0.015, bottom=-0.02, label="place_check")
                print(f"  at {np.round(at[:2] * 1000)} mm: " + (f"contact z {s[2] * 1000:6.1f} mm "
                      f"({(s[2] - mid[2]) * 1000:+.1f} vs limp)" if s is not None else why), flush=True)
                hits.append(s)
        except (SafetyStop, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {str(e) or 'Ctrl+C'}")
        z = np.array([s[2] for s in hits if s is not None]) * 1000
        if len(z) > 1:
            print(f"Contacts {len(z)}/{len(SPOTS_M)}: spread {np.ptp(z):.1f} mm, mean {np.mean(z) - mid[2] * 1000:+.1f} mm "
                  f"vs the limp reading" + (f", repeat at the middle {abs(z[-1] - z[0]):.1f} mm" if hits[0] is not None
                                            and hits[-1] is not None else ""))
        ask("Hold the arm, then press Enter: torque goes off. ")


if __name__ == "__main__":
    main()
