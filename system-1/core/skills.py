"""Scripted skills: plan step in, guarded motion and a sensor-backed verdict out.

A step is the plan's format: {"skill", "target", "params": {...}}. Every skill
approaches 30 mm out along the control's normal, moves in slowly until a force
or travel limit, and retreats. Verdicts come from measured force/travel and the
appliance's own switch readout, never from the commanded motion.
"""
import math

import numpy as np

from rig import CONTACT_N, CONTROL_HZ, HARD_FORCE_CAP_N, SafetyStop

APPROACH_M = 0.03
TIP_SPEED = 0.1          # m/s, free-space cap from the spec's hard limits
JOINT_SPEED = 1.2        # rad/s
APPROACH_SPEED = 0.02    # m/s for the first 20 mm of the guarded move
SLOW_ZONE_M = 0.01       # creep for the last 10 mm, so a control up to 10 mm proud of CAD isn't hit fast
CONTACT_SPEED = 0.003    # m/s in the slow zone and through contact; at 6 mm/s one tick's step overshot the limit by 3 N
# With force estimated from the servos (arm.sensing), a guarded move zeroes it (arm.tare()) at rest and again after
# creeping this long, and only then goes by it, the hard cap aside: moving joints' friction reads as a push.
TARE_AFTER_S = 0.3
SENSED_MOVE_S = 0.6      # and no move_joints is shorter than this
MAX_FORCE_LIMIT_N = 14.0 # leaves room for one tick of overshoot under the hard cap
# When the pose is right, first contact reads 0 to 2 mm in front of the CAD surface (the flat
# pad touches edge-first when pressed off-axis). Missing a 3 mm cap and hitting the panel reads
# about 2 mm behind it. Outside this band, the probe probably didn't land on the control.
CONTACT_OFFSET_OK_MM = (-1.5, 3.5)
DEFAULTS = {"force_limit": 6.0, "hold": 1.0}
SKILLS = ("press", "press_hold", "push_latch")


# --- motion primitives ---

def move_joints(arm, q_goal):
    q0 = arm.cmd.copy()
    p0, _ = arm.ik.fk(q0)
    p1, _ = arm.ik.fk(q_goal)
    # 1.6x because a cosine profile peaks at pi/2 of its mean speed
    T = max(1.6 * np.linalg.norm(p1 - p0) / TIP_SPEED, np.max(np.abs(q_goal - q0)) / JOINT_SPEED, 0.2)
    if arm.sensing:  # the servo estimate has no inertia: a 12 mm move in 0.2 s read as 18 N and stopped the arm
        T = max(T, SENSED_MOVE_S)
    n = max(1, int(T * CONTROL_HZ))
    for i in range(1, n + 1):
        s = 0.5 - 0.5 * math.cos(math.pi * i / n)
        arm.send(q0 + s * (q_goal - q0))
        arm.tick()
    for _ in range(10):
        arm.send(q_goal)
        arm.tick()


def move_line(arm, p_to, axis, speed):
    """Straight tip line from the current command, re-solving IK every tick."""
    q = arm.cmd.copy()
    p_from, _ = arm.ik.fk(q)
    n = max(1, int(np.linalg.norm(p_to - p_from) / speed * CONTROL_HZ))
    for i in range(1, n + 1):
        q, *_ = arm.ik.solve(p_from + (p_to - p_from) * i / n, axis, q, iters=30)
        arm.send(q)
        arm.tick()


def go_home(arm):
    arm.status = "home"
    move_joints(arm, arm.home_q)


def goto(arm, pos, axis=(0.7, 0, -0.7)):
    pos = np.asarray(pos, float)
    arm.check_workspace(pos)
    q, ok, err, ang = arm.ik.solve(pos, np.asarray(axis, float), arm.cmd)
    if not ok:
        raise SafetyStop(f"unreachable: best IK is {err * 1000:.0f} mm off")
    arm.status = f"goto {np.round(pos, 3).tolist()}"
    move_joints(arm, q)
    return ang


# --- validation (runs before anything moves) ---

