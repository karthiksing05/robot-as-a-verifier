"""Planted faults: real problems put into a compiled device, so a run can catch a real failure.

    plant(arm.m, "stuck_button")                                      # before the run starts
    plant(arm.m, "stuck_slider", "slider_1", arm.app, arm.d)          # another part, and the faults that need more
    resolve(arm.m, "random", seed=7)                                  # ("stuck_dial", "dial_1"): any fault this device can take

Nothing here touches a verdict. The fault changes the physics or the wiring, and affordances.py judges the result as usual.
Any fault works on any part of its kind, so a run can't be passed by knowing where the fault always is.
"""
import mujoco
import numpy as np

import device

FAULTS = {
    "stuck_button": {"kind": "button", "part": "button_2", "what": "button_2 jams after 0.3 mm of its 2.5 mm travel, short of its switch",
                     "travel_m": 0.0003},
    "stuck_slider": {"kind": "slider", "part": "slider_1", "what": "slider_1 is jammed where it is", "hold": 2e-5},
    "stuck_dial": {"kind": "dial", "part": "dial_1", "what": "dial_1 is jammed where it is", "hold": 0.002},
    "stiff_toggle": {"kind": "toggle", "part": "toggle_1", "what": "toggle_1 is too stiff to cross its centre", "hold": 0.02},
    "jammed_door": {"kind": "door", "part": "door_1", "what": "door_1 can't be pushed far enough to work its latch"},
    "dead_button": {"kind": "button", "part": "button_1", "what": "button_1 moves, but its switch is wired to nothing"},
    "dead_dial": {"kind": "dial", "part": "dial_1", "what": "dial_1 turns, but it's wired to nothing"},
}


def _joints(model):
    return {model.joint(j).name for j in range(model.njnt)}


def options(model):
    """Every (fault, part) this device can take, in a fixed order."""
    names = sorted(_joints(model))
    return [(fault, part) for fault, f in FAULTS.items() for part in names if part.rsplit("_", 1)[0] == f["kind"] and part.rsplit("_", 1)[-1].isdigit()]


def resolve(model, spec, seed=None):
    """(fault, part) from "stuck_button", "stuck_button:button_1" or "random"."""
    if spec == "random":
        choices = options(model)
        if not choices:
            raise ValueError("this device has no part a fault can go on")
        return choices[int(np.random.default_rng(seed or 0).integers(len(choices)))]
    name, _, part = spec.partition(":")
    if name not in FAULTS:
        raise ValueError(f"no fault called {name}. Known: {', '.join(FAULTS)}")
    return name, part or FAULTS[name]["part"]


def plant(model, name, part=None, mcu=None, data=None):
    """Returns the fault's description. Raises if this device doesn't have the part, or isn't given what the fault needs:
    mcu for a wiring fault, data for a jam around where the part is now (else its starting position)."""
    fault = FAULTS[name]
    part = part or fault["part"]
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, part)
    if joint < 0 or part.rsplit("_", 1)[0] != fault["kind"]:
        raise ValueError(f"this device has no {fault['kind']} called {part} to plant {name} on")
    adr = model.jnt_qposadr[joint]
    q = float(data.qpos[adr] if data is not None else model.qpos0[adr])
    if "travel_m" in fault:
        model.jnt_range[joint][1] = fault["travel_m"]
    elif "hold" in fault:
        model.jnt_range[joint] = [q - fault["hold"], q + fault["hold"]]
    elif name == "jammed_door":
        model.jnt_range[joint][0] = 0.1 * model.jnt_range[joint][0]
    elif name.startswith("dead_"):
        if mcu is None:
            raise ValueError(f"{name} is a wiring fault: pass the device's mcu")
        mcu.dead.add(device.channel_of(part))
    return fault["what"].replace(fault["part"], part)
