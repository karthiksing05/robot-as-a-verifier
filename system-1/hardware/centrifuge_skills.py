"""First versions of the MC-6 centrifuge's skills past its panel, for the real arm: the lid and the rack's cover hooked
open by their lips and drawn shut again, and a tube picked from the rack by its collar and lowered into well A.

Not from CAD: each skill takes one point and runs a few straight lines and arcs from it. The point is a scanned or
model-added part (a handle is the lip itself), or STOP plus one of the offsets below (a button target is taken as STOP).
Offsets are in the device's frame (x toward the arm, y right as seen from the arm, z up), worked out from
appliances/centrifuge/device.yaml, so they are guesses for the real box until tuned on it. Every pose of a skill is
checked for reach before anything moves (RuntimeError: RealBackend reports it as REFUSED). Speeds are slow and the arm's
own hard cap stays on. Geometry follows core/manipulate.py's hook and over-centre moves, made simple."""
import math

import numpy as np

import affordances
import real_skills
from manipulate import _roll_up
from rig import CONTROL_HZ
from safety import SafetyStop

# from STOP's cap top (device.yaml's button_2 at (46.04, 0, 80.04)), mm, in the device's frame
LID_LIP = (-20.0, 0.0, 27.0)       # handle_1, the lid's lip
RACK_LIP = (56.9, 144.0, 1.2)      # handle_2, the rack cover's lip
TUBE = (38.5, 175.0, -19.0)        # tube_1's collar top, in rack position 2
WELL_A = (-67.0, -13.0, -14.7)     # where that collar top sits once the tube is seated in well A
# each cover's hinge from its lip (mm) and its axis (opening is + about it), and where it rests open (deg)
COVERS = {"lid": dict(lip=LID_LIP, hinge=(-82.5, 0.0, -5.0), axis=(0.0, -1.0, 0.0), rest=105.0),
          "rack": dict(lip=RACK_LIP, hinge=(-42.5, 35.7, 5.0), axis=(-0.64, -0.77, 0.0), rest=105.0)}

# opening: the fixed jaw's tip goes in under the lip, its inner face turned up, and swings about the hinge
HOOK_PAST, HOOK_BELOW = 0.003, 0.007  # the jaw's tip this far in past the lip's point and below it (manipulate's)
HOOK_OUT = 0.03                       # starting this far out in front of that
HOOK_TILT = math.radians(10)          # the tool this far below level, levelling off as the cover rises
HOOK_OPEN = 0.2                       # the moving jaw opened out of the way (about 20 mm)
OPEN_DEG = 100.0                      # default swing: past vertical, so it falls onto its stop
AWAY = 0.03                           # and then off the cover this far
# closing: from in front, over the cover's top edge, down behind it, and drawn back past vertical; it falls shut
OVER_TILT = math.radians(20)  # manipulate's 45 put the tool over the real lid's edge out of reach at any box distance
OVER_FRONT, OVER_BEHIND, OVER_CLEAR, OVER_DOWN = 0.05, 0.012, 0.025, 0.006
CLOSE_TO = 78.0                       # deg: drawn back to here, past vertical (manipulate.OVER_TO), then let go
FALL_S = 3.0
# the tube: jaws open around its 18 mm collar, down straight, shut, lift clear of the rack
TUBE_GRIP_DOWN = 0.003                # the grip centre below the collar top: the middle of its 6 mm
TUBE_OPEN = 0.2                       # 0.3 opened far wider than the red collar on the real arm (Nov 8)
TUBE_SQUEEZE = -0.25                  # shut drives this far past closed, so the servo keeps squeezing through the lift
TUBE_CENTRE = 0.015                   # the collar's centre this far from the fixed jaw: half the real gap, not the model's
TUBE_HELD_X = 0.012                   # held, the tube's axis this far from the fixed jaw's tip (3 mm to its face + 9)
# the tool this far below level (deg), steepest first that reaches (manipulate.GRIP_TILTS): straight down only
# reaches about 290 mm out. It tilts in the upright plane through the pan axis, the jaws closing level across it
TUBE_TILTS = (90, 75, 60, 50)
PAN_XY = np.array([0.0388, 0.0])      # the pan axis, arm frame (manipulate.PAN_XY)
ABOVE = 0.05                          # a pick starts this far over its grip
LIFT = 0.07                           # and lifts this far: the tube is 55 mm long
PLACE_ABOVE = 0.06                    # a place starts this far over the seat, and lowers until the arm stalls
SPEED, ARC_SPEED, GUARD_SPEED = 0.03, 0.02, 0.015  # m/s
GUARD_N = 5.0                         # with no stall sensing (the sim bus), a guarded move stops at this
STEP_M, STEP_DEG = 0.005, 3.0         # poses checked for reach every this far
AXIS_TOL = 15.0                       # deg: the IK may point the tool this far off what a pose asks


