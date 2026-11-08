"""The first script to run on the built arm: each joint in the model's frame (degrees) next to its raw encoder steps,
and the fingertip's position by forward kinematics, so the joint mapping in real_arm.py can be checked by posing the arm
by hand. It turns torque off on every motor as it connects, so an arm that was holding drops: it asks you to support
the arm first. Torque then stays off, so the arm is limp, unless --move or --noise.

    python tools/arm_check.py COM5 CAL.json                       # 5 lines a second until Ctrl+C
    python tools/arm_check.py COM5 CAL.json --move elbow_flex     # asks, then 5 deg and back at about 2.5 deg/s
    python tools/arm_check.py COM5 CAL.json --move elbow_flex --deg 30 --speed 60   # further and faster
    python tools/arm_check.py COM5 CAL.json --noise               # asks, then the force estimate's noise at rest

CAL.json is lerobot-calibrate's file, ~/.cache/huggingface/lerobot/calibration/robots/so_follower/<robot.id>.json.
What to look for is in system-1/sim/docs/real-arm.md: in short, LeRobot's calibration pose reads near 0 on every joint with the tip
near (416, 0, 227) mm, and each joint's reading rises when it moves the way POSITIVE says.
"""
import argparse
import os
import sys

import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import real_arm  # noqa: E402
from rig import ARM_JOINTS, CONTROL_HZ, SafetyStop  # noqa: E402

# Which way each joint's reading rises, from the model at its zero pose (x forward, y left, z up)
POSITIVE = {"shoulder_pan": "turns the arm to its right (clockwise seen from above)",
            "shoulder_lift": "tilts the upper arm forward, toward the desk",
            "elbow_flex": "folds the forearm down",
            "wrist_flex": "tips the gripper down",
            "wrist_roll": "rolls the gripper clockwise, seen from behind the arm"}
SHORT = ("pan", "lift", "elbow", "wflex", "roll")
SPEED_DEG_S = 2.5  # --move's default
MAX_DEG = 90
MAX_SPEED_DEG_S = 90  # the move's cosine profile peaks at pi/2 times this, under RealArm's MAX_STEP_RAD a tick
EVERY = CONTROL_HZ // 5  # ticks between printed lines
NOISE_S = 5  # how long --noise logs the estimate at each pose
NOISE_TIPS = [(0.18, 0.0, 0.12), (0.28, 0.0, 0.12), (0.20, 0.18, 0.12)]  # close in, stretched out, to the left (m)
NOISE_SPEED_DEG_S = 10


def row(arm):
    tip = arm.tip_pose()[0] * 1000
    joints = "  ".join(f"{s} {d:+6.1f} ({r:4d})" for s, d, r in zip(SHORT, np.degrees(arm.read_q()), arm.pos))
    return f"{joints}   tip {tip[0]:4.0f} {tip[1]:+4.0f} {tip[2]:4.0f} mm"


def watch(arm, rows):
    print("Torque is off: pose the arm by hand. Each line: joint, degrees in the model's frame, (raw steps). Ctrl+C stops.")
    try:
        for n in range(rows or 10 ** 9):
            for _ in range(EVERY):
                arm.tick()
            print(row(arm), flush=True)
    except KeyboardInterrupt:
        pass


