"""SO-101 in MuJoCo: a safety layer, and the calls the pipeline makes on an arm (rig.Arm).

real_arm.RealArm answers the same calls on hardware. The IK and the shared constants are in rig.py.
"""
import copy
import os
import time

import mujoco
import numpy as np

import appliance
import vision
from rig import (ARM_JOINTS, CAP_AVG, CONTACT_N, CONTROL_HZ, DEADBAND_EST_TICKS, HARD_FORCE_CAP_N, IK,  # noqa: F401
                 MAX_STEP_RAD, SENSE_AVG, SENSED_NOISE_N, SERVO_KV, TARE_S, TICK_RAD, WORKSPACE, ArmBase, SafetyStop,
                 arm_bodies)

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "so101")
# Real-servo slop, used with SimArm(slop=True). Each servo reads its output shaft, ignores errors
# inside a dead band and pushes back softly beyond it, with gear play between motor and output.
# Fitted to one STS3215 bench test (P gain not stated): 22.5 and 30 counts of error at 0.98 and
# 1.47 N.m while moving, about 10 counts of reversal before the output moved (4 here, plus the
# motor's friction), and free play of 0.57 and 0.87 deg on two units. The stiffness is the least
# certain number: anywhere from about 18 to 43 fits, and the team's RobiServo-01 runs at P=160 (real_arm.SERVO_P),
# where it is unmeasured.
SERVO_NM_PER_RAD = 36.0
DEADBAND_RAD = np.radians(5 * 360 / 4096)  # a loose RobiServo-01 at P=160 stops about 5 steps short (arm bring-up results)
BACKLASH_DEG = 0.75
# Servo-only sensing, SimArm(slop=True, sensing="current"): no force sensor, so tip_force() and tip_force_vec() become
# what a rig can estimate from the servos' own feedback, read over the bus at SENSE_HZ. The register is Goal minus
# Present_Position in encoder ticks, the finest effort signal an STS3215 gives (it is a P controller: Present_Load and
# Present_Current follow from that error, more coarsely), or Present_Load as a backup (SENSE_REGISTER). The rig turns
# it into servo torque with the gain it believes, subtracts gravity and damping from its own model (masses and centres
# a little off), and maps the rest to a tip force through the Jacobian. The arm also gets the gear friction that hides
# small pushes, from Rhoban BAM's bench fit of the 7.4 V STS3215 (model m5): on top of the model file's 0.052 N.m,
# |0.241 x the load from outside (gravity, contacts) - 0.039 x the motor's torque|, and 0.149 x that load more below
# 0.37 rad/s. That is 0.28 x a held load, 0.43 x when slow. The team's servo claims a brushless motor and friction
# compensation, so FRICTION_SCALE = 0.5 halves it.
SENSE_HZ = 50              # reads per second: RealArm reads every joint once per 20 ms control tick
SENSE_NOISE_TICKS = 0.95   # a RobiServo-01 holding at P=160 flickers this much, 1 sigma, its own hunting included
SENSE_REGISTER = "error"   # or "load": Present_Load, 0 inside the 1-step dead zone, then a jump to 16 counts (1.6%)
LOAD_JUMP = 16             # of 1000 (full duty, the servo's stall torque), then in proportion to the torque
K_EST_SCALE = 1.0          # servo gain the estimator believes, over the true one
MASS_ERR, COM_ERR_M = 0.03, 0.002  # the estimator's model: masses and centres off by this, 1 sigma
SENSE_SEED = 0             # draws those errors and the jitter
FRICTION_LOAD, FRICTION_MOTOR, FRICTION_SLOW, SLOW_RAD_S = 0.241, 0.039, 0.149, 0.371
FRICTION_SCALE = 1.0       # 0.5: half of BAM's load-dependent friction
# Fingertip pad, SimArm(slop=True, sensing="tactile"): servo sensing plus a TouchTronix SensX 25 on the pad face, 5 x 5
# cells over 19 x 13 mm reporting whole kPa (0-534), read with the servos. It feels only force pressing into its face, so
# it gives tip_force() and the probe-axis part of tip_force_vec(); the part across the probe still comes from the servos.
# The sim's pad is a 12 mm disc, so it covers the middle of the grid. No datasheet found gives the film's noise, threshold
# or calibration error: the three numbers below are guesses for a bench test to replace.
PAD_CELLS, PAD_SIZE_M = (5, 5), (0.019, 0.013)
PAD_MAX_KPA = 534
PAD_NOISE_KPA = 1.0        # per cell, 1 sigma
PAD_THRESHOLD_KPA = 3.0    # a cell under this reads 0 (about 0.03 N)
PAD_GAIN = 0.85            # reads 15% low, the unsafe way round
PAD_NOISE_N = 0.1          # the pad's floor along the probe (arm.noise_axial): its threshold zeroes unloaded cells
PAD_FACE_M = 0.0008        # contacts further behind the face are on the pad's rim, where the film isn't
PAD_SPREAD_M = 0.003       # MuJoCo's contacts are points: each is spread over a disc this wide on the face, as the film's
                           # cover would (a guess). As points, one cell took the whole push and saturated at 5.3 N.
