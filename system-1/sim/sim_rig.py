"""The sim's rig: a device on the desk, the simulated SO-101 and its cameras, as explore.py and the tool server use
them. Everything random is drawn from the seed in a fixed order, so the same arguments give the same rig every run."""
import numpy as np

import rig
import robot
import sensors
import world


def make_rig(seed=None, placement="nominal", ideal=False, offsets=None, slop=False, stiffness=None, sensing="perfect",
             depth=False, stereo=False, realtime=False):
    """seed: a generated device (None: preset C), moved on the desk with placement="random". ideal: no sensor noise and
    no joint error. offsets: joint calibration error, uniform in +-offsets deg on all five joints (default N(0, 0.5 deg)
    on four). stiffness: robot.SERVO_NM_PER_RAD, for slop. sensing: "perfect", "current", "tactile" or "loadcell" (all
    but perfect need slop). depth: a D405 on the wrist and the phone for the survey, else the USB wrist camera alone."""
    rng = np.random.default_rng(seed or 0)  # the same placement and joint offsets every run
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
                       sensing=None if sensing == "perfect" else sensing)
    seed = seed or 0
    phone = sensors.PhoneCamera(arm, ideal=ideal, seed=seed + 1) if depth else None
    wrist = sensors.WristCamera(arm, ideal=ideal, seed=seed + 2, stereo=stereo, usb=not depth)
    return rig.Rig(arm, wrist, phone, name=f"sim {w.name}")