def device_frame(plane_T):
    """Columns x (toward the arm, level), y (right as seen from the arm), z (up), from the scanned panel's normal."""
    n = plane_T[:3, 2]
    x = np.array([n[0], n[1], 0.0])
    x /= np.linalg.norm(x)
    if x[0] > 0:  # the arm is at the origin, the device out along +x
        x = -x
    z = np.array([0.0, 0.0, 1.0])
    return np.c_[x, np.cross(z, x), z]


def anchor(p, offset_mm, R, nudge_mm=(0.0, 0.0, 0.0)):
    """Where a skill aims: a handle or well itself, or else STOP (the scan has read it as a button or a knob) plus
    offset_mm; then nudged by the step's dx/dy/dz_mm."""
    base = p.pos + (0.0 if p.kind in ("handle", "well") else R @ np.asarray(offset_mm) / 1000)
    return base + R @ np.asarray(nudge_mm, float) / 1000


def _line(name, a, b, axis, speed=SPEED, guard=None):
    """A leg along a straight line, its poses STEP_M apart."""
    n = max(1, math.ceil(np.linalg.norm(b - a) / STEP_M))
    return name, [a + (b - a) * i / n for i in range(n + 1)], [axis] * (n + 1), speed, guard


def _check(arm, label, legs, q):
    """Every pose of every leg in reach, tool within AXIS_TOL of its axis, or RuntimeError naming the first that isn't."""
    for leg in legs:
        if len(leg) == 2:
            continue
        name, pts, axes = leg[:3]
        for p, a in zip(pts, axes):
            try:
                arm.check_workspace(p)
            except SafetyStop as e:
                raise RuntimeError(f"{name}: {e}") from None
            q, ok, err, ang = arm.ik.solve(p, a, q)
            if not ok or ang > AXIS_TOL:
                raise RuntimeError(f"{name} is out of reach at {np.round(p * 1000).astype(int).tolist()} mm "
                                   f"(best IK {err * 1000:.0f} mm, {ang:.0f} deg off)")


def _follow(arm, pts, axes, speed, bias, guarded):
    """The tip through pts at speed, the bias held. Guarded, it stops where the arm stalls against something (the
    real arm, affordances._stall) or the force estimate passes GUARD_N (the sim bus), and returns how far along it got."""
    q = arm.cmd - bias
    stall = affordances._stall(arm) if guarded and arm.stall_m else None
    if guarded:
        arm.tare()
    a, done = arm.ik.fk(q)[0], 0.0
    for b, ax in zip(pts, axes):
        d = np.linalg.norm(b - a)
        if d < 1e-6:
            continue
        m, n = (b - a) / d, max(1, math.ceil(d / speed * CONTROL_HZ))
        for i in range(1, n + 1):
            to = a + (b - a) * i / n
            q = affordances._toward(arm, arm.ik.solve(to, ax, q, iters=30)[0], bias)
            arm.send(q + bias)
            arm.tick()
            if guarded:
                lag = (to - arm.tip_pose()[0]) @ m
                if stall(lag)[0] if stall else arm.tip_force() > GUARD_N:
                    return done + d * i / n - lag
        a, done = b, done + d
    return None