# Load cell, SimArm(slop=True, sensing="loadcell"): servo sensing plus a single-axis bar load cell between the gripper and
# the probe, read by an HX711 at 80 samples/s (about $10). It feels every probe contact, face and rim, along the probe, so
# it gives tip_force() and the probe-axis part of tip_force_vec(); across the probe the servos still give the force. A
# sample is the mean over its 12.5 ms, as the HX711 averages over its conversion. Assumed figures for a 2 kg cell (1 mV/V
# at 4.3 V, 0.22 mV/N), for a bench test to replace: the HX711 datasheet's 90 nV rms at 80 SPS is 0.4 mN, and LC_NOISE_N
# allows ten times that for a cheap module and its wiring. Its offset drifts 6 nV/degC (0.03 mN/degC), but a cheap bar
# cell's zero moves about 0.05% of full scale per 10 degC and creeps about as much in 30 min. A one-weight calibration
# leaves about 2% gain error, and a parallel-beam cell reads a few % of a load across it. The probe's own weight is taken
# out using the arm's pose (not modelled: the sim's probe weighs 1.6 g).
LC_HZ = 80
LC_NOISE_N = 0.005         # per sample, 1 sigma
LC_DRIFT_N = 0.01          # zero drift: a random walk, 1 sigma after 10 minutes
LC_GAIN = 0.98             # reads 2% low, the unsafe way round
LC_CROSS = 0.02            # share of the force across the probe (along the tip frame's x) read as force along it
LC_NOISE_FLOOR_N = 0.05    # the cell's floor along the probe (arm.noise_axial): noise and a run's drift


def load_model(path, slop=False):
    """Compile a scene. With slop, each arm joint gets a passive joint in series for the gear play
    (friction set to 0.1 N.m keeps it shut until a load forces it open; stiff stops keep it at
    BACKLASH_DEG under load), and the servos get the real damping (SERVO_KV)."""
    if not slop:
        return mujoco.MjModel.from_xml_path(path)
    spec = mujoco.MjSpec.from_file(path)
    half = np.radians(BACKLASH_DEG) / 2
    for name in ARM_JOINTS:
        j = spec.joint(name)
        j.parent.add_joint(name=f"{name}_backlash", axis=j.axis, pos=j.pos, range=[-half, half],
                           limited=mujoco.mjtLimited.mjLIMITED_TRUE, solref_limit=[0.004, 1],
                           damping=0.01, armature=1e-3, frictionloss=0.1)
    m = spec.compile()
    for name in ARM_JOINTS:
        m.actuator(name).biasprm[2] = -SERVO_KV
    return m


