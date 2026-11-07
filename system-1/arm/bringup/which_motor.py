"""Find the id of the one motor on the bus, then check it moves: for testing each motor and its cable on its own.

    python which_motor.py COM5

It looks for the motor at every baud rate the servo supports, prints its id, the joint that id is for, its position,
supply voltage and temperature, then turns torque on, nudges it 100 encoder steps (about 9 degrees) out and back, and
turns torque off. Connect one motor at a time, with nothing on its horn. It sets the P gain to RealArm's 160 first:
at LeRobot's 16 a loose motor barely moves (results.md).
"""
import argparse
import time

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

NAMES = {1: "shoulder_pan", 2: "shoulder_lift", 3: "elbow_flex", 4: "wrist_flex", 5: "wrist_roll", 6: "gripper"}
DEFAULT_BAUD = 1_000_000  # what lerobot-setup-motors leaves a motor at
SERVO_P = 160
STEP = 100  # encoder steps; 4096 is one full turn
TOL = 15    # steps: the RobiServo stops up to 5 steps short at P 160


def bus_for(port, motor_id):
    bus = SerialMotorsBus(port=port, motors={"m": Motor(motor_id, "sts3215", MotorNormMode.RANGE_M100_100)})
    bus.connect(handshake=False)
    return bus


def go(bus, target):
    """Goal to target, then wait up to 1.5 s for it. Returns (where it stopped, lowest voltage, peak |load|)."""
    bus.write("Goal_Position", "m", target, normalize=False)
    volts, load, end = [], 0, time.time() + 1.5
    while True:
        pos = bus.read("Present_Position", "m", normalize=False)
        volts.append(bus.read("Present_Voltage", "m", normalize=False) / 10)
        load = max(load, abs(bus.read("Present_Load", "m", normalize=False)))
        if abs(pos - target) <= TOL and len(volts) > 3 or time.time() > end:
            return pos, min(volts), load
        time.sleep(0.05)


def find(port):
    """(baud rate, {id: model number}) of whatever answers, trying the default rate first; (None, {}) if nothing does."""
    bus = bus_for(port, 1)
    try:
        d = bus._definition("m")
        for baud in sorted(d.baudrates, key=lambda b: (b != DEFAULT_BAUD, b != d.factory_baudrate, b)):
            bus.set_baudrate(baud)
            try:
                found = bus._scan(d)  # a broadcast ping to every id
            except (RuntimeError, ConnectionError):  # rustypot raises a timeout when nothing answers
                found = {}
            if found:
                return baud, found
        return None, {}
    finally:
        bus.disconnect(disable_torque=False)


ap = argparse.ArgumentParser()
ap.add_argument("port", help="the COM port lerobot-find-port reported, e.g. COM5")
args = ap.parse_args()

baud, found = find(args.port)
if not found:
    raise SystemExit("no motor answered at any baud rate: check the motor's power, its cable at both ends, and the port")
if len(found) > 1:
    raise SystemExit(f"more than one motor answered at {baud} baud (ids {sorted(found)}): connect one at a time")
motor_id = next(iter(found))
print(f"found motor id {motor_id} ({NAMES.get(motor_id, 'not an SO-101 joint id')}) at {baud} baud")
if baud != DEFAULT_BAUD:
    print(f"  not set up yet (LeRobot's buses run at {DEFAULT_BAUD}): run setup_one_motor.py before building")

bus = bus_for(args.port, motor_id)
ok = False
try:
    if baud != DEFAULT_BAUD:
        bus.set_baudrate(baud)
    pos = bus.read("Present_Position", "m", normalize=False)
    volts = bus.read("Present_Voltage", "m", normalize=False) / 10
    temp = bus.read("Present_Temperature", "m", normalize=False)
    print(f"  position {pos}, supply {volts:.1f} V, {temp} C")
    if bus.read("P_Coefficient", "m", normalize=False) != SERVO_P:
        bus.write("P_Coefficient", "m", SERVO_P, normalize=False)  # torque is still off, as an EEPROM write needs
    bus.write("Goal_Position", "m", pos, normalize=False)  # before torque: it runs to whatever goal it last had
    bus.enable_torque("m")
    out = pos + STEP if pos + STEP < 4096 else pos - STEP
    stops = []
    for target in (out, pos):
        got, low, load = go(bus, target)
        stops.append(abs(got - target))
        print(f"  told to go to {target}: stopped at {got} ({got - target:+d}), lowest supply {low:.1f} V, "
              f"peak load {load / 10:.1f}% of full torque")
    ok = max(stops) <= TOL
finally:
    try:
        bus.disable_torque("m")
    finally:
        bus.disconnect(disable_torque=False)
print(f"PASS: motor {motor_id} moved out and back" if ok else
      f"FAIL: motor {motor_id} stopped more than {TOL} steps from a target. Check its cable and power")
