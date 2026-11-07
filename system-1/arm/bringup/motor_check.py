"""Bring-up check for the six SO-101 follower servos, before the arm is built. Run it in the LeRobot environment.

    python motor_check.py COM5            # all six, daisy-chained
    python motor_check.py COM5 --only 3   # just the motor with id 3

For each motor: ask for its model number, read its position, then turn on torque, nudge it 100 encoder steps
(about 9 degrees) and back, and turn torque off. Only for loose motors with nothing attached: it knows nothing
about the arm's joint limits. Written against LeRobot's main branch (lerobot.motors.SerialMotorsBus).
"""
import argparse
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]  # ids 1-6
STEP = 100  # encoder steps; 4096 is one full turn

ap = argparse.ArgumentParser()
ap.add_argument("port", help="the COM port lerobot-find-port reported, e.g. COM5")
ap.add_argument("--only", type=int, choices=range(1, 7), help="check one motor id")
args = ap.parse_args()

ids = [args.only] if args.only else range(1, 7)
motors = {NAMES[i - 1]: Motor(i, "sts3215", MotorNormMode.RANGE_M100_100) for i in ids}
bus = SerialMotorsBus(port=args.port, motors=motors)
bus.connect(handshake=False)  # skip LeRobot's same-firmware check: we ping each motor ourselves below
try:
    for name, m in motors.items():
        model = bus.ping(name)
        if model is None:
            print(f"id {m.id} ({name}): NO ANSWER")
            continue
        pos = bus.read("Present_Position", name, normalize=False)
        print(f"id {m.id} ({name}): answers, model number {model}, position {pos}")
        out = pos + STEP if pos + STEP < 4096 else pos - STEP
        bus.enable_torque(name)
        for target in (out, pos):
            bus.write("Goal_Position", name, target, normalize=False)
            time.sleep(1.0)
            print(f"    told to go to {target}, now at {bus.read('Present_Position', name, normalize=False)}")
        bus.disable_torque(name)
finally:
    try:
        bus.disable_torque()
    except Exception:
        pass  # a motor that never answered can't be told anything
    bus.disconnect(disable_torque=False)
