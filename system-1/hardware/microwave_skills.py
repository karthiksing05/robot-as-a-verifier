"""The MW-1 microwave's skills, for the real arm and the sim's: its buttons pressed straight in on an upright panel, and
its door pulled open by the handle's bar and pushed shut again. Nothing here is used for the centrifuge.

As centrifuge_skills: each skill takes one point and runs a few straight lines and arcs from it, every pose checked for
reach before anything moves (RuntimeError: the backend reports it as REFUSED). The door's handle is the part itself
when the scan or System 2 has one (kind handle), else a named button (TIME, POWER, STOP, +30s, START) plus its offset
from appliances/microwave/device.yaml. That file's product frame is the device frame here (x toward the arm, y right
as seen from the arm, z up), so its numbers are used as they are. They are the CAD's, not yet measured on the real box.

Contact: the sim's force estimate stops a press or the door's close at a force limit. The real arm's estimate drifts too
much for that (real_arm.RealArm.stall_m), so on it the press goes to a fixed depth and the close stops on a stall. The
door's pull, on either arm, stops when the tip falls PULL_LAG behind its command: the door won't come, and how far it
got is measured from the arm's joint readings there."""
import math
import time

import numpy as np

import affordances
import real_skills
import skills
from centrifuge_skills import PAN_XY, _check, _hold, _line, _rot, device_frame
from manipulate import SAG_FOLLOW, _swing_roll
from rig import CONTROL_HZ

# --- the device, from device.yaml (mm, device frame) ---
BUTTONS = {"TIME": (72.0, 48.3, 152.0), "POWER": (72.0, 48.3, 127.0), "STOP": (72.0, 48.3, 102.0),
           "+30S": (72.0, 92.8, 152.0), "START": (72.0, 92.8, 127.0)}  # each cap's face, 7 mm proud of the panel
HANDLE = (84.0, 5.45, 151.0)   # the middle of the handle's round bar, upright, 33 mm long, 12 mm off the door
HINGE = (66.9, -119.9, 151.0)  # the door's hinge line, upright, on the arm's left; opening turns it about -z
HINGE_AXIS = (0.0, 0.0, -1.0)
BAR_D = 0.0127                 # the bar's diameter
CHANNELS = {"START", "STOP", "TIME", "POWER", "+30s", "DOOR"}  # a mapped readout's names for btn_start ... and door
DOOR_OPENS_DEG = 130.0        # where the manual and CAD say the door stops (Rev A: seized; Rev B: 145)

# --- mw_press: straight in, level, whatever the tool's tilt ---
PRESS_OUT = 0.02       # start this far out from the cap's face
PRESS_DEPTH = 0.004    # and command this far in past it: the cap travels 1.5 mm and switches at 1.0
PRESS_DEPTH_REAL = 0.012  # the real arm gives under load (the centrifuge's presses needed 20 mm): a guess, untested
PRESS_TILTS = (0, 10, 20, 30)  # the tool this far below level (deg), flattest first that reaches. The push stays level
PRESS_SPEED, PRESS_HOLD_S = 0.008, 0.3  # at 15 mm/s the sim's cap bottomed and the force jumped past 15 N in a tick
PRESS_SLOW, PRESS_SLOW_FROM = 0.003, 0.006  # and slower over the last of the way: START at 8 mm/s did it on the stiffer arm
PRESS_N = 6.0          # sim: stop pushing at this over the estimate's noise (the cap bottoms at 3 N)