def _hold(arm, s):
    for _ in range(int(s * CONTROL_HZ)):
        arm.send(arm.cmd)
        arm.tick()


def _run(arm, label, legs, q0):
    """Check the legs for reach, then run them. A leg is (name, points, axes, speed, guard), guard None, "stop" (contact
    there means the skill went wrong: it backs out to the leg's start and returns why) or "until" (contact ends the leg
    and the skill goes on), or (name, gripper opening). Returns (why it stopped or None, {leg: m along at contact})."""
    _check(arm, label, legs, q0)
    first = next(leg for leg in legs if len(leg) == 5)
    _, bias = affordances._approach(arm, first[1][0], first[2][0], label, q0)
    met = {}
    for leg in legs:
        arm.status = f"{label}: {leg[0]}"
        if len(leg) == 2:
            real_skills.gripper(arm, leg[1])
            continue
        name, pts, axes, speed, guard = leg
        at = _follow(arm, pts, axes, speed if guard is None else max(GUARD_SPEED, arm.guard_speed), bias, guard)
        if at is None:
            continue
        met[name] = at
        affordances._unwind(arm, bias)  # the command back to the arm, so it stops pushing
        if guard == "stop":
            arm.status = f"{label}: back out"
            _follow(arm, [pts[0]], [axes[0]], SPEED, bias, False)
            return f"{name} met something {at * 1000:.0f} mm along, short of its {np.linalg.norm(pts[-1] - pts[0]) * 1000:.0f}", met
    return None, met


def _rot(v, k, deg):
    return affordances._rotate(v, k, math.radians(deg))


def _cover(cover, lip, R):
    """The cover's hinge point, axis and level way in under its lip, in the arm's frame."""
    c = COVERS[cover]
    hinge = lip + R @ np.asarray(c["hinge"]) / 1000
    k = R @ np.asarray(c["axis"])
    flat = hinge - lip
    flat[2] = 0.0
    return hinge, k / np.linalg.norm(k), flat / np.linalg.norm(flat)


def open_cover(arm, cover, lip, R, angle=OPEN_DEG):
    """Hook a cover (COVERS: "lid" or "rack") open by its lip at lip: the fixed jaw's tip in under it, swung up about
    the hinge to angle (deg), then off it. Past vertical it falls onto its stop."""
    hinge, k, flat = _cover(cover, lip, R)
    up, label = np.array([0.0, 0.0, 1.0]), f"open {cover}"

    def tool(th):  # levelling off as it rises, then tipping up, as manipulate._hook_poses
        tilt = max(-math.radians(30), HOOK_TILT * (1 - th / 90.0))
        return math.cos(tilt) * flat - math.sin(tilt) * up

    hook = lip + HOOK_PAST * flat - HOOK_BELOW * up
    ths = np.linspace(0.0, angle, max(2, math.ceil(angle / STEP_DEG) + 1))
    swing = [hinge + _rot(hook - hinge, k, th) for th in ths]
    away = -_rot(flat, k, angle) if angle < 45 else -_rot(up, k, angle)
    q0 = arm.cmd.copy()
    q0 = _roll_up(arm, arm.ik.solve(hook, tool(0), q0)[0], tool(0))  # the fixed jaw's inner face up under the lip
    legs = [("open the jaws", HOOK_OPEN),
            _line("in", hook - HOOK_OUT * flat, hook, tool(0), guard="stop"),
            ("swing", swing, [tool(th) for th in ths], ARC_SPEED, None),
            _line("away", swing[-1], swing[-1] + AWAY * away, tool(angle)),
            ("shut the jaws", 0.0)]
    why, _ = _run(arm, label, legs, q0)
    return {"verdict": "FAIL" if why else "done", "reason": why or f"swung {angle:g} deg"}


