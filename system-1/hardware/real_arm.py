"""The real SO-101 through LeRobot's motor bus, with the calls the skills use on robot.SimArm.

    bus = make_bus("COM5", "makecu.json")   # lerobot-calibrate's file (see make_bus)
    with RealArm(bus) as arm:               # torque off: read_q() and tip_pose() work, nothing moves
        arm.enable(confirm=True)            # torque on the five arm joints, holding where they are
        skills.go_home(arm)
        affordances.run_step(arm, parts, {"skill": "press", "target": "button_1"})
    # torque off on every motor when the block ends, on any exception and on Ctrl+C: the arm goes limp

It uses LeRobot's SerialMotorsBus, not its SO101Follower: the follower's connect() always ends with torque on (its
configure() runs inside bus.torque_disabled(), which turns torque back on), and if the motors don't match its
calibration file it starts an interactive calibration that rewrites their homing offsets. Here torque goes on only in
enable(confirm=True), and a mismatch is an error. Positions are raw encoder steps (normalize=False), so the force
estimate sees exactly the steps written and read.

Joint angles are radians in the MuJoCo model's frame (see SIGN). Kinematics, IK and gravity come from the sim's model
file, with no physics. As on SimArm, send() clips to the joint limits and to MAX_STEP_RAD per tick, tick() runs at
CONTROL_HZ, and a tip force over HARD_FORCE_CAP_N backs the tip off and raises SafetyStop. Force is
SimArm(sensing="current")'s estimate from the servos (_sense), and `pad`, a fingertip sensor object, can supply the
force along the probe. The real arm has no collision check: seen_collisions stays empty. `app` is the device's
readout, which every verdict reads: OperatorReadout, a person at the terminal, unless another is passed in, such as
pico_readout.PicoReadout.
"""
import atexit
import json
import time

import mujoco
import numpy as np
from lerobot.motors import Motor, MotorCalibration, MotorNormMode, SerialMotorsBus

import rig
from rig import ARM_JOINTS, CONTROL_HZ, HARD_FORCE_CAP_N, MAX_STEP_RAD, TICK_RAD, SafetyStop