# --- door_open: the jaws round the bar, centred, at its middle, drawn round the hinge's arc ---
GRIP_SPARE = 0.005     # the jaws open to the bar's width plus this a side
JAW_FACE_X = 0.003     # the fixed jaw's tip (the arm's tip point) to its inner face (manipulate.JAW_FACE_X)
GRIP_DEPTH = 0.008     # the jaws' tips this far past the bar's middle: the door's face is 18.5 mm behind it
GRIP_OUT = 0.04        # going in to the bar from this far out along the tool
BACK_OFF = 0.02        # and off it this far, once let go: 40 back with the tool level, 280 mm out, is out of reach
GRIP_TILTS = (0, 10, 20, 30)
GAP_PER_OPEN = real_skills.GAP_PER_OPEN  # real gripper: m of gap per unit of opening
SIM_GAP = (0.0158, 0.075)  # sim gripper: the gap at 0 rad, and per rad (manipulate.JAW_GAP)
SQUEEZE = 0.0          # real: shut to the calibrated close, which the bar stops short (not real_skills' overdrive)
PULL_DEG = 45.0        # default: open this far. Past ~50 deg the leaf comes in beside the jaws
PULL_SPEED, UNLATCH_SPEED, UNLATCH_DEG = 0.02, 0.006, 5.0  # m/s along the arc; slower through the latch
PULL_LAG = 0.025       # the tip this far behind its command: the door won't come (the sim's force estimate read 14.6 N
                       # on the latch alone, near its 15 N cap; Rev A's seized hinge needs 20 N at the bar)
IN_LAG = 0.008         # going in to the bar, the tip this far behind its command has met something (the sim's force
                       # estimate read 7.6 N in free air there)

# --- door_close: the shut jaws on the bar's front, pushed round to shut ---
PUSH_IN = 0.001        # the tip this far into the bar's front
SHUT_AT = 1.0          # pushed to this far short of shut, inside the latch's 2 deg pull-in: pushed on past shut, the
                       # sim's estimate jumped from 3 N to the 15 N cap in one tick at the door's stop
PUSH_N = 5.0           # sim: pushing the free door read 2-3 N; at the stop it jumped from 3 to 11 and on past the 15 N cap

CLOSE_FROM = 15.0      # the push starts this much further open than the door is believed to be, so it meets the bar
CLOSE_START, CLOSE_MAX = 55.0, 65.0  # wherever it really is, and from no nearer shut than CLOSE_START: from 42 deg,
                       # with the door at 28, the way in met it (sim)
CLEAR_UP, CLEAR_SPEED = 0.06, 0.02  # up this far from the bar's height (over the 33 mm bar's top) before going home
STEP_DEG = 3.0


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _name(p):
    return str(p.meta.get("name") or p.id).upper().split("_")[0]


def _jaws(arm, gap):
    """Jaws to a gap (m) between their tips; at or under 0, shut on whatever is between them."""
    if hasattr(arm, "bus"):  # RealArm: real_skills' fraction of the calibrated range
        real_skills.gripper(arm, SQUEEZE if gap <= 0 else gap / GAP_PER_OPEN)
    else:  # SimArm: the gripper joint's angle; an object stops it short
        arm.grip(-0.17 if gap <= 0 else (gap - SIM_GAP[0]) / SIM_GAP[1], 0.6)


def _radial(at, tilt_deg):
    """The tool's axis tilt below level in the upright plane through the pan axis and at: the only one a 5-joint arm
    can point there."""
    r = np.r_[np.asarray(at[:2], float) - PAN_XY, 0.0]
    r /= np.linalg.norm(r)
    t = math.radians(tilt_deg)
    return math.cos(t) * r - math.sin(t) * np.array([0.0, 0.0, 1.0])