def close_cover(arm, cover, lip, R):
    """Draw a cover shut from where it rests open: the tool tilted down over its top edge from in front, down behind
    it, back about the hinge to CLOSE_TO, then up. Its weight closes it from there."""
    hinge, k, flat = _cover(cover, lip, R)
    up, label, rest = np.array([0.0, 0.0, 1.0]), f"close {cover}", COVERS[cover]["rest"]
    a = math.cos(OVER_TILT) * flat - math.sin(OVER_TILT) * up
    edge = hinge + _rot(lip - hinge, k, rest)
    over, behind = edge + OVER_BEHIND * flat + OVER_CLEAR * up, edge + OVER_BEHIND * flat - OVER_DOWN * up
    # a straight line, as manipulate's: it cuts inside the edge's arc, so it bears on the edge (an arc kept its gap)
    drop = hinge + _rot(lip - hinge, k, CLOSE_TO) + OVER_BEHIND * flat - OVER_DOWN * up
    legs = [_line("over", edge - OVER_FRONT * flat + OVER_CLEAR * up, over, a),
            _line("down", over, behind, a, guard="stop"),
            _line("draw", behind, drop, a, ARC_SPEED),
            _line("up", drop, drop + OVER_CLEAR * up, a)]
    why, _ = _run(arm, label, legs, arm.cmd.copy())
    if not why:
        arm.status = f"{label}: let it fall"
        _hold(arm, FALL_S)
    return {"verdict": "FAIL" if why else "done", "reason": why or f"drawn back to {CLOSE_TO:g} deg and let go"}


def _roll_level(arm, q, side):
    """q with the wrist rolled so the jaws close along side (either way), by the smallest turn."""
    x, lo, hi = arm.ik.fk_R(q)[:, 0], *arm.m.jnt_range[arm.m.joint("wrist_roll").id]
    best = None
    for w in (side, -side):
        th = math.atan2(np.linalg.norm(np.cross(x, w)), x @ w)
        for s in (1, -1):
            qt = q.copy()
            qt[4] = np.clip(q[4] + s * th, lo, hi)
            score = arm.ik.fk_R(qt)[:, 0] @ w - 0.01 * abs(qt[4] - q[4])
            if best is None or score > best[0]:
                best = (score, qt)
    return best[1]


def _jaws_at(arm, centre, offset, tilt):
    """The tool tilt (deg) below level, in the upright plane through the pan axis, the jaws closing level across that
    plane, and the tip placed so centre is offset from it toward the moving jaw. Returns the tip, tool axis and q."""
    r = np.r_[centre[:2] - PAN_XY, 0.0]
    r /= np.linalg.norm(r)
    t, up = math.radians(tilt), np.array([0.0, 0.0, 1.0])
    a, q, tip = math.cos(t) * r - math.sin(t) * up, arm.cmd.copy(), centre
    for _ in range(3):
        q = _roll_level(arm, arm.ik.solve(tip, a, q)[0], np.cross(up, r))
        tip = centre - offset * arm.ik.fk_R(q)[:, 0]
    return tip, a, q


def _tube_legs(arm, label, build):
    """build(tilt) -> (legs, q) at the steepest of TUBE_TILTS whose poses are all in reach, else the steepest's refusal."""
    first = None
    for tilt in TUBE_TILTS:
        legs, q = build(tilt)
        try:
            _check(arm, label, legs, q)
            return legs, q
        except RuntimeError as e:
            first = first or e
    raise first