def move(arm, joint, deg, speed, ask):
    i = ARM_JOINTS.index(joint)
    end = arm.read_q()
    end[i] = np.clip(end[i] + np.radians(deg), arm.ik.lo[i], arm.ik.hi[i])  # as send() clips it
    tip = arm.ik.fk(end)[0] * 1000
    print(f"--move turns torque on for the five arm joints, which then hold this pose, moves {joint} {deg:+g} deg "
          f"({POSITIVE[joint] if deg > 0 else 'the other way'}) and back at about {speed:g} deg/s, then waits "
          f"for you before torque goes off and the arm goes limp. Ctrl+C stops the move and the arm holds.\n{row(arm)}\n"
          f"At the far end {joint} reads {np.degrees(end[i]):+.1f} (its limits are {np.degrees(arm.ik.lo[i]):+.0f} to "
          f"{np.degrees(arm.ik.hi[i]):+.0f}) and the tip is at {tip[0]:.0f} {tip[1]:+.0f} {tip[2]:.0f} mm")
    if ask("Is the arm clear to move, and held or resting where it would fall? Type yes to go: ").strip() != "yes":
        print("Not moved.")
        return
    arm.enable(confirm=True)
    q0, n, peak = arm.cmd.copy(), max(1, round(abs(deg) / speed * CONTROL_HZ)), 0.0
    try:
        for a, b in ((0, deg), (deg, 0)):
            for k in range(1, n + 1):
                q = q0.copy()
                q[i] += np.radians(a + (b - a) * (0.5 - 0.5 * np.cos(np.pi * k / n)))
                arm.send(q)
                arm.tick()
                peak = max(peak, np.degrees(arm.read_q()[i] - q0[i]), key=abs)
                if k % EVERY == 0:
                    print(row(arm), flush=True)
        for _ in range(CONTROL_HZ):
            arm.send(q0)
            arm.tick()
    except (SafetyStop, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
        print(f"Stopped: {str(e) or 'Ctrl+C'}")
    else:
        print(f"Furthest: {joint} got to {peak:+.2f} deg of the {np.degrees(end[i] - q0[i]):+.2f} asked. "
              f"Back: {joint} reads {np.degrees(arm.read_q()[i] - q0[i]):+.2f} deg off its start (soft servos stop "
              f"short and sag). Force estimate at rest {np.linalg.norm(arm.tip_force_vec()):.1f} N (untared: well "
              f"over {arm.noise_n:g} N means the model's masses or real_arm.SERVO_NM_PER_RAD are off)")
    ask("Hold the arm, then press Enter: torque goes off. ")


def _goto(arm, q):
    """A smooth joint-space move from the current command to q at about NOISE_SPEED_DEG_S."""
    q0 = arm.cmd.copy()
    n = max(1, round(np.degrees(np.abs(q - q0).max()) / NOISE_SPEED_DEG_S * CONTROL_HZ))
    for k in range(1, n + 1):
        arm.send(q0 + (q - q0) * (0.5 - 0.5 * np.cos(np.pi * k / n)))
        arm.tick()


def noise(arm, ask):
    start = arm.read_q()
    poses = []
    for tip in NOISE_TIPS:
        q, ok, err, _ = arm.ik.solve(np.array(tip), np.array([0.7, 0.0, -0.7]), start)
        if ok:
            poses.append((tip, q))
        else:
            print(f"Skipping {tip}: out of reach ({err * 1000:.0f} mm short)")
    turn = max(np.degrees(np.abs(q - start).max()) for _, q in poses)
    print(f"--noise turns torque on for the five arm joints, then moves the arm itself to {len(poses)} poses 12 cm "
          f"above the desk (no joint turns more than {turn:.0f} deg, at about {NOISE_SPEED_DEG_S} deg/s). At each it "
          f"waits 1 s, zeroes the force estimate as a guarded move does and logs it for {NOISE_S} s. Then it comes back "
          f"here and waits for you before torque goes off. Ctrl+C stops and the arm holds.\n{row(arm)}")
    if ask("Is the space around the arm clear? Type yes to go: ").strip() != "yes":
        print("Not run.")
        return
    arm.enable(confirm=True)
    results = []
    try:
        for tip, q in poses:
            _goto(arm, q)
            for _ in range(CONTROL_HZ):
                arm.send(q)
                arm.tick()
            arm.tare()
            axial, total = [], []
            for _ in range(NOISE_S * CONTROL_HZ):
                arm.send(q)
                arm.tick()
                axial.append(arm.tip_force())
                total.append(np.linalg.norm(arm.tip_force_vec()))
            results.append((tip, axial, total))
            print(f"At {tip}: along the probe mean {np.mean(axial):.2f}, std {np.std(axial):.2f}, max {np.max(axial):.2f} "
                  f"N; magnitude mean {np.mean(total):.2f}, std {np.std(total):.2f}, max {np.max(total):.2f} N", flush=True)
        _goto(arm, start)
    except (SafetyStop, KeyboardInterrupt) as e:  # torque stays on, so the arm holds until the question below
        print(f"Stopped: {str(e) or 'Ctrl+C'}")
    if results:
        print(f"The rig assumes {arm.noise_n:g} N (rig.SENSED_NOISE_N): a touch takes 2x that along the probe as "
              f"contact, and skips buttons while that is over their 1.5 N spring")
    ask("Hold the arm, then press Enter: torque goes off. ")


def main(argv=None, bus=None, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("port", help="the follower's serial port, e.g. COM5")
    ap.add_argument("calibration", help="lerobot-calibrate's JSON file for this arm")
    ap.add_argument("--move", choices=ARM_JOINTS, help="nudge this joint and back, after asking")
    ap.add_argument("--deg", type=float, default=5.0, help=f"how far --move goes, at most {MAX_DEG} (default 5)")
    ap.add_argument("--speed", type=float, default=SPEED_DEG_S,
                    help=f"--move's average speed in deg/s, at most {MAX_SPEED_DEG_S} (default {SPEED_DEG_S:g})")
    ap.add_argument("--noise", action="store_true", help=f"log the force estimate at rest for {NOISE_S} s, after asking")
    ap.add_argument("--rows", type=int, default=0, help="stop after this many lines (default: Ctrl+C)")
    args = ap.parse_args(argv)
    if not 0 < abs(args.deg) <= MAX_DEG:
        ap.error(f"--deg must be between -{MAX_DEG} and {MAX_DEG}, and not 0")
    if not 0 < args.speed <= MAX_SPEED_DEG_S:
        ap.error(f"--speed must be over 0 and at most {MAX_SPEED_DEG_S}")
    ask("Connecting turns torque off on every motor, and the arm goes limp. Support it, then press Enter: ")
    with real_arm.RealArm(bus or real_arm.make_bus(args.port, args.calibration)) as arm:
        for j, mid in zip(ARM_JOINTS, arm.mid):
            print(f"{j:14s} LeRobot's zero (range middle) {mid:6.1f} steps, P gain {arm.bus.read('P_Coefficient', j)}; "
                  f"reading rises as it {POSITIVE[j]}")
        if args.move:
            move(arm, args.move, args.deg, args.speed, ask)
        elif args.noise:
            noise(arm, ask)
        else:
            watch(arm, args.rows)


if __name__ == "__main__":
    main()
