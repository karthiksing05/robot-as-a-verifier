"""Log the servo force estimate's raw inputs while the arm creeps through empty air the way a touch does, so its model
(stiffness, friction) can be fitted offline: in free air the true force is zero, so whatever the estimate reads is
model error. Writes creep_log.npz in the current folder.

    python tools/creep_log.py COM11 CAL.json

You rest the fixed jaw's tip on a surface (to know where it is), then hold the arm about 10 cm above it. After yes the arm
does five creeps 4 cm long, leaning 30 deg forward, all at least 5 cm over the surface, then comes back.
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

CLEAR_M = 0.05      # lowest point of every creep over the limp surface reading (which reads 1.5-2.5 cm low)
CREEP_M = 0.04
SPOTS_M = [(0, 0), (0.04, 0), (-0.04, 0), (0, 0.04), (0, -0.04)]
SPEEDS = (0.002, 0.02)  # touch creep and approach speed, m/s


def main(argv=None, bus=None, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port")
    ap.add_argument("calibration")
    args = ap.parse_args(argv)
    N = place_check.N
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        ask("Rest the fixed jaw's tip on the surface, jaws closed. Hold still and press Enter: ")
        surf = place_check.tip_now(arm)
        ask("Lift the arm about 10 cm and tip the gripper forward a little. Hold it and press Enter: ")
        arm.tick()  # read_q() is the last tick's reading: this one is the lifted pose, not the surface
        rows = []
        print("Planned poses (tip mm; joints deg):")
        for k, (dx, dy) in enumerate(SPOTS_M):
            low = surf + [dx, dy, 0] + CLEAR_M / N[2] * N
            pair, why = place_check.plan(arm, [(f"creep {k + 1} top", low + CREEP_M * N), (f"creep {k + 1} bottom", low)])
            if why:
                print(f"  creep {k + 1}: skipped, {why}")
                continue
            rows += pair
            for label, p, q, _ in pair:
                print(f"  {label:16s} tip {np.round(p * 1000)}  joints {np.round(np.degrees(q))}")
        if len(rows) < 6:
            print("Not moving: fewer than 3 creeps are in reach. Put the surface 20-28 cm in front of the base.")
            return
        if ask(f"The arm will creep {len(rows) // 2} times through empty air, at least 5 cm over the surface. Do the joint angles look "
               "sane, and is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        start = arm.read_q()
        log = {k: [] for k in ("t", "seg", "q", "cmd", "goal", "pos", "f_axial", "f_vec")}
        seg = 0
        try:
            for i in range(0, len(rows), 2):
                top, bottom = rows[i][2], rows[i + 1][2]
                skills.move_joints(arm, top)
                for speed in SPEEDS:
                    for a, b in ((top, bottom), (bottom, top)):
                        for _ in range(CONTROL_HZ):  # settle, then zero as a guarded move does
                            arm.send(a)
                            arm.tick()
                        arm.tare()
                        seg += 1
                        n = max(1, round(CREEP_M / speed * CONTROL_HZ))
                        for k in range(1, n + 1):
                            arm.send(a + (b - a) * k / n)
                            arm.tick()
                            for key, v in (("t", arm.d.time), ("seg", seg), ("q", arm.q), ("cmd", arm.cmd),
                                           ("goal", arm.goal), ("pos", arm.pos), ("f_axial", arm.tip_force()),
                                           ("f_vec", arm.tip_force_vec())):
                                log[key].append(np.copy(v))
                        print(f"  segment {seg}: {'down' if a is top else 'up'} at {speed * 1000:.0f} mm/s, estimate "
                              f"max {np.max(log['f_axial'][-n:]):.2f} N along the fingertip", flush=True)
            skills.move_joints(arm, start)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
            print(f"Stopped: {str(e) or 'Ctrl+C'}")
        if log["t"]:
            out = os.path.join(os.getcwd(), "creep_log.npz")
            np.savez(out, surface=surf, **{k: np.array(v) for k, v in log.items()})
            print("Wrote", out)
        ask("Hold the arm, then press Enter: torque goes off. ")


if __name__ == "__main__":
    main()