def _go(arm, pts, axes, speed, bias, limit=None, slow=None, along=True, lag_max=None, follow=False):
    """The tip through pts (one tool axis each) at speed, the bias held. limit (N): on an arm whose force estimate is
    trusted (no stall_m: the sim) it stops once the estimate passes it, on the real arm the stall does
    (affordances._stall). slow(i) -> a slower speed for the leg into point i, or None. Returns (index of the last
    point reached, why it stopped short or None, peak N). along: the force along the tool (a push), else its whole
    size (a pull, which the estimate along the tool reads as nothing). lag_max (m), on any arm: stop once the tip
    falls this far behind its command, as when what it pulls won't come. follow: the bias follows the sag as it
    changes along the way (manipulate._line), in place."""
    q, peak = arm.cmd - bias, 0.0
    guard = limit is not None
    stall = affordances._stall(arm) if guard and arm.stall_m else None
    if guard:
        arm.tare()
    try:
        a = arm.ik.fk(q)[0]
        for k, (b, ax) in enumerate(zip(pts, axes)):
            d = np.linalg.norm(b - a)
            if d < 1e-6:
                continue
            v = (slow(k) if slow else None) or speed
            m, n = (b - a) / d, max(1, math.ceil(d / v * CONTROL_HZ))
            for i in range(1, n + 1):
                to = a + (b - a) * i / n
                q1, ok, *_ = arm.ik.solve(to, ax, q, iters=30)
                if not ok:  # the solver's best guess can point the arm anywhere
                    return k - 1, f"out of reach at {np.round(to * 1000).astype(int).tolist()} mm", peak
                q = affordances._toward(arm, q1, bias)
                arm.send(q + bias)
                arm.tick()
                if follow:
                    bias += SAG_FOLLOW * (q - arm.read_q())
                f = float(arm.tip_force() if along else np.linalg.norm(arm.tip_force_vec()))
                peak = max(peak, f)
                if stall is not None and stall((to - arm.tip_pose()[0]) @ m)[0]:
                    return k - 1, "stalled", peak
                if guard and stall is None and f > limit:
                    return k - 1, f"met {f:.1f} N", peak
                lag = float(np.linalg.norm(to - arm.tip_pose()[0]))
                if lag_max and lag > lag_max:
                    return k - 1, f"fell {lag * 1000:.0f} mm behind its path at {f:.1f} N", peak
            a = b
        return len(pts) - 1, None, peak
    finally:
        if guard:
            arm.tare(False)


def _clear(arm, bias, axis):
    """Straight up over the door's top, the tool as it is: a joint move home from beside the open door swept the jaws
    through its leaf and pushed it 8 deg shut (sim)."""
    arm.status = "clear of the door"
    tip = arm.ik.fk(arm.cmd - bias)[0]
    _go(arm, [tip + CLEAR_UP * np.array([0.0, 0.0, 1.0])], [axis], CLEAR_SPEED, bias)


def _approach(arm, label, at, axis, q0):
    arm.status = f"{label}: approach"
    return affordances._approach(arm, at, axis, label, q0)[1]


# --- the press ---

def press(arm, p, R, depth=None):
    """In along the panel's level normal to depth (m) past the cap's face, hold, out. Never repeated: a button that
    didn't register is the verdict, not a reason to press again."""
    n, label = R[:, 0], f"mw_press {p.id}"  # level, out of the panel toward the arm
    depth = depth or (PRESS_DEPTH_REAL if arm.stall_m else PRESS_DEPTH)
    out, bottom = p.pos + PRESS_OUT * n, p.pos - depth * n
    first = None
    for tilt in PRESS_TILTS:
        a = _radial(p.pos, tilt)
        legs = [_line("in", out, bottom, a), _line("out", bottom, out, a)]
        q0 = arm.cmd.copy()  # rolled as at home: the wrist camera on top, clear of a door left ajar
        q0[4] = arm.home_q[4]
        try:
            _check(arm, label, legs, q0)
            break
        except RuntimeError as e:
            first = first or e
    else:
        raise first
    bias = _approach(arm, label, out, a, q0)
    arm.status = f"{label}: in"
    # the bias following the sag: held as at the approach, the softer sim arm's tip rose 8 mm going 24 mm in, over the cap
    slow = lambda k: PRESS_SLOW if (legs[0][1][k] - p.pos) @ n < PRESS_SLOW_FROM else None  # noqa: E731
    _, why, peak = _go(arm, legs[0][1], legs[0][2], PRESS_SPEED, bias, None if arm.stall_m else PRESS_N + arm.noise_n, slow, follow=True)
    _hold(arm, PRESS_HOLD_S)
    affordances._unwind(arm, bias)
    arm.status = f"{label}: out"
    _go(arm, [out], [a], PRESS_SPEED * 2, bias)
    return {"verdict": "done", "reason": f"pressed {p.id} level, {depth * 1000:.0f} mm in past its face, tool {tilt} deg down"
            + (f", stopped early: {why}" if why else ""), "peak_force_n": round(peak, 2), "tilt_deg": tilt}