def validate(arm, step):
    skill, target = step.get("skill"), step.get("target")
    params = {**DEFAULTS, **step.get("params", {})}
    if skill not in SKILLS:
        return f"unknown skill '{skill}' (have: {', '.join(SKILLS)})"
    c = arm.controls.get(target)
    if c is None:
        return f"unknown target '{target}' (have: {', '.join(arm.controls)})"
    if skill not in c.skills:
        if c.requires == "pinch":
            return f"{target} needs a pinch grip; no allowed skill provides pinch (no-thumbs rule)"
        return f"{skill} can't actuate {target} (allowed: {', '.join(c.skills) or 'none'})"
    if not all(isinstance(v, (int, float)) for v in params.values()):
        return f"params must be numbers, got {params}"
    if not 0 < params["force_limit"] <= MAX_FORCE_LIMIT_N:
        return f"force_limit must be between 0 and {MAX_FORCE_LIMIT_N:g} N (hard cap is {HARD_FORCE_CAP_N:g} N)"
    if skill == "press_hold" and params["hold"] < 0.1:
        return "hold must be at least 0.1 s"
    if skill == "push_latch" and arm.app.door_open:
        return "door is already open (type reset to close it)"
    for off in (APPROACH_M, -c.travel_mm / 1000):
        p = c.pos + off * c.normal
        _, ok, err, _ = arm.ik.solve(p, -c.normal, arm.cmd)
        if not ok:
            return f"{target} is out of reach ({err * 1000:.0f} mm short)"
        try:
            arm.check_workspace(p)
        except SafetyStop as e:
            return str(e)
    return None


# --- skills ---

def run_step(arm, step):
    """Validate, execute, judge. Always returns a result dict; never raises on a failed test."""
    result = {"skill": step.get("skill"), "target": step.get("target"), "verdict": "REFUSED"}
    err = validate(arm, step)
    if err:
        result["reason"] = err
        return result
    params = {**DEFAULTS, **step.get("params", {})}
    c = arm.controls[step["target"]]
    arm.seen_collisions = set()
    t0 = arm.d.time
    log_start = len(arm.force_log)
    try:
        if step["skill"] == "push_latch":
            result.update(_push_latch(arm, c, params))
        else:
            result.update(_press(arm, c, params, hold=params["hold"] if step["skill"] == "press_hold" else 0.0))
    except SafetyStop as e:
        result.update(verdict="ABORTED", reason=f"safety stop: {e}")
        arm.tare(False)
        try:
            go_home(arm)
        except SafetyStop:
            pass  # arm has already backed off; leave it there
    result["duration_s"] = round(arm.d.time - t0, 2)
    result["collisions"] = sorted(arm.seen_collisions)
    result["force_trace"] = arm.force_log[log_start:]
    arm.status = "idle"
    return result


def _guarded_push(arm, c, force_limit, travel_m, label):
    """Approach, then creep in along -normal until force_limit or travel_m past first contact."""
    axis = -c.normal
    pre = c.pos + APPROACH_M * c.normal
    q, ok, _, ang = arm.ik.solve(pre, axis, arm.cmd)
    arm.status = f"{label}: approach"
    move_joints(arm, q)

    arm.status = f"{label}: guarded push"
    arm.tare()  # does nothing with the perfect sensor
    depth, contact_at, peak, stop, creep = 0.0, None, 0.0, None, 0
    armed = not arm.sensing or arm.axial_sensor  # a sensor on the probe needs no tare, so it counts from the start
    contact_n = max(CONTACT_N, arm.noise_axial)  # tip_force() is along the probe
    max_depth = APPROACH_M + travel_m + 0.006
    while stop is None:
        f = arm.tip_force() if armed else 0.0
        # slow down as force approaches the limit so one tick can't overshoot it much
        if depth < APPROACH_M - SLOW_ZONE_M and contact_at is None:
            speed = APPROACH_SPEED
        else:
            speed = CONTACT_SPEED * float(np.clip(1 - f / force_limit, 0.15, 1.0))
        depth += speed / CONTROL_HZ
        q, *_ = arm.ik.solve(pre + depth * axis, axis, q, iters=30)
        arm.send(q)
        f = arm.tick()
        if not armed:
            f = 0.0  # until the creep's tare, only the hard cap (in tick) goes by the reading
        peak = max(peak, f)
        tip, _ = arm.tip_pose()
        if contact_at is None and f > contact_n:
            contact_at = tip
        travel = 0.0 if contact_at is None else float((tip - contact_at) @ axis)
        if f >= force_limit:
            stop = "force_limit"
        elif contact_at is not None and travel >= travel_m:
            stop = "travel"
        elif depth > max_depth:
            stop = "no_contact" if contact_at is None else "max_depth"
        creep += speed < APPROACH_SPEED
        if creep == 1:
            crept = (tip, depth)
        if creep == round(TARE_AFTER_S * CONTROL_HZ):
            if arm.sensing and stop is None and contact_at is None and (tip - crept[0]) @ axis < (depth - crept[1]) / 2:
                # the probe fell behind its creep: something it doesn't feel yet holds it (with servo sensing alone, a
                # tare would hide that force; a pad misses its rim)
                contact_at, stop = tip, "held"
            arm.tare()
            armed = True
    return {"pre": pre, "axis": axis, "q": q, "stop": stop, "peak": peak, "travel": travel,
            "contact": contact_at is not None, "axis_err_deg": round(ang, 1),
            # how far in front of the CAD surface the probe first touched; a localization check
            "contact_offset_mm": None if contact_at is None else round(float((contact_at - c.pos) @ c.normal) * 1000, 1)}


