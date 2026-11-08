"""An arm left touching the scene by a stop can still get home: a contact it was already in may go on while it only gets
shallower, and going home first backs straight off it. Anything that makes a contact deeper, or a new one, still stops.
Run: uv run --extra sim pytest sim/tests/test_contact_recovery.py"""
import pathlib
import sys

import numpy as np
import pytest

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[2]
for d in (SYSTEM_1 / "core", SYSTEM_1 / "sim"):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

pytestmark = pytest.mark.sim


DEVICE = SYSTEM_1.parent / "appliances" / "kettle-base" / "device.yaml"


@pytest.fixture
def arm():
    pytest.importorskip("mujoco")
    if not DEVICE.exists():
        pytest.skip("no appliances/kettle-base")
    import sim_rig
    import skills

    # the true contact force: the servo estimate has no history to go on after the arm is put in place
    a = sim_rig.make_rig(0, slop=True, offsets=0, stiffness=18.0, sensing="perfect", device=str(DEVICE), effector="stock").arm
    skills.go_home(a)
    return a


def _into_contact(arm):
    """Put the arm where its wrist camera, not the fingertips, touches the kettle, as a hook_pull's stop did in a model
    run and its back-off along the tool didn't clear: the tool level, moved in over the lid's handle until something
    other than the tool touches."""
    import mujoco

    handle = next(p for p in arm.world.truth(arm.m, arm.d) if p.id == "handle_1").pos
    for dx in np.arange(-0.06, 0.03, 0.0005):
        q, ok, *_ = arm.ik.solve(handle + [dx, 0.0, 0.02], np.array([1.0, 0.0, 0.0]), arm.home_q)
        arm.d.qpos[arm.qadr] = q - arm.q_off
        arm.d.qvel[:] = 0
        mujoco.mj_forward(arm.m, arm.d)
        if ok and arm._hits() and not any(arm._tool(i) is not None for i in range(arm.d.ncon)):
            arm.cmd = q.copy()
            arm._drive(q)
            for _ in range(200):  # let the servos settle there, sagging onto it as the stop's back-off does
                arm._servo()
                mujoco.mj_step(arm.m, arm.d)
            if not arm._hits():
                continue
            arm.touching = {k: dist for k, (dist, _) in arm._hits().items()}  # what a stop's handler records
            return q
    pytest.skip("found no pose where the wrist camera touches the kettle")


def test_home_from_a_pose_in_contact(arm):
    import skills

    _into_contact(arm)
    assert arm.touching
    skills.go_home(arm)  # before: every move home began in the contact, and stopped again
    assert not arm._hits()
    assert np.linalg.norm(arm.ik.fk(arm.read_q())[0] - arm.ik.fk(arm.home_q)[0]) < 0.01


def test_going_deeper_into_a_contact_still_stops(arm):
    import skills
    from rig import SafetyStop

    q = _into_contact(arm)
    deeper, *_ = arm.ik.solve(arm.ik.fk(q)[0] + [0.006, 0.0, 0.0], np.array([1.0, 0.0, 0.0]), q)
    with pytest.raises(SafetyStop, match="hit the rig"):
        skills.move_joints(arm, deeper)
