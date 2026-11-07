"""Tell a jammed gearbox from a stuck position sensor or a dead motor: command a 100-step move for one second and
log position, load and current while the motor tries. Loose motors only.

    python strain_test.py COM10 1 2     # motor 1, then motor 2 as a control

Present_Load is in 0.1% of full torque (sign = direction). Present_Current is in units of about 6.5 mA (the
STS3215's figure; not checked for the RobiServo-01), with bit 15 as its direction, decoded here as a minus sign.
"""
import sys
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

port, ids = sys.argv[1], [int(i) for i in sys.argv[2:]]
motors = {f"id{i}": Motor(i, "sts3215", MotorNormMode.RANGE_M100_100) for i in ids}
bus = SerialMotorsBus(port=port, motors=motors)
bus.connect(handshake=False)
try:
    for name in motors:
        pos = bus.read("Present_Position", name, normalize=False)
        out = pos + 100 if pos + 100 < 4096 else pos - 100
        print(f"{name}: at {pos}, told to go to {out}. Watch and listen.")
        bus.enable_torque(name)
        bus.write("Goal_Position", name, out, normalize=False)
        for _ in range(10):
            time.sleep(0.1)
            p = bus.read("Present_Position", name, normalize=False)
            load = bus.read("Present_Load", name, normalize=False)
            cur = bus.read("Present_Current", name, normalize=False)
            cur = -(cur - 32768) if cur >= 32768 else cur  # bit 15 is the direction, not part of the value
            print(f"    position {p:5d}   load {load:5d} ({load / 10:.0f}% torque)   current {cur:4d} (~{cur * 6.5:.0f} mA)")
        bus.write("Goal_Position", name, pos, normalize=False)
        time.sleep(0.5)
        bus.disable_torque(name)
        print(f"{name}: torque off\n")
finally:
    try:
        bus.disable_torque()
    except Exception:
        pass
    bus.disconnect(disable_torque=False)
