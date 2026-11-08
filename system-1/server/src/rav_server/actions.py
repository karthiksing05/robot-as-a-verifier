"""What the robot offers a caller, as SystemStatus publishes it. A table rather than an import, so a server with no sim
can answer; tests/test_actions.py holds it to core/affordances.py and core/skills.py."""
from __future__ import annotations

from rav_interface import ActionSpec, ParamSpec

MAX_FORCE_N = 14.0  # the most a step may ask for: skills.MAX_FORCE_LIMIT_N, which leaves room under the 15 N hard cap (D21)


def _force(default: float) -> ParamSpec:
    return ParamSpec(name="force_limit", min=0.1, max=MAX_FORCE_N, default=default, unit="N", about="stop pushing at this force")


def reposition_action(dx_mm: float, dy_mm: float, yaw_deg: float) -> ActionSpec:
    """Offered only by a robot that can do it, with ranges from that device's data."""
    return ActionSpec(skill="reposition", kinds=["object"], params=[
        ParamSpec(name="dx_mm", min=-dx_mm, max=dx_mm, default=0.0, unit="mm", about="along the arm's x"),
        ParamSpec(name="dy_mm", min=-dy_mm, max=dy_mm, default=0.0, unit="mm", about="along the arm's y"),
        ParamSpec(name="yaw_deg", min=-yaw_deg, max=yaw_deg, default=0.0, unit="deg", about="about the vertical")],
        about="move the whole device on the desk. The scene then goes stale, so run explore before any further plan")


def manipulate_actions(stock_gripper: bool, open_deg: float = 105.0) -> list[ActionSpec]:
    """Offered only by a rig with a device file: hook_pull with the probe, pick and place with the stock gripper."""
    if stock_gripper:
        return [ActionSpec(skill="pick", kinds=["object"], about="the jaws on the object's faces, shut by the servo's load, lift it clear. OBSERVED, with what the jaws read"),
                ActionSpec(skill="place", kinds=["well"], params=[ParamSpec(name="force_limit", min=0.1, max=MAX_FORCE_N, default=3.0, unit="N", about="going down, stop at this"),
                                                             ParamSpec(name="drop_mm", min=0.0, max=120.0, default=0.0, unit="mm", about="0 lowers it in. Over 0, holds it with its grip point this far above where it sits once seated, clear of the well's surroundings, opens the jaws and lets it fall in")],
                           about="lower what the jaws hold into this well, let go, lift clear. Says how far above its seat it was let go")]
    return [ActionSpec(skill="hook_pull", kinds=["handle"], params=[
        ParamSpec(name="angle", min=0.0, max=open_deg, unit="deg", about="where to leave the handle, from shut. Past vertical it falls to its stop; from there, 0 draws it back over and lets it fall shut"),
        _force(6.0)], about="the pad under the handle's lip, swung about its hinge. A handle that needs a pinch grip is refused")]


ACTIONS = [
    ActionSpec(skill="press", kinds=["button"], params=[_force(6.0)], about="push along the part's normal, until the force limit or 4 mm past first contact"),
    ActionSpec(skill="flip", kinds=["toggle"], params=[_force(5.0)], about="push the lever across to its other side"),
    ActionSpec(skill="slide", kinds=["slider"], params=[
        ParamSpec(name="to", required=True, min=0.0, max=1.0, about="where to leave the knob along its travel. It refuses at run time if the knob is already there"),
        _force(5.0)], about="push the knob along its slot"),
    ActionSpec(skill="turn", kinds=["dial", "knob"], params=[
        ParamSpec(name="angle", required=True, min=-360.0, max=360.0, nonzero=True, unit="deg", about="about the part's axis, right-handed. It refuses at run time past a stop: see Control.turn_range_deg"),
        _force(5.0)], about="push a fin around its axis. A part that needs a pinch grip is refused"),
    ActionSpec(skill="push_latch", kinds=["door"], params=[_force(6.0)], about="push the pad on a latched door and let go, so it pops open"),
    ActionSpec(skill="observe", kinds=["display"], about="no motion: report what the display shows"),
]
