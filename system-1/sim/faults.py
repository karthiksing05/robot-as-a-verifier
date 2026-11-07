"""Planted faults: real mechanical problems put into a compiled device model, so a run can catch a real failure.

    plant(arm.m, "stuck_button")        # before the run starts

Nothing here touches a verdict. The fault changes the physics, and affordances.py judges the result as usual.
"""
import mujoco

FAULTS = {
    "stuck_button": {"part": "button_2", "what": "button_2 jams after 0.3 mm of its 2.5 mm travel, short of its switch",
                     "travel_m": 0.0003},
}


def plant(model, name):
    """Returns the fault's description. Raises if this device doesn't have the part."""
    fault = FAULTS[name]
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, fault["part"])
    if joint < 0:
        raise ValueError(f"this device has no {fault['part']} to plant {name} on")
    model.jnt_range[joint][1] = fault["travel_m"]
    return fault["what"]