class SimArm(ArmBase):
    """`world` (from world.py) swaps the Rev A/B appliance for a generated device with no CAD.

    `joint_offsets` (rad) models servo calibration error: the arm believes it is at
    read_q() = true angle + offset, and every pose the controller computes inherits that.
    `slop` makes the servos as soft as real STS3215s, with their dead band and gear play (see
    SERVO_NM_PER_RAD); gravity alone then sags the tip about 1 cm, which the encoders see.

    `sensing="current"` (needs slop) takes the perfect tip sensor away: tip_force(), tip_force_vec() and the hard cap
    then use an estimate from the servos' own readings (see SENSE_REGISTER), and contact_force_vec() keeps the true
    force for evaluation only. A skill using it should tare() once its creep is moving and only then go by the force
    (moving joints' friction reads as a push), drop the zero with tare(False) once clear of the part (dropped while
    pressing, the reading jumps by several N), and keep its contact thresholds above noise_n, the force it can't tell
    from noise (0 with the perfect sensor, where tare() does nothing). The estimate has no inertia term, so free moves
    should be gentle: skills.move_joints stretches short ones to SENSED_MOVE_S. The hard cap uses the zero too and checks
    one reading per bus read. An impact shorter than that is taken by the arm's inertia, not its servos, so no servo
    reading sees it: keep speeds low where contact can come (moving 4 mm into a rigid part peaked at 12 N at 20 mm/s,
    21 N at 50 mm/s).

    `sensing="tactile"` (needs slop) adds a fingertip pad (see PAD_CELLS) to servo sensing. The pad gives the force along
    the probe directly, with no tare, and the hard cap reads it too; force across the probe is still the servo estimate,
    so tare() and noise_n keep their meaning; noise_axial is the floor along the probe alone (noise_n without the pad).
    pad_centre() says where on the pad the pressure is.

    `sensing="loadcell"` (needs slop) is the same with a load cell behind the probe instead of the pad (see LC_HZ): it
    reads the force along the probe from every probe contact, rim included, but only 80 times a second.

    axial_sensor is True with the pad or the load cell: a sensor on the probe reads the force along it, and its zero
    doesn't move with the joints' friction, so skills can go by tip_force() from the start of a move, with no tare.
    """

    def __init__(self, rev="B", realtime=False, viewer=None, placement=None, world=None, joint_offsets=None,
                 slop=False, sensing=None):
        self.world = world
        self.sensing = sensing
        self.axial_sensor = sensing in ("tactile", "loadcell")
        self.noise_n = self.noise_axial = 0.0
        if world is None:
            self.rev = rev
            self.params = appliance.REVS[rev]
            self.placement = placement or appliance.NOMINAL_PLACEMENT  # sim truth; skills never read it
            vision.write_textures(ASSETS)
            path = os.path.join(ASSETS, f"_scene_rev{rev}.xml")
            xml = appliance.scene_xml(self.params, self.placement)
            if not os.path.exists(path) or open(path).read() != xml:  # another sim may be loading it
                with open(path, "w") as f:
                    f.write(xml)
        else:
            self.rev, self.params, self.placement, path = world.name, None, None, world.xml_path
        self.m = load_model(path, slop)
        self.d = mujoco.MjData(self.m)
        self.ik = IK(self.m)
        # CAD at the nominal fixture spot until a look. A generated device has no CAD.
        self.controls = appliance.controls(self.params) if world is None else {}
        self.app = appliance.ApplianceState(self.m, self.params) if world is None else world.make_mcu(self.m)
        self.q_off = np.zeros(len(ARM_JOINTS)) if joint_offsets is None else np.asarray(joint_offsets, float)
        self.play_adr = np.array([self.m.joint(f"{j}_backlash").qposadr[0] for j in ARM_JOINTS]) if slop else None
        self.kp = self.m.actuator_gainprm[:5, 0].copy()
        self.realtime = realtime
        self.viewer = viewer
        self.on_tick = None  # hook for the viewer overlay
        self.substeps = round(1 / (CONTROL_HZ * self.m.opt.timestep))
        self.qadr = self.ik.qadr
        self.tip = self.m.site("tip").id
        self.probe_body = self.m.body("probe").id
        self.arm_bodies = arm_bodies(self.m)
        self.force_log = []  # (t, newtons)
        self.status = "idle"

        self.seen_collisions = set()
        self.home_q, *_ = self.ik.solve(np.array([0.2, 0.0, 0.14]), np.array([0.7, 0, -0.7]), np.zeros(5))
        self.target = self.home_q - self.q_off  # true joint angles the servos aim for
        self.d.qpos[self.qadr] = self.home_q - self.q_off
        self.d.ctrl[:5] = self.home_q - self.q_off
        self.d.ctrl[5] = 0.0
        self.cmd = self.home_q.copy()
        mujoco.mj_forward(self.m, self.d)
        self._wall = time.perf_counter()
        if sensing:
            assert sensing in ("current", "tactile", "loadcell") and slop, f"sensing='{sensing}' needs slop=True"
            self._init_sensing()

    def _init_sensing(self):
        rng = np.random.default_rng(SENSE_SEED)
        self.est_m = copy.deepcopy(self.m)  # the rig's own model: URDF masses and centres, a little off
        for b in sorted(self.arm_bodies):
            self.est_m.body_mass[b] *= 1 + rng.normal(0, MASS_ERR)
            self.est_m.body_ipos[b] += rng.normal(0, COM_ERR_M, 3)
        self.est_d = mujoco.MjData(self.est_m)
        self.noise = rng
        self.dadr = self.ik.dadr
        self.fric0 = self.m.dof_frictionloss[self.dadr].copy()
        self.sense_every = round(1 / (SENSE_HZ * self.m.opt.timestep))
        self.n_steps, self.raw, self.qs = 0, [], []
        self.zero = np.zeros(len(ARM_JOINTS))
        self.W, self.axis_est = np.zeros((len(ARM_JOINTS), 3)), np.zeros(3)
        self.est_vec, self.est_axial, self.cap_f = np.zeros(3), 0.0, 0.0
        self.noise_n = SENSED_NOISE_N * K_EST_SCALE
        self.noise_axial = {"tactile": PAD_NOISE_N, "loadcell": LC_NOISE_FLOOR_N}.get(self.sensing, self.noise_n)
        self.pad_rng, self.pad_kpa, self.pad_n = np.random.default_rng(SENSE_SEED + 1), np.zeros(PAD_CELLS), 0.0
        self.lc_rng, self.lc_n, self.lc_drift, self.lc_sum, self.lc_k = np.random.default_rng(SENSE_SEED + 2), 0.0, 0.0, 0.0, 0
        self.lc_t = 1 / LC_HZ
        self.cell = np.array(PAD_SIZE_M) / PAD_CELLS
        g = np.linspace(-PAD_SPREAD_M, PAD_SPREAD_M, 9)
        g = np.stack(np.meshgrid(g, g), -1).reshape(-1, 2)
        self.spread = g[np.linalg.norm(g, axis=1) <= PAD_SPREAD_M]
        self.pad_r = self.m.geom("probe_pad").size[0]

    # --- the five calls a hardware backend would implement ---
    def read_q(self):
        """What the servo encoders report. They sit on the output shaft, so they see any gear play."""
        q = self.d.qpos[self.qadr] + self.q_off
        if self.play_adr is not None:
            q += self.d.qpos[self.play_adr]
        return q

    def send(self, q):
        q = np.clip(q, self.ik.lo, self.ik.hi)
        q = self.cmd + np.clip(q - self.cmd, -MAX_STEP_RAD, MAX_STEP_RAD)
        self.cmd = q
        self._drive(q)

    def _drive(self, q):
        self.target = q - self.q_off
        if self.play_adr is None:
            self.d.ctrl[:5] = self.target

    def _servo(self):
        """With slop, each servo's own loop, run every physics step: it reads its output shaft,
        ignores errors inside its dead band, and pushes back with the real servo's stiffness."""
        if self.play_adr is None:
            return
        motor = self.d.qpos[self.qadr]
        err = self.target - motor - self.d.qpos[self.play_adr]
        push = np.sign(err) * np.maximum(np.abs(err) - DEADBAND_RAD, 0)
        self.d.ctrl[:5] = motor + push * SERVO_NM_PER_RAD / self.kp
        if self.sensing:
            d, fr = self.d, np.zeros(self.m.nv)  # BAM's load is what the gearbox carries from outside: gravity and
            sel = d.efc_type == mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF  # contacts, not its own friction
            np.add.at(fr, d.efc_id[sel], d.efc_force[sel])
            ext = (d.qfrc_constraint - d.qfrc_bias - fr)[self.dadr]
            slow = np.exp(-(np.abs(d.qvel[self.dadr]) / SLOW_RAD_S) ** 10)  # its Stribeck window
            self.m.dof_frictionloss[self.dadr] = self.fric0 + FRICTION_SCALE * (
                np.abs(FRICTION_LOAD * ext - FRICTION_MOTOR * d.qfrc_actuator[self.dadr]) + FRICTION_SLOW * slow * np.abs(ext))
            self.n_steps += 1
            if self.sensing == "loadcell":
                self._loadcell()
            if self.n_steps % self.sense_every == 0:
                self._sense()

    def _sense(self):
        """One bus read: Present_Position and one effort register per joint. The rig knows its own command; from its own
        model it takes away what moving and holding the arm costs with nothing touching it."""
        n = len(ARM_JOINTS)
        pos = np.round(self.read_q() / TICK_RAD + self.noise.normal(0, SENSE_NOISE_TICKS, n))
        err = np.round(self.cmd / TICK_RAD) - pos
        if SENSE_REGISTER == "load":  # what the servo drives, from its own error; the rig scales it by the stall torque
            stall = self.m.actuator_forcerange[:5, 1]
            push = np.maximum(np.abs(err) * TICK_RAD - DEADBAND_RAD, 0)
            load = np.sign(err) * (push > 0) * np.minimum(LOAD_JUMP + np.round(1000 * SERVO_NM_PER_RAD * push / stall), 1000)
            servo = K_EST_SCALE * np.sign(load) * np.maximum(np.abs(load) - LOAD_JUMP, 0) / 1000 * stall
        else:  # the rig's own servo law, with the gain it believes
            servo = SERVO_NM_PER_RAD * K_EST_SCALE * np.sign(err) * np.maximum(np.abs(err) - DEADBAND_EST_TICKS, 0) * TICK_RAD
        self.qs = (self.qs + [pos * TICK_RAD])[-SENSE_AVG - 1:]
        vel = (self.qs[-1] - self.qs[0]) * SENSE_HZ / max(len(self.qs) - 1, 1)
        m, d = self.est_m, self.est_d
        d.qpos[self.qadr], d.qvel[self.dadr] = self.qs[-1], vel
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        mujoco.mj_comVel(m, d)
        free = np.zeros(m.nv)
        # gravity, Coriolis and damping. Inertia is left out: taken from encoder differences it lagged every reading, the
        # hard cap's too, by 50 ms, and lowered the worst free-move reading only from 9.8 to 8.8 N
        mujoco.mj_rne(m, d, 0, free)
        free = free[self.dadr] + (m.dof_damping[self.dadr] + SERVO_KV) * vel
        self.raw = (self.raw + [free - servo])[-int(TARE_S * SENSE_HZ) - 1:]
        jac = np.zeros((3, m.nv))
        mujoco.mj_jacSite(m, d, jac, None, self.tip)
        self.W = jac[:, self.dadr].T  # joint torques = W @ (force on the tip)
        self.axis_est = -d.site_xmat[self.tip].reshape(3, 3)[:, 2]  # the probe axis, as the rig believes
        self._estimate()
        if self.sensing == "tactile":
            self._pad()
            self.cap_f = max(self.cap_f, self.pad_n)
        # the cap uses the zero too: without it, gear friction reads as about 6 N of push and normal presses trip it
        self.cap_f = max(self.cap_f, self._axial(self._fit(np.mean(self.raw[-CAP_AVG - 1:-1] or self.raw, axis=0))))

    def _pad(self):
        """One read of the fingertip pad: per cell, the force pressing into the face, as whole kPa."""
        R, o = self.d.site_xmat[self.tip].reshape(3, 3), self.d.site_xpos[self.tip]
        load, f6 = np.zeros(PAD_CELLS), np.zeros(6)
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            b1, b2 = self.m.geom_bodyid[c.geom1], self.m.geom_bodyid[c.geom2]
            if self.probe_body not in (b1, b2):
                continue
            x, y, z = (c.pos - o) @ R  # the tip site's frame: the face is z = 0, the pad behind it z > 0
            if z > PAD_FACE_M:
                continue
            mujoco.mj_contactForce(self.m, self.d, i, f6)
            world = c.frame.reshape(3, 3).T @ f6[:3]
            push = max(float((world if b2 == self.probe_body else -world) @ R[:, 2]), 0.0)
            pts = np.array([x, y]) + self.spread
            pts = pts[np.linalg.norm(pts, axis=1) <= self.pad_r]  # the part of the disc on the pad
            if push and len(pts):
                ij = np.floor(pts / self.cell + np.array(PAD_CELLS) / 2).astype(int)
                np.add.at(load, (ij[:, 0], ij[:, 1]), push / len(pts))
        area = self.cell.prod()
        kpa = PAD_GAIN * load / area / 1000 + self.pad_rng.normal(0, PAD_NOISE_KPA, PAD_CELLS)
        self.pad_kpa = np.clip(np.round(np.where(kpa >= PAD_THRESHOLD_KPA, kpa, 0)), 0, PAD_MAX_KPA)
        self.pad_n = float(self.pad_kpa.sum() * area * 1000)

    def _loadcell(self):
        """Every physics step, the force along the probe; every 1 / LC_HZ, one HX711 sample of its mean since the last."""
        R, F = self.d.site_xmat[self.tip].reshape(3, 3), self.contact_force_vec()
        self.lc_sum += F @ R[:, 2] + LC_CROSS * (F @ R[:, 0])  # the tip site's +z points back up the probe: a push
        self.lc_k += 1
        if self.d.time >= self.lc_t:
            self.lc_t += 1 / LC_HZ
            self.lc_drift += self.lc_rng.normal(0, LC_DRIFT_N / np.sqrt(600 * LC_HZ))
            self.lc_n = LC_GAIN * self.lc_sum / self.lc_k + self.lc_drift + self.lc_rng.normal(0, LC_NOISE_N)
            self.lc_sum, self.lc_k = 0.0, 0
            self.cap_f = max(self.cap_f, self.lc_n)

    def pad_centre(self):
        """With sensing="tactile": where on the pad the pressure is centred, (x, y) in m in the tip site's frame, or None
        with nothing pressing."""
        if self.sensing != "tactile" or not self.pad_kpa.any():
            return None
        ij = np.indices(PAD_CELLS).reshape(2, -1).T
        centres = (ij + 0.5 - np.array(PAD_CELLS) / 2) * self.cell
        w = self.pad_kpa.reshape(-1)
        return w @ centres / w.sum()

    def _estimate(self):
        self.est_vec = self._fit(np.mean(self.raw[-SENSE_AVG - 1:-1] or self.raw, axis=0))
        self.est_axial = self._axial(self.est_vec)

    def tare(self, on=True):
        """Servo sensing: zero the force estimate on the last TARE_S of readings, or with on=False drop the zero again.
        Does nothing with the perfect sensor."""
        if self.sensing:
            self.zero = np.mean(self.raw[:-1] or self.raw, axis=0) if on else np.zeros(len(ARM_JOINTS))
            self._estimate()

    def tick(self):
        f = 0.0  # peak over the substeps, so short impacts aren't missed
        self.cap_f = 0.0
        for _ in range(self.substeps):
            self._servo()
            mujoco.mj_step(self.m, self.d)
            self.app.update(self.m, self.d)
            f = max(f, self.tip_force()) if not self.sensing else self.cap_f
            if f > HARD_FORCE_CAP_N:
                break
        if self.sensing and f <= HARD_FORCE_CAP_N:
            f = self.tip_force()  # with servo sensing, the averaged reading at the end of the tick (the cap uses a faster one)
        if self.d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number:
            raise SafetyStop("simulation went unstable (MuJoCo reset itself); restart with 'reset'")
        self.force_log.append((self.d.time, f))
        hits = self.collisions()
        self.seen_collisions.update(hits)
        if f > HARD_FORCE_CAP_N or hits:
            self._back_off()
            raise SafetyStop(f"tip force {f:.1f} N over hard cap {HARD_FORCE_CAP_N} N" if f > HARD_FORCE_CAP_N
                             else f"arm hit the rig: {', '.join(hits)}")
        if self.on_tick:
            self.on_tick(self)
        if self.realtime:
            self._wall += 1 / CONTROL_HZ
            delay = self._wall - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                self._wall = time.perf_counter()
        return f

    def _back_off(self, dist=0.01, ticks=15):
        """After a stop, pull the tip back along the tool axis so the servos stop pushing."""
        tip, axis = self.tip_pose()
        q, *_ = self.ik.solve(tip - dist * axis, axis, self.read_q(), iters=50)
        self.cmd = q
        self._drive(q)
        for _ in range(ticks * self.substeps):
            self._servo()
            mujoco.mj_step(self.m, self.d)
            self.app.update(self.m, self.d)

    def tip_force(self):
        """What a tip load cell reads: contact force on the probe along the tool axis (N).
        With sensing="current", the estimate from the servos instead; with "tactile", the fingertip pad; with "loadcell",
        the load cell's latest sample."""
        if self.sensing == "tactile":
            return self.pad_n
        if self.sensing == "loadcell":
            return self.lc_n
        if self.sensing:
            return self.est_axial
        axis = -self.d.site_xmat[self.tip].reshape(3, 3)[:, 2]  # the load cell's real axis
        return abs(self.tip_force_vec() @ axis)

    def tip_force_vec(self):
        """Contact force on the probe, arm frame (N). Sideways pushes (sliders, dials) need the
        whole vector; on the rig it would come from servo load or the soft wrist."""
        return super().tip_force_vec() if self.sensing else self.contact_force_vec()

    def contact_force_vec(self):
        """Sim truth: MuJoCo's contact force on the probe, arm frame (N)."""
        total = np.zeros(3)
        f6 = np.zeros(6)
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            b1, b2 = self.m.geom_bodyid[c.geom1], self.m.geom_bodyid[c.geom2]
            if self.probe_body not in (b1, b2):
                continue
            mujoco.mj_contactForce(self.m, self.d, i, f6)
            world = c.frame.reshape(3, 3).T @ f6[:3]  # force from geom1 on geom2
            total += world if b2 == self.probe_body else -world
        return total

    def tip_pose(self):
        """Where the controller believes the tip is: forward kinematics of the joint readings."""
        return self.ik.fk(self.read_q())

    # --- extras the sim can answer that hardware can't ---
    def true_controls(self):
        return appliance.moved(appliance.controls(self.params), appliance.fixture_pose(self.placement))

    def collisions(self):
        """Arm parts other than the probe touching the scene."""
        hits = set()
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            b1, b2 = self.m.geom_bodyid[c.geom1], self.m.geom_bodyid[c.geom2]
            for arm_b, other in ((b1, b2), (b2, b1)):
                if arm_b in self.arm_bodies and other not in self.arm_bodies and arm_b != self.probe_body:
                    g = c.geom2 if other == b2 else c.geom1
                    hits.add(f"{self.m.body(arm_b).name}->{self.m.geom(g).name or self.m.body(other).name}")
        return sorted(hits)
