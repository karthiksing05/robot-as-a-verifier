"""Print one motor's position 5 times a second with its torque off, so you can turn its shaft by hand and watch.

    python watch_position.py COM10 1            # motor id 1, for 20 s
    python watch_position.py COM10 1 --seconds 40

A working position sensor follows the shaft: about 11 steps per degree, 4096 per turn.
"""
import argparse
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("id", type=int)
ap.add_argument("--seconds", type=float, default=20)
args = ap.parse_args()

bus = SerialMotorsBus(port=args.port, motors={"m": Motor(args.id, "sts3215", MotorNormMode.RANGE_M100_100)})
bus.connect(handshake=False)
try:
    bus.disable_torque("m")
    print(f"motor {args.id}: torque off. Turn its shaft by hand now.")
    end = time.time() + args.seconds
    while time.time() < end:
        print(f"  position {bus.read('Present_Position', 'm', normalize=False)}", flush=True)
        time.sleep(0.2)
finally:
    bus.disconnect(disable_torque=False)