# Joint mapping: model angle = SIGN * (raw - mid) * TICK_RAD + OFFSET_RAD, with mid = (range_min + range_max) / 2 from
# the calibration file. That is LeRobot's use_degrees reading (whose zero is mid; it counts 4095 steps a turn, 0.02% off)
# with a sign and offset per joint. lerobot-calibrate has every joint held at the middle of its range, then swept stop to
# stop. so101_new_calib puts each joint's zero at the middle of its range (TheRobotStudio's SO-ARM100 README), and
# LeRobot's own kinematics (lerobot-find-joint-limits, its phone and end-effector examples) feed the use_degrees reading
# into this model through np.deg2rad alone. Hence sign +1 and no offset. Unchecked on the team's arm: tools/arm_check.py
# is for that, and what it finds goes here. Expect offsets of a few degrees, as a hand sweep's middle isn't the model's.
SIGN = np.array([1, 1, 1, 1, 1])                       # ARM_JOINTS order
# lift, elbow and wrist_flex: the hand-eye views (4.6 px rms) refitted with lift held where six desk touches came out
# flat (12.8 -> 1.9 mm spread); hand-eye can't see pan's or roll's
OFFSET_RAD = np.radians([0.0, -1.9, -4.8, -2.24, 0.0])
# P gain enable() sets on the five arm joints. The RobiServo-01 ships at 160. LeRobot's follower writes 16 on every
# connect (lerobot-calibrate, teleop), and at 16 a loose motor didn't follow a 5 deg move at all; at 160 it stopped 5
# steps short (system-1/arm/bringup/results.md).
SERVO_P = 160
# Servo stiffness the force estimate assumes (N.m/rad). The sim's 36 is fitted to a bench test at an unstated P gain,
# and the stiffness at SERVO_P is unmeasured. On softer servos the estimate reads high and drifts with the pose (slides
# miss, the cap trips with nothing touching); on stiffer ones it reads low and the cap trips late (sim/docs/real-arm.md,
# Servo numbers). Measure it with system-1/arm/bringup/stiffness_test.py and put the result here before any test step.
SERVO_NM_PER_RAD = 36.0
OUT_OK = np.radians(15)  # enable() starts from a joint up to this far past its limit
MOTOR_IDS = {"shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3, "wrist_flex": 4, "wrist_roll": 5, "gripper": 6}


def to_model(raw, mid):
    """Raw Present_Position steps of the five arm joints to model joint angles (rad)."""
    return SIGN * (np.asarray(raw, float) - mid) * TICK_RAD + OFFSET_RAD


def to_raw(q, mid):
    """Model joint angles (rad) to the nearest raw Goal_Position steps."""
    return np.round(mid + SIGN * (np.asarray(q, float) - OFFSET_RAD) / TICK_RAD).astype(int)


def make_bus(port, calibration):
    """LeRobot's bus for the follower's six servos, as SO101Follower(use_degrees=True) sets it up, with the calibration
    file lerobot-calibrate wrote: ~/.cache/huggingface/lerobot/calibration/robots/so_follower/<robot.id>.json."""
    with open(calibration) as f:
        cal = {name: MotorCalibration(**c) for name, c in json.load(f).items()}
    motors = {name: Motor(i, "sts3215", MotorNormMode.RANGE_0_100 if name == "gripper" else MotorNormMode.DEGREES)
              for name, i in MOTOR_IDS.items()}
    return SerialMotorsBus(port, motors, cal)


class RealArm(rig.ArmBase):
    """Connects with torque off on every motor, after checking the motors hold the calibration in the file (homing
    offsets and limits). enable(confirm=True) turns torque on for the five arm joints, and holds the gripper where it is.

    tick() writes the goal for cmd, waits for the tick's end, then reads every joint once (so read_q() and tip_pose()
    between ticks give the last reading, as on the sim). d.time counts ticks, 1 / CONTROL_HZ each. With pace=False
    ticks run as fast as the bus answers: for tests against a simulated bus only.

    pad, if given, is a fingertip sensor: pad.read() returns the force pressing into its face (N) and pad.noise_n its
    floor. tip_force() and the hard cap then use it, and the force across the probe stays the servo estimate, as with
    SimArm(sensing="tactile"). No driver for the SensX 25 exists yet.
    """
    # The arm stands on the desk, not the sim's post: the hand-eye fit put the desk at z = -0.1 mm. The workspace floor
    # is 5 mm over it, where perceive starts counting points as above the desk, so controls low on a panel stay in reach.
    # The camera sits about 130 mm behind the probe tip (the model's 81 mm), so at the sim's standoff the tip would be
    # in the panel.
    table_z = 0.0
    workspace = np.array([[0.05, 0.42], [-0.25, 0.25], [0.005, 0.35]])
    standoff = 0.14  # camera to panel: the jaw tip sits ~11 cm in front of the camera; 12 cm reached no views
    # The force estimate drifts 2.5-10 N along the fingertip in free air on any downward move (tools/creep_log.py, Nov 7),
    # so guarded moves take contact as a stall instead, as tools/press_check.py does, at a speed that tracks smoothly
    # (at 2 mm/s the tip stick-slips)
    stall_m, guard_speed = 0.004, 0.015
    # on the desk, a panel 23 cm out tilted toward the arm put every view tilted down its slope out of reach (0/9);
    # tilted up it, the camera rises away from the base and all 9 reach at a 14-17 cm standoff
    view_tilts = np.radians([-10, -20, -30])
    # each photo's pose comes from the joint readings, so a view needn't be met to 0.5 mm: re-commanding to that took
    # ~3 s a photo on this stick-slip arm
    view_tol = 0.01
    view_looks = [(0.0, -0.05), (0.0, 0.0), (0.0, 0.05)]  # the middle row only: one 14 cm view nearly covers a panel
    # wrist_roll at home, so views and presses start from it: -90 deg puts the camera on top of the gripper, centred,
    # instead of 7 cm to its side (same views in reach); the gripper then sits along the bottom of the picture
    home_roll = np.radians(-90)  # camera on top; +90 (under) pointed the survey away from the panel
    # Free moves (skills.move_joints) at 1.5x the sim's cap (0.2 read 35 N on the servo estimate going home and tripped
    # the hard cap). The joints peak well inside MAX_STEP_RAD,
    # and a cosine profile arrives at rest. Guarded moves keep guard_speed.
    tip_speed = 0.15
    # one re-command of an approach pose: the press is by stall and the last look's pose is from the joint readings, so
    # the ~1.2 mm one round leaves doesn't matter, and each further round cost 0.7 s
    sag_tries = 1
    # no hard cap on the force estimate: it read 35-60 N on free moves home and stopped the arm. Stalls and the press depth
    # limit bound a press; the servos cap themselves (Torque_Limit 680/1000, overload protection)
    hard_cap_n = float("inf")
    # presses come in a quarter of the way from the panel's normal to straight down: along the normal the jaw slid off a
    # tilted button's cap, halfway the gripper met the panel's lower edge first; a quarter clicked START (Nov 8)
    press_down = 0.25

    def __init__(self, bus, app=None, pad=None, pace=True):
        self.bus, self.pad, self.pace = bus, pad, pace
        self.m = mujoco.MjModel.from_xml_path(rig.ARM_XML)
        self.d = mujoco.MjData(self.m)  # the arm as its readings say, for the estimator
        self.ik = rig.IK(self.m)
        self.arm_bodies = rig.arm_bodies(self.m)  # perceive crops the arm out of what the cameras see
        self.qadr, self.dadr, self.tip = self.ik.qadr, self.ik.dadr, self.ik.tip
        self.home_q, *_ = self.ik.solve(np.array([0.2, 0.0, 0.14]), np.array([0.7, 0, -0.7]), np.zeros(5))
        self.home_q[4] = self.home_roll  # wrist_roll isn't solved by the IK: it stays where home puts it
        self.mid = np.array([(bus.calibration[j].range_min + bus.calibration[j].range_max) / 2 for j in ARM_JOINTS])
        self.controls, self.seen_collisions, self.force_log, self.status = {}, set(), [], "idle"
        self.sensing = "tactile" if pad else "current"
        self.axial_sensor = pad is not None
        self.noise_n = rig.SENSED_NOISE_N  # arm_check --noise: 0.6 N worst at rest, but up to 3.5 N moving at 20 mm/s
        self.noise_axial = pad.noise_n if pad else self.noise_n
        self.raw, self.qs, self.zero = [], [], np.zeros(len(ARM_JOINTS))
        self.W, self.axis_est, self.est_vec = np.zeros((len(ARM_JOINTS), 3)), np.zeros(3), np.zeros(3)
        self.est_axial = self.cap_f = self.pad_n = 0.0
        self.torque = False
        self.app = OperatorReadout(self) if app is None else app
        bus.connect(handshake=False)  # as the team's scripts: LeRobot's firmware check is skipped
        atexit.register(self.close)
        try:
            bus.disable_torque()
            if not bus.is_calibrated:
                raise RuntimeError("the motors' homing offsets or limits don't match the calibration file: wrong file, "
                                   "or run lerobot-calibrate again")
            self._read()
        except BaseException:
            self.close()
            raise
        self._wall = time.perf_counter()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Torque off on every motor, then the port closed, then the readout's if it has one (pico_readout). The arm
        goes limp: support it first."""
        self.torque = False
        try:
            self.bus.disconnect(disable_torque=True)
        finally:
            if hasattr(self.app, "close"):
                self.app.close()

    def enable(self, confirm=False):
        """Torque on for the five arm joints, holding where they are. confirm must be True: the caller has checked the
        arm is clear to move. A joint a little outside the model's limits (resting limp past one) steps back inside on the
        first commands, MAX_STEP_RAD a tick; one far outside means a wrong joint mapping, so that refuses."""
        if confirm is not True:
            raise RuntimeError("enable(confirm=True) turns torque on, and the arm then holds and moves: confirm it")
        self._read()  # the limp arm may have moved since the last reading: hold it where it is now
        out = [f"{j} reads {np.degrees(q):+.1f} deg, outside {np.degrees(lo):+.0f} to {np.degrees(hi):+.0f}"
               for j, q, lo, hi in zip(ARM_JOINTS, self.q, self.ik.lo, self.ik.hi) if not lo - OUT_OK <= q <= hi + OUT_OK]
        if out:
            raise SafetyStop("; ".join(out) + ". Check the joint mapping (tools/arm_check.py), or move it inside by hand")
        p = self.bus.sync_read("P_Coefficient", ARM_JOINTS, normalize=False)
        if any(p[j] != SERVO_P for j in ARM_JOINTS):  # torque is still off, as an EEPROM write needs
            self.bus.sync_write("P_Coefficient", dict.fromkeys(ARM_JOINTS, SERVO_P), normalize=False)
        self.goal = self.pos.copy()
        self.bus.sync_write("Goal_Position", dict(zip(ARM_JOINTS, self.goal.tolist())), normalize=False)
        self.bus.enable_torque(ARM_JOINTS)  # after the goal: a servo turned on runs to whatever goal it last had
        # The gripper holds where it is (closed by hand before), at LeRobot's soft gripper gain and torque limit, so the
        # loose jaw can't hang below the fingertip
        self.bus.sync_write("Goal_Position", self.bus.sync_read("Present_Position", ["gripper"], normalize=False),
                            normalize=False)
        self.bus.enable_torque(["gripper"])
        self.torque = True
        self._io()

    # --- the calls the skills use, as on SimArm ---
    def read_q(self):
        return self.q.copy()

    def send(self, q):
        if not self.torque:
            raise RuntimeError("torque is off: enable(confirm=True) first")
        q = np.clip(q, self.ik.lo, self.ik.hi)
        self.cmd = self.cmd + np.clip(q - self.cmd, -MAX_STEP_RAD, MAX_STEP_RAD)

    def tick(self):
        self._io()
        f = self.cap_f if self.cap_f > self.hard_cap_n else self.tip_force()
        self.force_log.append((self.d.time, f))
        if self.torque and f > self.hard_cap_n:
            self._back_off()
            raise SafetyStop(f"tip force {f:.1f} N over hard cap {self.hard_cap_n} N")
        return f

    def tip_pose(self):
        return self.ik.fk(self.read_q())

    def tip_force(self):
        """Force along the probe (N): the pad's, or the servo estimate."""
        return self.pad_n if self.pad else self.est_axial

    def tare(self, on=True):
        """Zero the servo estimate on the last rig.TARE_S of readings, or with on=False drop the zero."""
        self.zero = np.mean(self.raw, axis=0) if on else np.zeros(len(ARM_JOINTS))
        self._estimate()

    # --- bus and estimate ---
    def _io(self):
        """One tick: the goal out, wait for the tick's end, the joints in, the force estimate."""
        if self.torque:
            self.goal = to_raw(self.cmd, self.mid)
            self.bus.sync_write("Goal_Position", dict(zip(ARM_JOINTS, self.goal.tolist())), normalize=False)
        if self.pace:
            self._wall += 1 / CONTROL_HZ
            delay = self._wall - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                self._wall = time.perf_counter()
        self._read()
        self.d.time += 1 / CONTROL_HZ
        if self.torque:
            self._sense()

    def _read(self):
        pos = self.bus.sync_read("Present_Position", ARM_JOINTS, normalize=False, num_retry=2)
        self.pos = np.array([pos[j] for j in ARM_JOINTS])
        self.q = to_model(self.pos, self.mid)
        if not self.torque:  # nothing holds the arm: the command follows it
            self.cmd, self.goal = self.q.copy(), self.pos.copy()

    def _sense(self):
        """SimArm._sense's estimate on the real readings: each servo's goal minus present position in steps, through
        the servo law the rig believes, less what gravity and damping cost by the model, fitted to a force on the tip
        through the Jacobian. Copied rather than shared, as the sim's reads its sim and adds the noise and one sample
        of latency a real bus has anyway. One read a tick (the sim reads at robot.SENSE_HZ), so its windows hold the
        same number of samples over twice the time; the hard cap uses the newest reading."""
        err = SIGN * (self.goal - self.pos)  # in the model's direction
        servo = SERVO_NM_PER_RAD * np.sign(err) * np.maximum(np.abs(err) - rig.DEADBAND_EST_TICKS, 0) * TICK_RAD
        self.qs = (self.qs + [self.q])[-rig.SENSE_AVG - 1:]
        vel = (self.qs[-1] - self.qs[0]) * CONTROL_HZ / max(len(self.qs) - 1, 1)
        m, d = self.m, self.d
        d.qpos[self.qadr], d.qvel[self.dadr] = self.q, vel
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        mujoco.mj_comVel(m, d)
        free = np.zeros(m.nv)
        mujoco.mj_rne(m, d, 0, free)
        free = free[self.dadr] + (m.dof_damping[self.dadr] + rig.SERVO_KV) * vel
        self.raw = (self.raw + [free - servo])[-int(rig.TARE_S * CONTROL_HZ) - 1:]
        jac = np.zeros((3, m.nv))
        mujoco.mj_jacSite(m, d, jac, None, self.tip)
        self.W = jac[:, self.dadr].T
        self.axis_est = -d.site_xmat[self.tip].reshape(3, 3)[:, 2]
        self._estimate()
        self.pad_n = float(self.pad.read()) if self.pad else 0.0
        self.cap_f = max(self.pad_n, self._axial(self._fit(np.mean(self.raw[-rig.CAP_AVG:], axis=0))))

    def _estimate(self):
        self.est_vec = self._fit(np.mean(self.raw[-rig.SENSE_AVG:], axis=0))
        self.est_axial = self._axial(self.est_vec)

    def _back_off(self, dist=0.01, ticks=15):
        """After a stop, pull the tip back along the probe so the servos stop pushing (no force check meanwhile)."""
        tip, axis = self.tip_pose()
        q, *_ = self.ik.solve(tip - dist * axis, axis, self.read_q(), iters=50)
        for _ in range(ticks):
            self.send(q)
            self._io()


class OperatorReadout:
    """The device's readout from a person watching it, until a camera or a wire can read the device. It has what verdicts
    read on device.DeviceMCU: readings ({channel: value}), events ([(time, channel, value)]) and lcd (None here).
    skills.py's Rev A/B steps also read switches and door_open, but they need CAD controls (arm.controls), which a real
    arm has none of, so they refuse before reading them.

    affordances.run_step reads events at the start and end of every step, so reading events after a test motion (arm
    status "press button_1: push" and the like) asks the operator what the device did. The first read, and one after
    other motion (going home between steps or after a stop), only set the baseline: an answer at a step's start would
    land after the step copied its readings, and count as that step's change. The answer is what changed: "BTN1"
    for a momentary press (0 -> 1 -> 0), "POWER 1" or "FAN 0.8" for a new value, several separated by commas, Enter
    for nothing. A new value needs its channel declared with where it starts, as slide and turn verdicts compare
    values: OperatorReadout(arm, {"POWER": 0, "FAN": 0.0}). Reads within a step don't ask, so a turn that moved
    nothing (it tries again further out along the fin) can't know a reading changed.
    """

    def __init__(self, arm, channels=None, ask=input):
        self.arm, self.readings, self.lcd, self.ask = arm, dict(channels or {}), None, ask
        self._events, self._seen = [], None

    @property
    def events(self):
        if self._seen is not None and not np.array_equal(self._seen, self.arm.cmd) and ":" in self.arm.status:
            self._question()
        self._seen = self.arm.cmd.copy()
        return self._events

    def _question(self):
        print(f"\nThe arm just did: {self.arm.status}. The device read: {self.readings or 'nothing declared'}")
        while True:
            try:
                changes = [_change(c, self.readings) for c in self.ask("What changed on the device? ").split(",")
                           if c.strip()]
                break
            except ValueError as e:
                print(e)
        t = self.arm.d.time
        for ch, v in changes:
            self._events += [(t, ch, 1), (t, ch, 0)] if v is None else [(t, ch, v)]
            self.readings[ch] = 0 if v is None else v


def _change(text, readings):
    """'BTN1' -> ('BTN1', None), a momentary press; 'FAN 0.8' -> ('FAN', 0.8), of the type its channel was declared."""
    name, *value = text.split()
    if not value:
        return name, None
    if name not in readings or len(value) > 1:
        raise ValueError(f"'{text.strip()}': a new value needs a declared channel and one number "
                         f"(declared: {list(readings)})")
    return name, type(readings[name])(value[0])
