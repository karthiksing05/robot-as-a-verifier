"""The sim's rig: a device on the desk, the simulated SO-101 and its cameras, as explore.py and the tool server use
them. Everything random is drawn from the seed in a fixed order, so the same arguments give the same rig every run."""
import os
import sys
import tempfile

import numpy as np

import rig
import robot
import sensors
import world

HARDWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hardware")


def make_rig(seed=None, placement="nominal", ideal=False, offsets=None, slop=False, stiffness=None, sensing="perfect",
             depth=False, stereo=False, realtime=False, device=None, rev="B", effector="stock", mounts=None, driver="sim"):
    """seed: a generated device (None: preset C), moved on the desk with placement="random". ideal: no sensor noise and
    no joint error. offsets: joint calibration error, uniform in +-offsets deg on all five joints (default N(0, 0.5 deg)
    on four). stiffness: robot.SERVO_NM_PER_RAD, for slop. sensing: "perfect", "current", "tactile" or "loadcell" (all
    but perfect need slop). depth: a D405 on the wrist and the phone for the survey, else the USB wrist camera alone.
    device: a device file (cad_device.py) instead of a generated device, with rev: its revision or fault choices.
    effector: "stock" (the SO-101's own gripper alone, as the real arm is) or "probe" (the fingertip probe and pad, kept
    as a sim-only reference).
    mounts: {root: "clamped" | "free"} over the device file's.
    driver="real": the rig's arm is real_arm.RealArm, torque on, over a simulated motor bus whose servos are the SimArm
    (see real_driver). The cameras and the device's readout stay the sim's."""
    rng = np.random.default_rng(seed or 0)  # the same placement and joint offsets every run
    if device:
        import cad_device
        import perceive

        w = cad_device.build_cad_world(device, rev, mounts=mounts)
        if placement == "random":
            w = cad_device.build_cad_world(device, rev, placement=w.random_placement(rng), mounts=mounts)
        perceive.set_table_z(w.table_z)
    else:
        w = world.build_world(seed)
        if placement == "random":
            w = world.build_world(seed, placement=w.random_placement(rng))
    if offsets is not None:
        joint_offsets = np.radians(rng.uniform(-offsets, offsets, 5))
    elif ideal:
        joint_offsets = None
    else:
        joint_offsets = np.radians(np.r_[rng.normal(0, 0.5, 4), 0])
    if stiffness:
        robot.SERVO_NM_PER_RAD = stiffness  # read by the servo model at run time
    arm = robot.SimArm(world=w, joint_offsets=joint_offsets, realtime=realtime, slop=slop,
                       sensing=None if sensing == "perfect" else sensing, effector=effector)
    seed = seed or 0
    phone = sensors.PhoneCamera(arm, ideal=ideal, seed=seed + 1) if depth else None
    wrist = sensors.WristCamera(arm, ideal=ideal, seed=seed + 2, stereo=stereo, usb=not depth)
    if driver == "real":
        return rig.Rig(real_driver(arm, realtime), wrist, phone, name=f"sim {w.name} through RealArm")
    return rig.Rig(arm, wrist, phone, name=f"sim {w.name}")


def real_driver(sim, pace=False):
    """real_arm.RealArm over hardware/tests/fake_bus.py, which steps sim one control tick per goal written and reads
    its encoders back in raw steps: the real driver's conversions, force estimate and hard cap on the sim's servos.
    sim needs slop and sensing="current" or "tactile": RealArm estimates force from the servos, and with "tactile"
    reads the sim's pad as its own (fake_bus.FakePad). The bus opens no port, so enable() here moves nothing real.
    The SimArm stays at arm.bus.fake.sim, for sim truth."""
    assert sim.sensing in ("current", "tactile"), f"RealArm senses with the servos and a pad, not sensing={sim.sensing}"
    for p in (HARDWARE, os.path.join(HARDWARE, "tests")):  # after core and sim, so they shadow neither
        if p not in sys.path:
            sys.path.append(p)
    import fake_bus  # here, so the sim alone needs no LeRobot
    import real_arm
    pad = fake_bus.FakePad(sim) if sim.sensing == "tactile" else None
    arm = real_arm.RealArm(fake_bus.make(sim, tempfile.mkdtemp(prefix="fake_bus_")), app=sim.app, pad=pad, pace=pace)
    arm.press_down, arm.press_depth = sim.press_down, sim.press_depth  # the sim presses along the normal, to contact
    arm.table_z, arm.workspace, arm.standoff, arm.stall_m, arm.guard_speed = (  # the sim's desk, camera, contact test
        sim.table_z, sim.workspace, sim.standoff, sim.stall_m, sim.guard_speed)
    arm.hard_cap_n = rig.HARD_FORCE_CAP_N  # the sim's cap, not the real arm's
    arm.part_shift = None  # the real camera's offset, which the sim's doesn't have
    arm.noise_n = sim.noise_n  # the sim servos' noise, not the real arm's measured floor
    arm.noise_axial = pad.noise_n if pad else sim.noise_n
    arm.enable(confirm=True)
    return arm
