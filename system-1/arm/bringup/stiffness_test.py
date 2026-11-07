"""Servo stiffness at LeRobot's gains, from a known weight on a lever. One loose motor, body held still.

    python stiffness_test.py COM10 2 --mass 0.52

Each trial asks where the weight hangs (cm from the shaft centre), then measures how far the lever gives.
Run trials at two or more distances: the slope across them cancels the servo's small dead zone.
The sim assumes 18 N.m/rad (LeRobot's P=16 on a 12 V STS3215) or 36 (factory gain).
"""
import argparse
import math
import statistics
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

TICK = 2 * math.pi / 4096  # radians per encoder count

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("id", type=int)
ap.add_argument("--mass", type=float, required=True, help="the hanging weight in kg")
args = ap.parse_args()

bus = SerialMotorsBus(port=args.port, motors={"m": Motor(args.id, "sts3215", MotorNormMode.RANGE_M100_100)})
bus.connect(handshake=False)


def hold(seconds=2.0):
    """Mean position, load and current over a short window."""
    p, l, c = [], [], []
    end = time.time() + seconds
    while time.time() < end:
        p.append(bus.read("Present_Position", "m", normalize=False))
        l.append(bus.read("Present_Load", "m", normalize=False))
        cur = bus.read("Present_Current", "m", normalize=False)
        c.append(-(cur - 32768) if cur >= 32768 else cur)  # bit 15 is the direction
        time.sleep(0.02)
    return statistics.mean(p), statistics.mean(l), statistics.mean(c)


trials = []
try:
    with bus.torque_disabled():  # LeRobot's SO-101 gains (config_so_follower.py)
        bus.write("P_Coefficient", "m", 16)
        bus.write("I_Coefficient", "m", 0)
        bus.write("D_Coefficient", "m", 32)
    bus.disable_torque("m")
    input(f"Motor {args.id}: torque off, gain set to LeRobot's P=16. Hold the lever level by hand, then press Enter.")
    bus.write("Goal_Position", "m", bus.read("Present_Position", "m", normalize=False), normalize=False)
    bus.enable_torque("m")
    time.sleep(1.0)
    while True:
        r = input("\nWeight off the lever. Distance you'll hang it at, in cm (or q to finish): ").strip()
        if r.lower().startswith("q"):
            break
        r_m = float(r) / 100
        p0, l0, c0 = hold()
        input(f"  Hang the {args.mass} kg weight at {r} cm, let it settle, then press Enter.")
        time.sleep(1.0)
        p1, l1, c1 = hold()
        torque = args.mass * 9.81 * r_m
        give = abs(p1 - p0)
        trials.append((torque, give, l1 - l0, c1 - c0))
        print(f"  torque {torque:.3f} N.m: lever gave {give:.1f} counts ({give * TICK * 180 / math.pi:.2f} deg), "
              f"load {l0:.0f} -> {l1:.0f}, current {c0:.0f} -> {c1:.0f}")
        if give > 0:
            print(f"  stiffness from this trial alone: {torque / (give * TICK):.1f} N.m/rad (includes the dead zone)")
        input("  Take the weight off, then press Enter.")
finally:
    try:
        bus.disable_torque("m")
    except Exception:
        pass
    bus.disconnect(disable_torque=False)

if len({round(t[0], 4) for t in trials}) >= 2:
    tq = [t[0] for t in trials]
    rad = [t[1] * TICK for t in trials]
    mt, mr = statistics.mean(tq), statistics.mean(rad)
    slope = sum((a - mt) * (b - mr) for a, b in zip(tq, rad)) / sum((a - mt) ** 2 for a in tq)  # rad per N.m
    dz = (mr - slope * mt) / TICK
    print(f"\nStiffness from the slope across {len(trials)} trials: {1 / slope:.1f} N.m/rad, dead zone about {dz:.1f} counts")
    lt = [t[2] for t in trials]
    ml = statistics.mean(lt)
    load_per_nm = sum((a - mt) * (b - ml) for a, b in zip(tq, lt)) / sum((a - mt) ** 2 for a in tq)
    print(f"Present_Load changes by {load_per_nm:.0f} units per N.m (for servo-only force sensing)")
elif trials:
    print("\nRun at least two distances to get the slope.")