# --- the door ---

def door_geometry(p, R, nudge=(0.0, 0.0, 0.0)):
    """(the bar's middle with the door shut, the hinge point, its axis), arm frame. From the handle itself, or from a
    named button plus device.yaml's offsets; both moved by nudge (mm, device frame: toward the arm, right, up)."""
    if p.kind == "handle":
        bar = np.asarray(p.pos, float)
        if "hinge" in p.meta:  # the sim's CAD handle carries its hinge
            return bar, np.asarray(p.meta["hinge"], float), _unit(p.meta["hinge_axis"])
    elif _name(p) in BUTTONS:
        bar = p.pos + R @ (np.subtract(HANDLE, BUTTONS[_name(p)]) / 1000)
    else:
        raise RuntimeError(f"target the handle or a named button ({', '.join(BUTTONS)}): {p.id} is neither")
    bar = bar + R @ (np.asarray(nudge, float) / 1000)
    return bar, bar + R @ (np.subtract(HINGE, HANDLE) / 1000), _unit(R @ np.asarray(HINGE_AXIS))


def _bar(bar0, H, k, deg):
    return H + _rot(bar0 - H, k, deg)


def _angle_of(bar0, H, k, at):
    """How far round the hinge (deg, opening +) point at is from the shut bar, in the plane square to the axis."""
    u, v = bar0 - H, at - H
    u, v = u - (u @ k) * k, v - (v @ k) * k
    return math.degrees(math.atan2(float(k @ np.cross(u, v)), float(u @ v)))


