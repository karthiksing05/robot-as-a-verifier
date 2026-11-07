"""How far one servo stops short of its goal at different P gains: the dead zone behind arm_check's short moves.

    python p_gain_sweep.py COM10 [motor_id] [gains...]     # default: motor 3, gains 16 32 64 160

For each gain: torque on holding where it is, small steps (+5, +10, +20 steps and back) to find the smallest error it
corrects, then arm_check's move (+57 steps, 5 deg, ramped at 2.5 deg/s at 50 Hz) and back. Run it on a loose motor.
The motor's own P is put back at the end and torque is turned off.
"""
import sys
import time

import numpy as np
from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

port = sys.argv[1]
mid = int(sys.argv[2]) if len(sys.argv) > 2 else 3
gains = [int(g) for g in sys.argv[3:]] or [16, 32, 64, 160]
M = "m"
bus = SerialMotorsBus(port, {M: Motor(mid, "sts3215", MotorNormMode.DEGREES)})
bus.connect()


def pos():
    return int(bus.read("Present_Position", M, normalize=False))


def goal(g):
    bus.write("Goal_Position", M, int(g), normalize=False)


def hold(seconds):
    """positions over a hold, sampled at 50 Hz"""
    out, t_end = [], time.time() + seconds
    while time.time() < t_end:
        out.append(pos())
        time.sleep(0.02)
    return np.array(out)


def ramp(a, b, deg_per_s=2.5):
    n = max(1, int(abs(b - a) * 360 / 4096 / deg_per_s * 50))
    for k in range(1, n + 1):
        goal(round(a + (b - a) * k / n))
        time.sleep(0.02)


p0 = int(bus.read("P_Coefficient", M, normalize=False))
print(f"motor {mid}: P {p0}, I {int(bus.read('I_Coefficient', M, normalize=False))}, "
      f"D {int(bus.read('D_Coefficient', M, normalize=False))}")
try:
    for p in gains:
        bus.disable_torque(M)
        bus.write("P_Coefficient", M, p, normalize=False)
        start = pos()
        goal(start)
        bus.enable_torque(M)
        hold(0.5)
        start = pos()
        goal(start)
        steps = []
        for d in (5, 10, 20):  # small steps: does it close an error this size?
            goal(start + d)
            a = hold(1.0)[-10:].mean()
            goal(start)
            b = hold(1.0)[-10:].mean()
            steps.append(f"+{d}: reached {a - start:+5.1f}, back {b - start:+5.1f}")
        start = pos()
        goal(start)
        ramp(start, start + 57)
        up = hold(1.5)
        ramp(start + 57, start)
        down = hold(1.5)
        print(f"P {p:3d} | small steps (encoder steps): " + " | ".join(steps))
        print(f"      | 5 deg move: reached {up[-10:].mean() - start:+5.1f} of +57 (short by {57 - (up[-10:].mean() - start):.1f}), "
              f"back to {down[-10:].mean() - start:+5.1f} of 0 | jitter while holding {up.std():.2f} steps", flush=True)
finally:
    bus.disable_torque(M)
    bus.write("P_Coefficient", M, p0, normalize=False)
    print(f"P put back to {p0}, torque off")
    bus.disconnect(disable_torque=True)
