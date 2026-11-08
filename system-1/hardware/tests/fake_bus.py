"""A stand-in for rustypot's serial bus, backed by a SimArm, under LeRobot's real SerialMotorsBus: real_arm runs with no
hardware and no serial port. A Goal_Position write moves the simulated arm one control tick (while torque is on); a
Present_Position read is the sim's encoder reading, with its jitter, in raw steps through real_arm.to_raw. FakePad is
the sim's fingertip pad, with sensing="tactile", as RealArm's pad.

    sim = robot.SimArm(world=world.build_world(None), slop=True, sensing="current", effector="stock")
    bus = fake_bus.make(sim, tmp_dir)       # a SerialMotorsBus whose port opens FakeServos
    arm = real_arm.RealArm(bus, app=sim.app, pace=False)
    bus.fake.torque                         # {motor id: on?}
"""
import os

import draccus
import mujoco
import numpy as np
from lerobot.motors import MotorCalibration

import real_arm
import robot


def calibration(sim):
    """What lerobot-calibrate might write for this arm: each joint swept through the model's range around a middle that
    differs per joint and isn't 2047, so a mapping that ignored the file's range would show. wrist_roll is a full-turn
    motor, which lerobot-calibrate gives the whole encoder (its middle, 2047.5, is half a step)."""
    cal = {}
    for i, j in enumerate(robot.ARM_JOINTS[:4]):
        mid, half = 1900 + 90 * i, (sim.ik.hi[i] - sim.ik.lo[i]) / 2 / robot.TICK_RAD
        cal[j] = MotorCalibration(i + 1, 0, 30 * i - 60, round(mid - half), round(mid + half))
    cal["wrist_roll"] = MotorCalibration(5, 0, 40, 0, 4095)
    cal["gripper"] = MotorCalibration(6, 0, 15, 1800, 3000)
    return cal


def make(sim, folder, cal=None):
    """A SerialMotorsBus built by real_arm.make_bus from a calibration file written as LeRobot writes it."""
    path = os.path.join(folder, "fake_arm.json")
    with open(path, "w") as f, draccus.config_type("json"):
        draccus.dump(cal or calibration(sim), f, indent=4)
    bus = real_arm.make_bus("FAKE", path)
    bus.fake = FakeServos(sim, bus.calibration)
    bus._open_bus = lambda: bus.fake  # what connect() opens: never a port
    return bus


class FakeServos:
    """rustypot.Bus's calls that LeRobot's SerialMotorsBus makes, with the same signatures. Status 0 is no error."""

    def __init__(self, sim, cal):
        self.sim, self.cal = sim, cal
        self.names = {c.id: name for name, c in cal.items()}
        self.mid = np.array([(cal[j].range_min + cal[j].range_max) / 2 for j in robot.ARM_JOINTS])
        self.torque = dict.fromkeys(self.names, False)
        self.goal, self.p, self.d = {}, {}, {}
        self.rng = np.random.default_rng(robot.SENSE_SEED + 7)
        self.collisions, self.peak_true_n, self.open = set(), 0.0, True
        self.qs = []  # every pose the arm was driven toward, model frame

    def _value(self, id_, name):
        c = self.cal[self.names[id_]]
        if name == "present_position" and id_ <= len(robot.ARM_JOINTS):
            q = self.sim.read_q() + self.rng.normal(0, robot.SENSE_NOISE_TICKS, len(robot.ARM_JOINTS)) * robot.TICK_RAD
            return int(real_arm.to_raw(q, self.mid)[id_ - 1])
        return {"present_position": (c.range_min + c.range_max) // 2, "min_position_limit": c.range_min,
                "max_position_limit": c.range_max, "homing_offset": c.homing_offset, "model_number": 777,
                "p_coefficient": self.p.get(id_, 16), "d_coefficient": self.d.get(id_, 32), "torque_enable": int(self.torque[id_])}[name]

    def read_register_with_error(self, id, name, retries=0):
        return self._value(id, name), 0

    def sync_read_register_with_error(self, ids, name, retries=0):
        return [(self._value(i, name), 0) for i in ids]

    def set_torque(self, ids, enabled, retries=0):
        self.torque.update(dict.fromkeys(ids, bool(enabled)))
        return {}

    def sync_write_register(self, ids, name, values, retries=0):
        if name in ("p_coefficient", "d_coefficient"):
            assert not any(self.torque[i] for i in ids), "gain written with torque on"
            (self.p if name == "p_coefficient" else self.d).update(zip(ids, values))
            return
        assert name == "goal_position", name
        self.goal.update(zip(ids, values))
        arm_ids = range(1, len(robot.ARM_JOINTS) + 1)
        if all(self.torque[i] for i in arm_ids):
            self._step(real_arm.to_model([self.goal[i] for i in arm_ids], self.mid))

    def close(self):
        self.open = False

    def _step(self, q):
        """One control tick of physics toward q, as SimArm.tick runs it, without the sim's own safety checks."""
        s = self.sim
        s.cmd = q
        s._drive(q)
        self.qs.append(q)
        for _ in range(s.substeps):
            s._servo()
            mujoco.mj_step(s.m, s.d)
            s.app.update(s.m, s.d)
        self.collisions.update(s.collisions())
        self.peak_true_n = max(self.peak_true_n, float(np.linalg.norm(s.contact_force_vec())))
        if s.on_tick:  # explore.py's film draws from here, as SimArm.tick would call it
            s.on_tick(s)


class FakePad:
    """RealArm's pad from a SimArm(sensing="tactile"): read() is the pad reading the sim took in the tick FakeServos
    last ran (SimArm._pad: the force pressing into the face in N, with the film's noise and threshold)."""

    noise_n = robot.PAD_NOISE_N

    def __init__(self, sim):
        self.sim = sim

    def read(self):
        return self.sim.pad_n