def open_door(arm, p, R, angle=PULL_DEG, nudge=(0.0, 0.0, 0.0)):
    """The jaws open round the handle's bar at its middle, the bar centred between them, shut on it, drawn round the
    hinge's arc to angle (deg), opened and backed off. Says how far round the bar really went, from the arm's joint
    readings where the pull ended."""
    bar0, H, k = door_geometry(p, R, nudge)
    label = f"door_open {p.id}"
    gap = BAR_D + 2 * GRIP_SPARE
    centre_x = JAW_FACE_X + gap / 2  # the bar's middle from the fixed jaw's tip, toward the moving jaw
    ths = np.linspace(0.0, angle, max(2, math.ceil(angle / STEP_DEG) + 1))
    first = None
    for tilt in GRIP_TILTS:
        def tip(th):  # the same grip on the bar wherever it has swung to: the tool radial, the jaws closing level,
            b = _bar(bar0, H, k, th)  # the moving jaw on the side away from the hinge: opening it there to let go
            a = _radial(b, tilt)      # can't push on the leaf (manipulate's swing drove it into the leaf)
            x = np.cross([0.0, 0.0, 1.0], a)
            x = _unit(x if x @ (b - H) > 0 else -x)
            return b + GRIP_DEPTH * a - centre_x * x, a, x
        arc = [tip(th) for th in ths]
        tip0, a0, x0 = arc[0]
        q0 = _swing_roll(arm, arm.ik.solve(tip0, a0, arm.cmd)[0], a0, x0)
        legs = [_line("in", tip0 - GRIP_OUT * a0, tip0, a0), ("pull", [t for t, _, _ in arc], [a for _, a, _ in arc])]
        try:
            _check(arm, label, legs, q0)
            break
        except RuntimeError as e:
            first = first or e
    else:
        raise first
    _jaws(arm, gap)
    bias = _approach(arm, label, tip0 - GRIP_OUT * a0, a0, q0)
    arm.status = f"{label}: in round the bar"
    _, why, _ = _go(arm, legs[0][1], legs[0][2], PRESS_SPEED, bias, lag_max=IN_LAG, follow=True)
    if why:
        affordances._unwind(arm, bias)
        _go(arm, [legs[0][1][0]], [a0], PRESS_SPEED * 2, bias)
        _jaws(arm, 0)
        return {"verdict": "MISSED", "reason": f"going in round the handle's bar the jaws {why}: not on the bar"}
    arm.status = f"{label}: shut on the bar"
    _jaws(arm, 0)
    arm.status = f"{label}: pull"
    slow = lambda i: UNLATCH_SPEED if ths[i] <= UNLATCH_DEG else None  # noqa: E731
    k_end, why, peak = _go(arm, legs[1][1], legs[1][2], PULL_SPEED, bias, None, slow, along=False, lag_max=PULL_LAG)
    if why:  # held: stop pulling before anything else, or the force builds on while it waits
        affordances._unwind(arm, bias)
    _hold(arm, 0.3)  # the arm catches up with its sag before its reading is taken
    t_now, _ = arm.tip_pose()
    _, a_end, x_end = arc[max(k_end, 0)]
    reached = _angle_of(bar0, H, k, t_now - GRIP_DEPTH * a_end + centre_x * x_end)
    arm.door_deg = max(0.0, reached)  # where door_close starts from
    affordances._unwind(arm, bias)
    arm.status = f"{label}: let go"
    _jaws(arm, gap)  # only as wide as they went on: wider, the door swung 6 deg back shut as they opened (sim)
    arm.status = f"{label}: back off"
    _go(arm, [t_now - BACK_OFF * a_end], [a_end], PRESS_SPEED * 2, bias)
    _jaws(arm, 0)
    _clear(arm, bias, a_end)
    held = why is not None  # a pull that ran its whole path and came up short is the arm's own give, not the door's
    what = (f"the door opened to {reached:.0f} deg by the arm's reading, of {angle:g} asked (the manual: it opens to about "
            f"{DOOR_OPENS_DEG:g})")
    return {"verdict": "FAIL" if held else "done", "reached_deg": round(reached, 1), "asked_deg": angle,
            "peak_force_n": round(peak, 2),
            "reason": f"{what}: the pull {why or 'ended short'} at {reached:.0f} deg" if held else what}