def pick_tube(arm, collar_top):
    """Jaws open over the tube, down around its collar, shut, lift LIFT. Leaves it held."""
    up, label = np.array([0.0, 0.0, 1.0]), "pick tube"

    def build(tilt):
        tip, a, q = _jaws_at(arm, collar_top - TUBE_GRIP_DOWN * up, TUBE_CENTRE, tilt)
        return [("open the jaws", TUBE_OPEN),
                _line("down", tip + ABOVE * up, tip, a),  # unguarded: the stall check stopped it in mid-air (Nov 8)
                ("shut", TUBE_SQUEEZE),
                _line("lift", tip, tip + LIFT * up, a)], q
    why, _ = _run(arm, label, *_tube_legs(arm, label, build))
    return {"verdict": "FAIL" if why else "done", "reason": why or f"shut on the collar and lifted {LIFT * 1000:.0f} mm"}


def place_tube(arm, seat):
    """With the tube held, over the well's seat (seat: where its collar top sits once seated), lowered until the arm
    stalls or the collar reaches the seat (never forced), jaws opened, lifted out."""
    up, label = np.array([0.0, 0.0, 1.0]), "place tube"

    def build(tilt):
        tip, a, q = _jaws_at(arm, seat - TUBE_GRIP_DOWN * up, TUBE_HELD_X, tilt)
        return [_line("lower", tip + PLACE_ABOVE * up, tip, a, guard="until"),
                ("let go", TUBE_OPEN),
                _line("up", tip, tip + ABOVE * up, a),
                ("shut the jaws", 0.0)], q
    _, met = _run(arm, label, *_tube_legs(arm, label, build))
    short = PLACE_ABOVE - met["lower"] if "lower" in met else 0.0
    return {"verdict": "done", "reason": f"let go {short * 1000:.1f} mm above the seat" if short > 0.001
            else "let go at the seat", "short_mm": round(short * 1000, 1)}


SKILLS = {  # skill: (offset from STOP, what runs it)
    "lid_open": (LID_LIP, lambda arm, at, R, angle: open_cover(arm, "lid", at, R, angle)),
    "lid_close": (LID_LIP, lambda arm, at, R, angle: close_cover(arm, "lid", at, R)),
    "rack_open": (RACK_LIP, lambda arm, at, R, angle: open_cover(arm, "rack", at, R, angle)),
    "rack_close": (RACK_LIP, lambda arm, at, R, angle: close_cover(arm, "rack", at, R)),
    "tube_find": (TUBE, None),  # the camera's, in run
    "tube_pick": (TUBE, lambda arm, at, R, angle: pick_tube(arm, at)),  # STOP + TUBE only with no camera
    "tube_place": (WELL_A, lambda arm, at, R, angle: place_tube(arm, at)),
}


def run(arm, skill, p, plane_T, params, wrist=None):
    """One skill on part p (STOP, or the thing itself), with the step's params: angle, dx_mm, dy_mm, dz_mm, and for
    tube_find and tube_pick which tube (1 the green collar, 2 the red). Those two find the tube with the wrist camera
    (tube_find.find): tube_find only reports where, tube_pick then picks it there."""
    nudge = [float(params.get(k, 0.0)) for k in ("dx_mm", "dy_mm", "dz_mm")]
    if skill in ("tube_find", "tube_pick") and wrist is not None:
        import tube_find
        top, how = tube_find.find(arm, wrist, "red" if float(params.get("tube", 1)) >= 2 else "green")
        if top is None:
            raise RuntimeError(how)
        top = top + (device_frame(plane_T) if plane_T is not None else np.eye(3)) @ np.asarray(nudge) / 1000
        if skill == "tube_find":
            return {"verdict": "done", "reason": how}
        done = pick_tube(arm, top)
        return {**done, "reason": f"{how}; {done['reason']}"}
    if skill == "tube_find":
        raise RuntimeError("no wrist camera to look with")
    if plane_T is None:
        raise RuntimeError("no scanned panel to aim from: run explore first")
    offset, fn = SKILLS[skill]
    R = device_frame(plane_T)
    at = anchor(p, offset, R, nudge)
    return fn(arm, at, R, float(params.get("angle", OPEN_DEG)))