def _missed(g):
    """Why the probe probably didn't land on the control, or None if contact looked right."""
    off = g["contact_offset_mm"]
    if off is None:
        return "no contact: control is not where the CAD says"
    lo, hi = CONTACT_OFFSET_OK_MM
    if not lo <= off <= hi:
        return (f"first contact {abs(off):g} mm {'in front of' if off > 0 else 'behind'} the CAD surface, "
                f"so the probe hit something else. Run look")
    return None


def _press(arm, c, params, hold):
    label = f"{'press_hold' if hold else 'press'} {c.name}"
    idx = int(c.name[-1]) - 1
    switched = False
    # stop at 90% of CAD travel: past the 70% switch point, short of slamming the bottom stop
    g = _guarded_push(arm, c, params["force_limit"], params.get("travel_mm", 0.9 * c.travel_mm) / 1000, label)
    switched |= bool(arm.app.switches[idx])

    held_on = 0
    if hold:
        arm.status = f"{label}: hold {hold:.1f}s"
        n = int(hold * CONTROL_HZ)
        for _ in range(n):
            arm.send(g["q"])
            f = arm.tick()
            g["peak"] = max(g["peak"], f)
            held_on += bool(arm.app.switches[idx])
        switched |= held_on > 0

    lcd = arm.app.lcd
    arm.status = f"{label}: retreat"
    move_line(arm, g["pre"], g["axis"], 0.03)
    arm.tare(False)  # only once clear: dropped while pressing, the zero's friction and hidden force read as 16 N

    out = {"peak_force_n": round(g["peak"], 2), "travel_mm": round(g["travel"] * 1000, 2),
           "stop": g["stop"], "switch": switched, "lcd": lcd, "axis_err_deg": g["axis_err_deg"],
           "contact_offset_mm": g["contact_offset_mm"], "force_limit_n": params["force_limit"]}
    if hold:
        out["switch_held_frac"] = round(held_on / int(hold * CONTROL_HZ), 2)
    limit = f"{params['force_limit']:g} N"
    missed = _missed(g)
    if switched and (not hold or out["switch_held_frac"] > 0.9):
        out.update(verdict="PASS", reason=f"switch closed at {out['peak_force_n']} N peak, {out['travel_mm']} mm travel")
    elif missed:
        out.update(verdict="MISSED", reason=missed)
    elif hold and switched:
        out.update(verdict="FAIL", reason=f"switch dropped out during hold ({out['switch_held_frac']:.0%} on)")
    elif g["stop"] == "force_limit" and g["travel"] < 0.5e-3 and params["force_limit"] >= 2 * c.expected_force_n:
        # only call it stuck if we pushed well past what the CAD says the button needs
        out.update(verdict="FAIL", reason=f"stuck: hit {limit} limit with only {out['travel_mm']} mm travel")
    elif g["stop"] == "force_limit":
        out.update(verdict="FAIL", reason=f"no switch: stopped by the {limit} limit after {out['travel_mm']} mm "
                                          f"(CAD says it needs up to {c.expected_force_n:g} N)")
    else:
        out.update(verdict="FAIL", reason=f"no switch: moved {out['travel_mm']} mm, stopped by {g['stop']}")
    return out


def _push_latch(arm, c, params):
    label = f"push_latch {c.name}"
    g = _guarded_push(arm, c, params["force_limit"], c.travel_mm / 1000 + 0.0005, label)
    arm.status = f"{label}: release"
    move_line(arm, g["pre"], g["axis"], 0.03)
    arm.tare(False)
    for _ in range(CONTROL_HZ):  # give it a second to pop
        arm.send(arm.cmd)
        arm.tick()
    opened = arm.app.door_open
    out = {"peak_force_n": round(g["peak"], 2), "travel_mm": round(g["travel"] * 1000, 2),
           "stop": g["stop"], "door_open": opened, "contact_offset_mm": g["contact_offset_mm"], "lcd": arm.app.lcd, "axis_err_deg": g["axis_err_deg"],
           "force_limit_n": params["force_limit"]}
    missed = _missed(g)
    if opened:
        out.update(verdict="PASS", reason="door popped open")
    elif missed:
        out.update(verdict="MISSED", reason=missed)
    else:
        out.update(verdict="FAIL", reason=f"door stayed latched after {g['peak']:.1f} N push")
    return out