def close_door(arm, p, R, angle=None, nudge=(0.0, 0.0, 0.0)):
    """The shut jaws' tip swept round the arc toward shut from CLOSE_FROM further open than the door is believed to rest
    (angle, deg: door_open's last reading by default), in front of the bar, so it meets the bar wherever it really is
    and pushes it to SHUT_AT; held while the latch pulls it shut, then back off."""
    bar0, H, k = door_geometry(p, R, nudge)
    label = f"door_close {p.id}"
    angle = float(angle if angle is not None else getattr(arm, "door_deg", PULL_DEG))
    if angle < 2.0:
        raise RuntimeError(f"the door is already shut ({angle:.0f} deg)")
    start = min(max(angle + CLOSE_FROM, CLOSE_START), CLOSE_MAX)
    ths = np.linspace(start, SHUT_AT, max(2, math.ceil((start - SHUT_AT) / STEP_DEG) + 1))
    first = None
    for tilt in GRIP_TILTS:
        pts, axes = [], []
        for th in ths:
            b = _bar(bar0, H, k, th)
            a = _radial(b, tilt)
            pts.append(b - (BAR_D / 2 - PUSH_IN) * a)
            axes.append(a)
        legs = [_line("in", pts[0] - GRIP_OUT * axes[0], pts[0], axes[0]), ("push", pts, axes)]
        q0 = arm.cmd.copy()
        q0[4] = arm.home_q[4]
        try:
            _check(arm, label, legs, q0)
            break
        except RuntimeError as e:
            first = first or e
    else:
        raise first
    _jaws(arm, 0)
    bias = _approach(arm, label, legs[0][1][0], axes[0], q0)
    arm.status = f"{label}: in to the bar"
    _, why, _ = _go(arm, legs[0][1], legs[0][2], PRESS_SPEED, bias, lag_max=IN_LAG, follow=True)
    if why:
        affordances._unwind(arm, bias)
        _go(arm, [legs[0][1][0]], [axes[0]], PRESS_SPEED * 2, bias)
        return {"verdict": "MISSED", "reason": f"going in to the bar's front at {start:.0f} deg it {why}: the door isn't where it was believed"}
    arm.status = f"{label}: push"
    # slow from a little before where the door is believed to be, onto the bar (a seized door went from 3 N to the
    # 15 N cap in a tick at 20 mm/s), and onto the latch
    slow = lambda i: UNLATCH_SPEED if ths[i] <= max(angle + 10.0, UNLATCH_DEG) else None  # noqa: E731
    k_end, why, peak = _go(arm, pts, axes, PULL_SPEED, bias, None if arm.stall_m else PUSH_N + arm.noise_n, slow, along=False)
    if why:  # held short (or at the stop): stop pushing first. Held there, Rev A's seized door reached the 15 N cap
        affordances._unwind(arm, bias)
    _hold(arm, 0.5)
    t_now, _ = arm.tip_pose()
    reached = _angle_of(bar0, H, k, t_now + (BAR_D / 2 - PUSH_IN) * axes[max(k_end, 0)])
    arm.door_deg = max(0.0, reached)
    affordances._unwind(arm, bias)
    arm.status = f"{label}: back off"
    _go(arm, [t_now - BACK_OFF * axes[max(k_end, 0)]], [axes[max(k_end, 0)]], PRESS_SPEED * 2, bias)
    _clear(arm, bias, axes[max(k_end, 0)])
    shut = reached < 4.0  # the door's sensor reads shut under 3 deg, and the arm's reading is a degree or two off
    return {"verdict": "done" if shut else "FAIL", "reached_deg": round(reached, 1), "peak_force_n": round(peak, 2),
            "reason": f"pushed the door from {angle:.0f} deg to {reached:.0f} deg by the arm's reading"
            + ("" if shut else f": it {why or 'stopped'} short of shut")}


def _nudge(params):
    return tuple(float(params.get(k, 0.0)) for k in ("dx_mm", "dy_mm", "dz_mm"))


SKILLS = {
    "mw_press": lambda arm, p, R, params: press(arm, p, R, float(params.get("depth_mm", 0)) / 1000),
    "door_open": lambda arm, p, R, params: open_door(arm, p, R, float(params.get("angle", PULL_DEG)), _nudge(params)),
    "door_close": lambda arm, p, R, params: close_door(arm, p, R, params.get("angle"), _nudge(params)),
}


def run(arm, skill, p, plane_T, params):
    """One skill on part p with the step's params. The device frame comes from the scanned panel's normal, or with no
    panel, from the part's own (the sim's CAD parts)."""
    if plane_T is not None:
        R = device_frame(plane_T)
    else:
        T = np.eye(4)
        T[:3, 2] = p.normal
        R = device_frame(T)
    return SKILLS[skill](arm, p, R, params)


def execute(robot, step, p):
    """A step on a PipelineRobot (the real or sim backend), as a result dict for sim_backend.map_verdict. PASS: a reading
    changed (the button's, or the door's sensor). FAIL: a press that changed nothing, or a door that held short of
    what was asked (with how far it went). OBSERVED: the door moved between open angles, which nothing reads."""
    arm = robot.arm
    if p is None:
        return {"verdict": "REFUSED", "reason": f"no part called {step.target}"}
    if not robot.at_home:
        skills.go_home(arm)
    arm.status = "between steps"  # an operator readout takes its baseline here, with nothing to ask
    before, n_ev, t0 = dict(arm.app.readings), len(arm.app.events), time.monotonic()
    try:
        done = run(arm, step.skill, p, robot.plane_T, step.params)
    except RuntimeError as e:  # out of reach, or no handle to aim at
        return {"verdict": "REFUSED", "reason": f"{p.id}: {e}"}
    robot.at_home = False
    new = [ch for _, ch, _ in arm.app.events[n_ev:]] + [ch for ch, v in arm.app.readings.items() if before.get(ch) != v]
    # only a button's own channel or the door's says the step did it: the cook time counts down by itself, and a
    # broken +30s while cooking would pass on that
    ch = next((c for c in new if c.startswith("btn_") or c == "door" or c in CHANNELS), None)
    r = {"channel": ch, "stop": "done", "duration_s": round(time.monotonic() - t0, 1), "peak_force_n": done.get("peak_force_n"),
         "readout_change": {c: [before.get(c), arm.app.readings.get(c)] for c in dict.fromkeys(new)}}
    if done["verdict"] in ("FAIL", "MISSED"):
        r.update(verdict=done["verdict"], reason=done["reason"] + (f"; {ch} changed" if ch else "; no reading changed"))
        if done["verdict"] == "FAIL" and step.skill in ("door_open", "door_close"):
            r["stop"] = "force_limit"  # map_verdict: stuck
    elif step.skill == "mw_press":
        r.update(verdict="PASS" if ch else "FAIL", reason=f"{done['reason']}; " + (f"{ch} changed" if ch else "no reading changed"))
    else:
        r.update(verdict="PASS" if ch else "OBSERVED", reason=f"{done['reason']}; " + (f"{ch} changed" if ch else "no reading changed"))
    return r


# the microwave's rules plan, as the manual runs it: set a time and power, start, open the door mid-cook (it pauses),
# shut it, resume, add 30 s, pause, clear
DEMO = [("mw_press", "TIME", {}), ("mw_press", "POWER", {}), ("mw_press", "START", {}), ("door_open", "DOOR", {"angle": PULL_DEG}),
        ("door_close", "DOOR", {}), ("mw_press", "START", {}), ("mw_press", "+30S", {}), ("mw_press", "STOP", {}),
        ("mw_press", "STOP", {})]


def demo(parts, plane_T):
    """DEMO on these parts, as [(skill, part id, params)], and what it had to leave out. A button is found by the name
    System 2 gave it, else, with all five found, by place: the column nearer the door is TIME, POWER, STOP from the
    top, the other +30s, START. The door's steps target the handle, else TIME if it is named."""
    buttons = [p for p in parts if p.kind == "button"]
    ids = {_name(p): p.id for p in buttons if _name(p) in BUTTONS}
    if len(buttons) == 5:
        T = plane_T if plane_T is not None else np.c_[np.zeros((4, 2)), np.r_[np.mean([p.normal for p in buttons], 0), 0], np.zeros(4)]
        y = device_frame(T)[:, 1]
        near, far = sorted(buttons, key=lambda p: p.pos @ y)[:3], sorted(buttons, key=lambda p: p.pos @ y)[3:]
        guess = zip(("TIME", "POWER", "STOP", "+30S", "START"), [*sorted(near, key=lambda p: -p.pos[2]), *sorted(far, key=lambda p: -p.pos[2])])
        ids = {**{name: p.id for name, p in guess}, **ids}
    door = next((p.id for p in parts if p.kind == "handle"), None) or next((p.id for p in buttons if _name(p) == "TIME"), None)
    ids["DOOR"] = door
    steps = [(skill, ids[t], params) for skill, t, params in DEMO if ids.get(t)]
    return steps, sorted({t for _, t, _ in DEMO if not ids.get(t)})


def scan_settings():
    """The real scan's settings for the microwave's upright panel, over hw_rig's for the sloped centrifuge: a survey
    whose panel faces the arm upright passes the check, and the buttons stand in two columns, not one row. Untested
    on the real arm."""
    import rgbperceive

    if rgbperceive.SURVEY_CHECK:
        _, pts, side = rgbperceive.SURVEY_CHECK
        rgbperceive.SURVEY_CHECK = ((-0.1, 0.3), pts, side)  # perceive.VERTICAL_NZ up to PANEL_NZ's floor: upright
    rgbperceive.ROW_MAX = None
