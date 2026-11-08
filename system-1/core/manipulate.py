"""Skills that move more than a part's own mechanism: hooking a lid open or shut, and picking and placing an object
(pushing the whole device is inventory.push). They take features.Part records like the skills in affordances.py and return the same
result dicts, and they run on any rig, with no CAD and no knowledge of any one device.

    r = hook_pull(arm, parts, i, step)      # params: angle, the handle's angle from shut; force_limit
    r = pick(arm, parts, i, step)           # jaws on the object's flats
    r = place(arm, parts, i, step)          # target: the well; what the jaws hold goes in it

Verdicts come from the readout, as in affordances.py. Where a device has no reading for what a step did (a rack cover has
no sensor), the verdict is OBSERVED with what the arm measured, not PASS.
"""
import math
import os
from dataclasses import replace

import numpy as np

import skills
from rig import CONTROL_HZ, HARD_FORCE_CAP_N, SafetyStop, tip_shape

HOOK_TILT = math.radians(60)    # the probe comes in this far below level, so its 12 mm pad fits under a lip
# the tool's start tilt, the handle angle it's level by, and the most it tips up after: in degrees, steepest first
HOOK_TILTS = ((60, 90, -30), (50, 90, -30), (40, 90, -30), (60, 90, 0), (50, 90, 0), (40, 90, 0), (40, 75, 0))
# the stock gripper's fixed jaw is 6 mm thick at its tip and its inner face runs straight back along the tool: tilted 60
# deg, that face stood 19 mm above its tip where it passed the lip's end, so it met the lip's end instead of going under.
# Within 10-15 deg of level it goes 7 mm in under the lip 2.5 mm below it and clears its end; nearer level, the test lids'
# lips were out of the arm's reach. Below the lips the test lids leave 12-22 mm
HOOK_TILTS_JAW = ((10, 90, -30), (5, 90, -30), (15, 90, -30), (0, 90, -30), (10, 90, 0), (5, 90, 0), (15, 90, 0))
HOOK_IN = 0.03                  # start this far out from under the lip
HOOK_SPEED = 0.03               # m/s along the arc, and in and out
# come to the entry in a straight line from this far back along the tool and up, the first the arm reaches: a joint move
# from home straight to the entry, low and nearly level, swung the gripper out over the handle and down onto the lid beside
# it (kettle-base: 14-18 N, 4 seeds in 5). Near the base, level, the arm can't draw back along the tool: then from above
HOOK_STAGES = ((0.04, 0.03), (0.02, 0.03), (0.0, 0.03), (0.0, 0.02))
# every move of a hook reaches its speed over this long from rest: starting at full speed, the servos' lag read as 7-9 N
# for its first quarter second with nothing touching (label-printer, centrifuge: the run in stopped short at 9 N, D32);
# ramped over 1 s, 6 N
HOOK_RAMP_S = 1.0
# the last of the run in under a lip goes slowly, and meeting something there (the riser behind the lip, nearer than the
# plan by the arm's calibration error) ends the run in where it is: the swing is planned from there. At full speed the tip
# struck the kettle's riser at 9-10 N and the estimate overshot the hard cap
HOOK_FEEL = 0.008               # m: the slow part
HOOK_FEEL_SPEED = 0.008         # m/s
HOOK_FEEL_N = 1.5               # over the estimate's noise, from a zero taken just before
HOOK_SETTLE_S = 0.3             # then this long for the estimate to settle
HOOK_LIFTS = (0.0, 0.003, 0.006)  # m: having met the face below a lip, go in again this much higher, in turn
HOOK_RISER_MAX = 0.008          # met further out than this short of the plan, it isn't the riser (the lips run 7-9 mm in)
# swinging, the jaw gives way along the handle, out from the hinge, when the handle pushes it out: the arm's calibration
# error puts the hinge a few mm off where it believes, so the arc ran into the handle (label-printer: 5 N true, 9 read)
HOOK_GIVE = 1e-4                # m per N over the noise per tick
HOOK_GIVE_MAX = 0.005           # and no further than this in all: 10 mm let the incubator door, left on the jaw, swing onto the wrist camera
HOOK_GIVE_N = 1.0               # over this, from the estimate's zero at the swing's start
HOOK_BACK = 0.001               # and the swing starts this far back off what it met
SETTLE_S = 1.0                  # after letting go, time for a lid to come to rest
FALL_S = 6.0                    # after drawing one back past vertical, time for it to fall shut
FORCE_LIMIT = {"hook_pull": 6.0}
PAD_OFFSET = (0.0025, 0.007)    # out from the lip's contact point and down from it, when a Part's meta doesn't say
PAD_R = 0.006                   # the fingertip pad's radius
HOOK_FACE_CLEAR = 0.004        # stock: the fixed jaw's inner face goes in this far under the lip's underside; 2.5 mm left the tip, lifted ~3 mm by slop low down, striking the lip
FIXED_JAW_OUT_X = -0.0029       # stock: the fixed jaw's outer face at its tip, along the tip frame's x
HOOK_JAW_OUT = -0.003           # stock: the jaw's tip goes this far in past the handle's contact point. On the test lids the
                                # lip runs 4-5 mm out past it and 7-9 mm in, to its riser: 3 mm in puts 7 mm of jaw under it
HOOK_JAW_IN = 0.016            # stock: the shorter run in, when the arm can't reach HOOK_IN out from the lip
HOOK_JAW_SLIDE = 0.012         # stock: coming away, first slide the jaws this far back along the lip, off its end
HOOK_JAW_OPEN = 0.0             # stock: the gripper opened to this (rad) to hook, the moving jaw's tip 16 mm off the fixed one
OVER_TILT = math.radians(45)    # reaching over a handle past vertical: the tool this far below level
OVER_BEHIND = 0.012             # pad centre this far behind the handle's top edge
OVER_CLEAR = 0.04               # going over that edge, this far above it: tilted 45 deg, the jaws hang 27 mm below the tip
OVER_DOWN = 0.006               # then down to this far below it
OVER_TO = math.radians(78)      # draw it back to here, past vertical, and let it fall


def _rotate(v, k, th):
    k = k / np.linalg.norm(k)
    return v * math.cos(th) + np.cross(k, v) * math.sin(th) + k * (k @ v) * (1 - math.cos(th))


def _changes(app, before, n_events):
    seq = {}
    for _, ch, v in app.events[n_events:]:
        seq.setdefault(ch, [before.get(ch)]).append(v)
    return seq


BRANCH_RAD = math.radians(20)  # an IK step bigger than this in one tick jumped to another branch


def _ramp(length, speed, t0, ramp_s):
    """Fractions along a segment `length` long, one per tick, at speed, starting t0 s into a move that reaches full
    speed over its first ramp_s. Returns them and the time at the end."""
    fs, d, t = [], 0.0, t0
    while d < length - 1e-9:
        t += 1 / CONTROL_HZ
        d = min(length, d + speed * min(1.0, t / ramp_s if ramp_s else 1.0) / CONTROL_HZ)
        fs.append(d / length)
    return fs or [1.0], t


def _follow(arm, poses, speed, bias, limit, what, follow=False, ramp_s=0.0, give=None, give_zero=None):
    """Move through (tip, axis) poses at speed, watching the force. Returns (peak force, whether it got to the end, why
    not): a soft limit here just records the force, since a part may simply be heavy; the arm's own hard cap still stops
    it. A path whose IK jumps to another branch (a joint more than BRANCH_RAD in one tick) ends there: sent anyway, the
    incubator's closing hook_pull swung the elbow 124 deg at full speed, and the servo estimate read that as 28 N.
    ramp_s: reach full speed over this long from rest (see HOOK_RAMP_S). give: a unit vector per pose; the rest of the
    path shifts back against it by however much the force pushes that way over the noise (see HOOK_GIVE), the force
    taken from give_zero, the estimate where the move began (its drift there, D32: a give from the bare estimate let a
    lid's lip slip off the jaw)."""
    q, peak, t, off = arm.cmd - bias, 0.0, 0.0, np.zeros(3)
    for j, ((p0, a0), (p1, a1)) in enumerate(zip(poses[:-1], poses[1:])):
        fs, t = _ramp(float(np.linalg.norm(p1 - p0)), speed, t, ramp_s)
        for f in fs:
            a = a0 + (a1 - a0) * f
            if give is not None:
                g = give[j] + (give[j + 1] - give[j]) * f
                g /= np.linalg.norm(g)
                F = arm.tip_force_vec() - (0.0 if give_zero is None else give_zero)
                push = max(-float(F @ g) - (HOOK_GIVE_N if give_zero is not None else arm.noise_n), 0.0)  # pushed back against g
                off -= HOOK_GIVE * push * g
                if np.linalg.norm(off) > HOOK_GIVE_MAX:
                    off *= HOOK_GIVE_MAX / np.linalg.norm(off)
            q1 = arm.ik.solve(p0 + (p1 - p0) * f + off, a / np.linalg.norm(a), q, iters=30)[0]
            if np.max(np.abs(q1 - q)) > BRANCH_RAD:
                return peak, False, f"the {what} path left the arm's reach on this IK branch"
            q = q1
            arm.send(q + bias)
            arm.tick()
            if follow:  # the sag changes along the way: low and near level, a fixed bias let the tip rise 8 mm in 30
                bias += SAG_FOLLOW * (q - arm.read_q())
            peak = max(peak, float(np.linalg.norm(arm.tip_force_vec())))
            if peak > limit:
                return peak, False, f"met {peak:.1f} N"
    return peak, True, None


def _hook_poses(arm, p, angle_from, angle_to, tilt0=HOOK_TILT, level_at=math.pi / 2, lowest=-math.pi / 6):
    """Pad poses for swinging a handle about its hinge with the pad underneath it. The tool levels off as the handle rises,
    turning about the rim of the pad so the rim stays under the lip, until the pad's face is flat against the underside.
    With the stock gripper the hook is the fixed jaw alone (_hook_jaw): its tip is the point that stays under the lip."""
    hinge, axis = p.meta["hinge"], p.meta["hinge_axis"]
    now = p.meta.get("angle", 0.0)
    # meta holds the part's directions where it is now: take them back to shut
    under0, pull0 = _rotate(p.meta["under"], axis, -now), _rotate(p.meta["pull"], axis, -now)
    point0 = hinge + _rotate(p.pos - hinge, axis, -now)
    jaw = _hook_jaw(arm)
    out, down = p.meta.get("pad_offset", PAD_OFFSET)
    if jaw:
        # the jaw's inner face just under the lip, so the swing lifts it at once, and its tip in past the contact point
        down, out = JAW_FACE_X + HOOK_FACE_CLEAR, HOOK_JAW_OUT
    pad_r = 0.0 if jaw else PAD_R
    up = np.array([0, 0, 1.0])
    flat = under0 - (under0 @ up) * up
    flat /= np.linalg.norm(flat)
    rim0 = point0 - out * under0 - down * pull0 + pad_r * (math.sin(HOOK_TILT) * flat + math.cos(HOOK_TILT) * up)

    def pose(th):
        # past level_at the tool carries on tipping up, as far as lowest
        tilt = max(lowest, tilt0 * (1 - th / level_at))
        rim = hinge + _rotate(rim0 - hinge, axis, th)
        return rim - pad_r * (math.sin(tilt) * flat + math.cos(tilt) * up), np.array([*(math.cos(tilt) * flat[:2]), -math.sin(tilt)])

    n = max(2, int(abs(angle_to - angle_from) / math.radians(4)) + 1)

    def away(th):
        """Which way the pad leaves the lip from: back out from under it, or once it's swung well up, straight off its back."""
        return _rotate(under0 if th < math.radians(45) else pull0, axis, th)

    return [pose(angle_from + (angle_to - angle_from) * i / (n - 1)) for i in range(n)], away


def _hook_jaw(arm):
    """True for the stock gripper: it hooks with the fixed jaw alone, the moving jaw opened up out of the way and the
    fixed jaw's flat inner face turned up under the lip. Shut, the two fingertips make a wedge 7 mm thick at the tip and
    12.6 mm 10 mm back, which doesn't fit under a 10 mm lip: going in, it met the lip's end at 6-7 N on every lid."""
    return not tip_shape(arm).round and hasattr(arm, "grip")


def _roll_up(arm, q, axis):
    """q with the wrist rolled so the tip frame's x (the fixed jaw's inner face normal, toward the moving jaw) points as
    nearly up as the tool's axis allows."""
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    want = np.array([0, 0, 1.0]) - a[2] * a
    want /= np.linalg.norm(want)
    best = None
    for _ in range(3):
        x = arm.ik.fk_R(q)[:, 0]
        turn = math.atan2(np.cross(x, want) @ -a, x @ want)
        for sgn in (1, -1):
            qt = q.copy()
            qt[4] = q[4] + sgn * turn
            score = arm.ik.fk_R(qt)[:, 0] @ want
            if best is None or score > best[0]:
                best = (score, qt)
        q = best[1]
    lo, hi = arm.m.jnt_range[arm.m.joint("wrist_roll").id]
    q = q.copy()
    q[4] = float(np.clip(q[4], lo, hi))
    return q


def _over_centre_poses(arm, p, rest, tilt=OVER_TILT):
    """A handle resting past vertical can't be lifted from under: reach over its top edge and draw it back past vertical,
    where its weight takes over. Returns the (tip, axis) poses and the angle it should fall from."""
    hinge, axis = p.meta["hinge"], p.meta["hinge_axis"]
    now = p.meta.get("angle", 0.0)
    pull0 = _rotate(p.meta["pull"], axis, -now)
    under0 = _rotate(p.meta["under"], axis, -now)
    point0 = hinge + _rotate(p.pos - hinge, axis, -now)
    lip = hinge + _rotate(point0 - hinge, axis, rest)
    flat = under0 - (under0 @ np.array([0, 0, 1.0])) * np.array([0, 0, 1.0])
    flat /= np.linalg.norm(flat)
    up = np.array([0, 0, 1.0])
    a = math.cos(tilt) * flat - math.sin(tilt) * up       # pointing down over the edge, so the wrist stays above the arc
    drop = hinge + _rotate(point0 - hinge, axis, OVER_TO)
    return [(lip - 0.05 * flat + OVER_CLEAR * up, a), (lip + OVER_BEHIND * flat + OVER_CLEAR * up, a),
            (lip + OVER_BEHIND * flat - OVER_DOWN * up, a), (drop + OVER_BEHIND * flat - OVER_DOWN * up, a)]


def _hook_check(arm, p, to):
    if p.grip == "pinch":
        return f"{p.id} needs a pinch grip; the no-thumbs rule allows only the fingertip pad"
    if not 0 <= to <= p.meta["open_deg"]:
        return f"angle must be between 0 and {p.meta['open_deg']:g} deg"
    return None


def hook_pull(arm, parts, i, step):
    """Slide the pad under the handle's lip, swing it about its hinge to params.angle, slide out, and let go. PASS: the
    device's reading changed. With no reading to go by, OBSERVED: the arm's path is all it knows."""
    p, params = parts[i], step.get("params", {})
    result = {"skill": "hook_pull", "target": p.id, "verdict": "REFUSED", "channel": None, "readout_change": {}}
    to_deg = params.get("angle", p.meta["open_deg"] - 5.0)
    why = _hook_check(arm, p, to_deg)
    if why:
        result["reason"] = why
        return result
    limit = params.get("force_limit", FORCE_LIMIT["hook_pull"])
    now, to = p.meta.get("angle", 0.0), math.radians(to_deg)
    if abs(to - now) < math.radians(2):
        result["reason"] = f"{p.id} is already at {to_deg:g} deg"
        return result
    level = _rotate(p.meta["under"], p.meta["hinge_axis"], -now) * np.array([1.0, 1.0, 0.0])    # its direction when shut
    level = level / np.linalg.norm(level)
    falls = now > math.pi / 2 and to < now     # resting past vertical, so it has to be drawn back over and then falls
    # the stock gripper hooks a lip with its fixed jaw, nearly level; reaching over a lid's top edge, its shut fingertip
    # serves as the probe's does, from the probe's steeper tilts
    jaw = _hook_jaw(arm) and not falls

    def path(tilt, level_at, lowest, run_in=HOOK_IN):
        if falls:
            first, *rest = _over_centre_poses(arm, p, now, tilt)
            return first, rest, [(rest[-1][0] + 0.02 * np.array([0, 0, 1.0]), rest[-1][1])]
        poses, away = _hook_poses(arm, p, now, to, tilt, level_at, lowest)
        # the entry's direction is the handle's shut one, whatever its angle now
        entry = (poses[0][0] - run_in * _rotate(p.meta["under"], p.meta["hinge_axis"], 0.0), poses[0][1])
        if jaw:
            # the lip is between the jaws: slide them off its end the way they went in, the tool as it is, and only then
            # away. Levelling the tool first dragged a lid let go at 99 deg back to 83, short of vertical, and it fell shut
            u = _rotate(p.meta["under"], p.meta["hinge_axis"], to - now)
            last, a_end = poses[-1]
            off = last - HOOK_JAW_SLIDE * u
            return entry, poses, [(last - HOOK_IN * u, a_end)] + [[(off, a_end), (off + HOOK_IN * d, a_end)] for d in (-level, np.array([0, 0, 1.0]))]
        # high up the arc the probe points upward, and that won't reach back along the handle: level it to come away
        if to < math.radians(45):
            return entry, poses, [(poses[-1][0] - HOOK_IN * away(to), poses[-1][1])]
        last = poses[-1][0]
        return entry, poses, [(last - HOOK_IN * away(to), level), (last - HOOK_IN * level, level),
                              (last + HOOK_IN * np.array([0, 0, 1.0]) - 0.01 * level, level)]

    def reaches(way, leaves):
        """How far off the worst pose is, and the first way out that the arm reaches."""
        q, worst = arm.cmd, 0.0
        for pt, a in way:
            arm.check_workspace(pt)
            q, ok, err, _ = arm.ik.solve(pt, a, q)
            worst = max(worst, 0.0 if ok else err)
        outs = []
        for leave in leaves:  # a pose, or a list of them (the stock jaw's way off a lip and then away)
            way_out, q1, err = leave if isinstance(leave, list) else [leave], q, 0.0
            for pt, a in way_out:
                q1, _, e, _ = arm.ik.solve(pt, a, q1)
                err = max(err, e)
            outs.append((err, way_out))
        for err, out in outs:
            if err < 1e-3:
                for pt, _ in out:
                    arm.check_workspace(pt)
                return worst, out
        return max(worst, min(e for e, _ in outs)), None

    # the steepest tool the arm can hold through the whole swing
    worst, chosen = float("inf"), None
    try:
        # the stock jaw comes in nearly level: low and near the arm a 30 mm run in can be out of its reach, so a shorter
        # one, though the longer keeps the wrist further off the device on the way down
        runs = (HOOK_IN, HOOK_JAW_IN) if jaw else (HOOK_IN,)
        # reaching over a lid, flatter as a last resort: the stock gripper is longer than the probe and fell 3-7 mm short
        tilts = HOOK_TILTS_JAW if jaw else HOOK_TILTS + (((30, 90, 0), (20, 90, 0)) if falls else ())
        for (deg, level_at, lowest), run_in in ((t, r) for r in runs for t in tilts):
            entry, poses, leaves = path(math.radians(deg), math.radians(level_at), math.radians(lowest), run_in)
            err, leave = reaches([entry, *poses], leaves)
            if err == 0.0:
                chosen = deg
                break
            worst = min(worst, err)
    except SafetyStop as e:
        result["reason"] = str(e)
        return result
    if chosen is None:
        result["reason"] = f"{p.id} is out of reach for this swing: best IK is {worst * 1000:.1f} mm off"
        return result
    app, t0, log0 = arm.app, arm.d.time, len(arm.force_log)
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    arm.status = f"hook_pull {p.id}"
    bias = np.zeros(5)
    try:
        import affordances

        if jaw:
            # the moving jaw up and out of the way, the fixed jaw's inner face up: then it's a thin flat hook
            q_in = _roll_up(arm, arm.ik.solve(entry[0], entry[1], arm.cmd)[0], entry[1])
            skills.move_joints(arm, np.r_[arm.cmd[:4], q_in[4]])
            arm.grip(HOOK_JAW_OPEN, 0.5)
        a_in = entry[1] / np.linalg.norm(entry[1])
        stage = None if falls else next((pt for pt in (entry[0] - back * a_in + up * np.array([0, 0, 1.0]) for back, up in HOOK_STAGES)
                                         if arm.ik.solve(pt, entry[1], arm.cmd)[1]), None)
        staged = stage is not None
        _, bias = affordances._approach(arm, stage if staged else entry[0], entry[1], f"hook_pull {p.id}")
        if jaw and arm.sensing:
            # low and near level, the estimate reads 4-5 N with nothing touching (D32): over the noise, not at the bare limit
            limit = params.get("force_limit", FORCE_LIMIT["hook_pull"] + arm.noise_n)
        way_in = [(stage, entry[1])] * staged + [entry]
        if not falls:
            u_in = poses[0][0] - entry[0]
            feel = min(HOOK_FEEL, float(np.linalg.norm(u_in)))
            u_in = u_in / np.linalg.norm(u_in)
            way_in.append((poses[0][0] - feel * u_in, poses[0][1]))
        else:
            way_in.append(poses[0])
        # zeroed up there, clear of everything: at the stage over a level tool the drift alone read 7-9 N (D32). Reaching over
        # a lid resting open, the entry is 40 mm above its top edge, as clear: unzeroed, the long reach up to it read 6 N on
        # the way in with nothing touching (centrifuge lid at 105 deg, after a pick and place)
        if staged or falls:
            arm.tare()
        peak, ok1, why1 = _follow(arm, way_in, HOOK_SPEED, bias, limit, "in", follow=jaw, ramp_s=HOOK_RAMP_S)
        arm.tare(False)
        if ok1 and not falls:
            ax, k = p.meta["hinge_axis"], max(len(poses) - 1, 1)
            up_in = _rotate(p.meta["pull"], ax, -now)  # off the lip's underside, shut

            def shifted(d_in, d_up):
                """The swing and the way off, moved d_in along the way in and d_up off the lip: the same point on the handle
                all the way up, so the shift turns with it."""
                d = lambda th: d_in * _rotate(u_in, ax, th) + d_up * _rotate(up_in, ax, th)
                return ([(pt + d((to - now) * j / k), a) for j, (pt, a) in enumerate(plan0)],
                        [(pt + d(to - now), a) for pt, a in leave0])

            plan0, leave0 = poses, leave
            for n_try, lift in enumerate(HOOK_LIFTS):
                poses, leave = shifted(0.0, lift)
                start = (poses[0][0] - feel * u_in, poses[0][1])
                if n_try:  # back out to where the slow part began, higher
                    _follow(arm, [(arm.ik.fk(arm.cmd - bias)[0], poses[0][1]), start], HOOK_FEEL_SPEED, bias, 2 * limit,
                            "back", ramp_s=HOOK_RAMP_S)
                # zeroed where it is, it feels the riser at a few newtons: low and level, the estimate's own drift (D32)
                # is 4-7 N with nothing touching, and pressed at the bare limit the swing began against the riser and stalled
                arm.tare()
                peak1, ok1, why1 = _follow(arm, [start, poses[0]], HOOK_FEEL_SPEED, bias,
                                           min(limit, HOOK_FEEL_N + arm.noise_n) if arm.sensing else limit, "in", follow=jaw)
                arm.tare(False)
                peak = max(peak, peak1)
                if ok1:
                    break
                # from where the joints say the tip is: pressed on something, the command has run on ahead of it
                short = float((poses[0][0] - arm.ik.fk(arm.read_q())[0]) @ u_in) + HOOK_BACK
                if short <= HOOK_RISER_MAX:  # met the riser: the jaw is under the lip, short of the plan by this much
                    poses, leave = shifted(-short, lift)
                    # back off it before swinging: still pressed, the swing's first ticks read that push and stopped there
                    _follow(arm, [(arm.ik.fk(arm.cmd - bias)[0], poses[0][1]), poses[0]], HOOK_FEEL_SPEED, bias, 2 * limit,
                            "back", ramp_s=HOOK_RAMP_S)
                    for _ in range(int(HOOK_SETTLE_S * CONTROL_HZ)):
                        arm.send(arm.cmd)
                        arm.tick()
                    ok1, why1 = True, None
                    result["met_riser_mm"] = round(short * 1000, 1)
                    break
                # further out than any riser behind a lip: the jaw met the face below it, low by the calibration error
                result.setdefault("met_below_mm", []).append(round(short * 1000, 1))
                why1 = f"{why1} {short * 1000:.0f} mm short of the lip, on the face below it"
            result["lifted_mm"] = round(lift * 1000, 1)
        peak2, ok2, why2 = (0.0, False, None)
        if ok1:
            # along the handle toward the hinge, at each pose's angle
            ax, k = p.meta["hinge_axis"], max(len(poses) - 1, 1)
            u_h = _rotate(p.meta["under"], ax, -now)
            inward = [_rotate(u_h, ax, (to - now) * j / k) for j in range(len(poses))]
            peak2, ok2, why2 = _follow(arm, poses, HOOK_SPEED, bias, limit, "swing", follow=jaw, ramp_s=HOOK_RAMP_S,
                                       give=None if falls else inward, give_zero=arm.tip_force_vec() if arm.sensing else None)
        peak3, _, _ = _follow(arm, [(arm.ik.fk(arm.cmd - bias)[0], poses[-1][1]), *leave], HOOK_SPEED, bias, 2 * limit, "out", ramp_s=HOOK_RAMP_S)
        # a handle let go past its balance point falls on its own: give it time, and stop waiting once a reading says it landed
        for k in range(int((FALL_S if falls else SETTLE_S) * CONTROL_HZ)):
            arm.send(arm.cmd)
            arm.tick()
            if falls and k > SETTLE_S * CONTROL_HZ and any(app.readings.get(c) != before.get(c) for c in _changes(app, before, n_events)):
                break
        seq = _changes(app, before, n_events)
        peak = max(peak, peak2, peak3)
        result.update(peak_force_n=round(peak, 2), travel_mm=round(float(np.linalg.norm(p.pos - poses[-1][0])) * 1000, 2), force_limit_n=limit,
                      stop="force_limit" if not (ok1 and ok2) else "end", readout_change=seq)
        moved = [c for c in seq if app.readings.get(c) != before.get(c)]
        if not ok1:
            result.update(verdict="MISSED", reason=f"going in under {p.id}, {why1}, before it could lift anything")
        elif not ok2:
            result.update(verdict="FAIL" if why2.startswith("met") else "MISSED", reason=f"swinging {p.id}, {why2} before {to_deg:g} deg",
                          channel=moved[0] if moved else None)
        elif moved:
            result.update(verdict="PASS", reason=f"{p.id} swung to {to_deg:g} deg: {moved[0]} {' -> '.join(map(str, seq[moved[0]]))}", channel=moved[0])
        elif not _has_reading_for(arm, p):
            result.update(verdict="OBSERVED", reason=f"the arm carried {p.id} to {to_deg:g} deg, peak {peak:.1f} N. Nothing on this device reads it")
        elif result.get("lifted_mm"):
            # it went in higher than planned, having met something below the lip: it may have gone over the lip, not
            # under it, and swung nothing. Not a finding against the device
            result.update(verdict="MISSED", reason=f"the arm swung to {to_deg:g} deg and no reading changed, but the jaw went in "
                          f"{result['lifted_mm']:g} mm higher than planned and may have passed over {p.id}'s lip")
        else:
            result.update(verdict="FAIL", reason=f"the arm swung {p.id} to {to_deg:g} deg and no reading changed")
        if result["verdict"] in ("PASS", "OBSERVED"):
            # past vertical it falls on by itself, somewhere short of its stop (the hinge's friction holds it: 92-98 deg
            # for a 105 deg stop in the sim): believe where it was asked to go
            axis, hinge, th = p.meta["hinge_axis"], p.meta["hinge"], to - now
            at = hinge + _rotate(p.pos - hinge, axis, th)
            T = p.T.copy()
            T[:3, 3] = at
            T[:3, :3] = np.c_[_rotate(p.T[:3, 0], axis, th), _rotate(p.T[:3, 1], axis, th), _rotate(p.T[:3, 2], axis, th)]
            parts[i] = replace(p, T=T, state=to, range=(-to, math.radians(p.meta["open_deg"]) - to),
                               meta={**p.meta, "angle": to, "under": _rotate(p.meta["under"], axis, th), "pull": _rotate(p.meta["pull"], axis, th)})
    except SafetyStop as e:
        seq = _changes(app, before, n_events)
        result.update(verdict="ABORTED", reason=f"safety stop: {e}", readout_change=seq)
        try:
            arm.tare(False)
            skills.go_home(arm)
        except SafetyStop:
            pass
    if jaw:
        try:
            arm.grip(JAW_SHUT, 0.5)  # a finger again
        except SafetyStop:
            pass
    result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
    arm.status = "idle"
    return result


def _has_reading_for(arm, p):
    return bool(p.meta.get("reads"))


# --- pick and place, with the arm's own jaws ---------------------------------------------------------------------------
# The fixed jaw's inner face is the tip frame's x = 0 plane on the stock gripper, and the moving jaw closes toward it
# along +x. An object is held with one flat on the fixed jaw: its middle sits flats / 2 out along x from the face.
JAW_FACE_X = 0.003      # the stock tip (the middle of the fixed jaw's end) to its inner face, along the tip frame's x
JAW_CLEAR = 0.0015      # going down, the fixed jaw stands this far off the flat
HELD_FACE_X = 0.001     # held, an object's flat sits this far from the tip along x: measured in the sim, 3.5 mm nearer
                        # than the plan's JAW_FACE_X + JAW_CLEAR, as the jaws push it over and squeeze into it
JAW_DEPTH = 0.0025      # the fixed jaw's tip goes this far past an object's grip point, along the tool: the moving jaw's goes 1.6 mm further, and tilted, a jaw's lower edge 2 mm more
MOVING_JAW_DEEPER = 0.0016  # open, the moving jaw's tip stands this much further out along the tool than the fixed jaw's
TOP_CLEAR = 0.003       # gripping something that stands above the object's top (a lifting loop): the jaws' lowest point
                        # stays this far above the top, for the servos' dead band (about 2 mm at the tip) and a margin. Down on
                        # it, the moving jaw met the collar's edge first and turned the object out of the jaws
GRIP_TILTS = (90, 80, 75, 70, 65, 60, 55, 50)   # tool tilts below level to try, steepest first: the same one, pick to place
PAN_XY = np.array([0.0388, 0.0])                # the pan axis, arm frame: what the tool's plane turns about
JAW_GAP = (0.0158, 0.075)   # the gap at the jaws' tips: 15.8 mm at gripper 0 rad, opening 75 mm per rad (23 at 0.1, 31 at 0.2)
JAW_SPARE = 0.006           # going down, this much more than the object's width between the jaws
JAW_SHUT = -0.17        # and to close to: an object stops it short
JAW_EMPTY = -0.12       # a reading at or under this, shut, means nothing is between the jaws, unless the servo is still pushing:
JAW_LOAD = 0.15         # over this (N.m), it is squeezing something too thin to stop it short
JAW_CLOSE_SPEED = 0.5   # rad/s, shutting
JAW_STALL = 0.05        # shutting, the reading this far behind the command means the jaws have met something
JAW_SQUEEZE = 0.3       # once they meet something, command this far (rad) past it, so the servo keeps pushing at its
                        # torque limit: 0.012 rad was used up as the contacts gave, and the jaws held at no load and dropped it
JAW_SETTLE_S = 0.5
FACE_TILT = 6.0         # deg: jaws' faces this near vertical close square on a flat-sided object (_face_tilt)
SEARCH_MM = (1.0, 2.0)  # placing, the circles to feel round for a bore on, and how many points on each
SEARCH_DIRS = 6
SEARCH_LIFT = 0.002     # up this far to move over
SEARCH_GAIN = 0.0015    # getting this much further down than where it stopped is progress
SEARCH_DONE = 0.0015    # and within this of the seat's height, done
SEARCH_TRIES = 16
CARRY_SPEED = 0.03      # m/s, mean, carrying an object across
CARRY_RAD_S = 0.3       # and the fastest joint's mean speed
MAX_TRIES = 3           # ways down to try when the jaws meet something on the way
JAW_MIN_SQUEEZE = 0.002  # a grip has to be this much wider than the jaws' shut gap for them to squeeze it
PLACE_CLEAR = 0.0025    # lowering into a well, the jaws' lowest point stays this far above its mouth: short of seating,
                        # they let go there and the object drops the rest of the way, as a person's fingers would
LIFT_M = 0.075          # lift this far, to clear what the object stood in
PICK_SPEED = 0.02       # m/s, down and up
PLACE_FORCE_N = 3.0     # going down with an object, stop here: it has met something
DROP_MAX_MM = 120.0     # place with drop_mm: let go at most this far above the seat
DROP_HOLD_S = 0.4       # held still over the well this long before letting go, so the object stops swinging in the jaws
DROP_OPEN_S = 1.0       # the jaws opening, eased open over this long: snapped open (the servo's own speed), the squeezed
                        # jaws let go of the tube with a flick that threw it 0.1-0.5 m/s sideways or upward
DROP_SETTLE_S = 1.5     # then this long for it to fall and come to rest before the jaws go up and the reading is judged
DROP_REACH_M = 0.002    # the release pose must be reachable to this
DROP_CARRY_M = 0.04     # carried over this far above the higher of the release pose and the pose above the well, then
                        # straight down to let go: carried at the pose above the well, a tube hanging 60 mm under the
                        # jaws met the device's side panel on the way and was knocked out of them
DOWN = np.array([0.0, 0.0, -1.0])
SAG_FOLLOW = 0.05       # each tick, this share of the joints' shortfall goes into the bias: some 0.2 s to catch up
def _tool_axis(arm, at, tilt):
    """The tool's axis, tilt below level, in the vertical plane through the pan axis and `at`: on a 5-joint arm the
    tool can't point anywhere else."""
    r = np.asarray(at[:2], float) - PAN_XY
    r /= np.linalg.norm(r)
    return np.array([*(math.cos(tilt) * r), -math.sin(tilt)])


def _jaw_q(arm, centre, jaw_dir, tilt, half, q0, depth=None, signs=(1.0, -1.0)):
    """Joints that put the jaws either side of `centre` (the grip point), closing as near jaw_dir as the tool's tilt
    allows, the fixed jaw's tip JAW_DEPTH past the grip point along the tool. The wrist roll aims the jaws; the other
    four put the tip there. Returns (q, ok, err, axis)."""
    a = _tool_axis(arm, centre, tilt)
    best = None
    for sign in signs:
        x_want = sign * np.asarray(jaw_dir, float)
        x_want = x_want - (x_want @ a) * a
        x_want /= np.linalg.norm(x_want)
        tip = centre - x_want * (JAW_FACE_X + half) + (JAW_DEPTH if depth is None else depth) * a
        qs, ok, err = np.array(q0, float), False, float("inf")
        for _ in range(4):
            qs, ok, err, _ = _solve_rolled(arm, tip, a, qs)
            arm.ik.fk(qs)
            x_now = arm.ik.d.site_xmat[arm.tip].reshape(3, 3)[:, 0]
            turn = math.atan2(np.cross(x_now, x_want) @ -a, x_now @ x_want)
            trial = []
            for s in (1, -1):  # which way the roll joint turns x: try both, keep the better
                qt = qs.copy()
                qt[4] = qs[4] + s * turn
                arm.ik.fk(qt)
                trial.append((arm.ik.d.site_xmat[arm.tip].reshape(3, 3)[:, 0] @ x_want, qt))
            qs = max(trial, key=lambda t: t[0])[1]
        qs, ok, err, _ = _solve_rolled(arm, tip, a, qs)
        lo, hi = arm.m.jnt_range[arm.m.joint("wrist_roll").id]
        ok = ok and lo <= qs[4] <= hi
        if best is None or (ok and not best[1]) or (ok == best[1] and abs(qs[4]) < abs(best[0][4])):
            best = (qs, ok, err, a)
    return best or (np.array(q0, float), False, float("inf"), a)


def _solve_rolled(arm, pos, axis, q0, iters=200):
    """IK that keeps q0's wrist roll: the jaws' aim. The solver's fallback seeds carry rolls of their own."""
    q, ok, err, ang = arm.ik.solve(pos, axis, q0, iters=iters)
    if q[4] != q0[4]:
        q = q.copy()
        q[4] = q0[4]
        q, ok, err, ang = arm.ik.solve(pos, axis, q, iters=iters)
        if q[4] != q0[4]:
            p, a = arm.ik.fk(np.r_[q[:4], q0[4]])
            q = np.r_[q[:4], q0[4]]
            err, ok = float(np.linalg.norm(p - pos)), float(np.linalg.norm(p - pos)) < 1e-3
            ang = math.degrees(math.acos(np.clip(a @ (np.asarray(axis) / np.linalg.norm(axis)), -1, 1)))
    return q, ok, err, ang


def _close_on(arm, bias):
    """Shut the jaws slowly until the servo's load says they've met something, then hold a little past that: a grip
    by load, as on an STS3215, not a full-torque squeeze. Returns the reading they stopped at."""
    cmd = arm.jaw()
    while cmd > JAW_SHUT:
        cmd = max(JAW_SHUT, cmd - JAW_CLOSE_SPEED / CONTROL_HZ)
        arm.d.ctrl[5] = cmd
        arm.send(arm.cmd)
        arm.tick()
        if arm.jaw() - cmd > JAW_STALL:  # it has stopped following the command: something is between the jaws
            break
    arm.grip(max(arm.jaw() - JAW_SQUEEZE, JAW_SHUT), JAW_SETTLE_S)
    return arm.jaw()


def _jaw_open(width):
    return (width + JAW_CLEAR + JAW_SPARE - JAW_GAP[0]) / JAW_GAP[1]


def _grips(p):
    return p.meta.get("grips") or [dict(axis=p.T[:3, 0], width=p.meta["flats"], depth=JAW_DEPTH, at=np.zeros(3))]


def _jaw_low(arm, q):
    """How far below the tip site the jaws' lowest point is at joints q, the moving jaw open: the shut fingertip's hull
    turned with the tool, and the moving jaw's extra reach."""
    R = arm.ik.fk_R(q)
    return float(-np.min(tip_shape(arm).world(R)[:, 2])) + MOVING_JAW_DEEPER


def _grip_poses(arm, centre, jaw_dir, half, q0, tilts=None, depth=None, floor=None, signs=(1.0, -1.0)):
    """The steepest tool tilt from which the jaws reach `centre` and can lift straight up LIFT_M from it, keeping the
    tool's direction all the way. floor: a height the jaws' lowest point stays above, by going less deep past `centre`.
    Returns (tilt, q_down, q_above, axis, depth) or the worst error."""
    worst = float("inf")
    for deg in tilts or GRIP_TILTS:
        t = math.radians(deg)
        d = JAW_DEPTH if depth is None else depth
        q, ok, err, a = _jaw_q(arm, centre, jaw_dir, t, half, q0, d, signs)
        if ok and floor is not None:
            short = floor - (arm.ik.fk(q)[0][2] - _jaw_low(arm, q))
            if short > 0:
                d -= short / max(math.sin(t), 0.5)
                q, ok, err, a = _jaw_q(arm, centre, jaw_dir, t, half, q0, d, signs)
        if not ok:
            worst = min(worst, err)
            continue
        down_at, _ = arm.ik.fk(q)
        qa, qi, fine = q, q, True
        for k in range(1, 5):  # the whole lift, not just its end: the arm's reach isn't convex
            qi, ok_i, err_i, ang = _solve_rolled(arm, down_at + np.array([0, 0, LIFT_M * k / 4]), a, qi)
            if not ok_i or ang > 2:
                worst, fine = min(worst, err_i if not ok_i else 0.001), False
                break
        if fine:
            return deg, q, qi, a, d
    return worst


def _settle(arm, q):
    """Go to q, then command it again by however far the joint readings fell short, as affordances._approach does:
    the servos sag under gravity, 10 mm and more at the tip out here. Returns the bias, command minus reading, that
    holds the arm on poses near q."""
    import affordances

    skills.move_joints(arm, q)
    for _ in range(3):
        if np.linalg.norm(arm.ik.fk(q)[0] - arm.tip_pose()[0]) < affordances.SAG_TOL:
            break
        skills.move_joints(arm, arm.cmd + q - arm.read_q())
        for _ in range(int(affordances.SAG_HOLD_S * CONTROL_HZ)):
            arm.send(arm.cmd)
            arm.tick()
    return arm.cmd - arm.read_q()


def _line(arm, to, axis, speed, limit=None, bias=None, hold_s=0.0, follow=True):
    """A straight line keeping the tool's direction and the wrist roll, with _settle's bias on every command, the bias
    following the joint readings as the sag changes along the way (SAG_FOLLOW), then hold_s at the end. Stops early
    when the force passes limit. Returns the peak force and whether it went the whole way. bias is updated in place.
    follow=False keeps the bias as it is: with the jaws shut on something still in its well, following the readings wound
    up the sideways push the squeeze had put on the arm (10 N per contact on the fixed jaw), and the object shot out
    sideways as it cleared the bore."""
    bias = np.zeros(5) if bias is None else bias
    q = arm.cmd - bias
    p0, _ = arm.ik.fk(q)
    n = max(1, int(np.linalg.norm(to - p0) / speed * CONTROL_HZ))
    peak = 0.0
    for i in range(1, n + 1):
        q, *_ = _solve_rolled(arm, p0 + (to - p0) * i / n, axis, q, iters=30)
        arm.send(q + bias)
        arm.tick()
        f = float(np.linalg.norm(arm.tip_force_vec()))
        peak = max(peak, f)
        if limit is not None and f > limit:
            return peak, False
        if follow:
            bias += SAG_FOLLOW * (q - arm.read_q())
    for _ in range(int(hold_s * CONTROL_HZ)):
        arm.send(q + bias)
        arm.tick()
        if follow:
            bias += SAG_FOLLOW * (q - arm.read_q())
    return peak, True


def _floor(p, grip):
    """The height the jaws stay above for a grip on something standing above the object's top, or None."""
    top = p.meta.get("collar", p.pos)[2] + p.meta.get("top_above", 0.0)
    if p.meta.get("collar", p.pos)[2] + grip["at"][2] <= top:
        return None
    return top + TOP_CLEAR


def _grip_order(p):
    """The object's grips to try, as (index, grip), best first. Jaws can't squeeze what is barely wider than their shut
    gap, so those go. Then faces on the body before faces on something standing above its top: closing on a thin lifting
    loop's 3 mm edges, the moving jaw turned it out from between them on every device with one (the jaws' faces aren't
    parallel), where a body's flats sit square. The device's own order holds otherwise."""
    shut_gap = JAW_GAP[0] + JAW_GAP[1] * JAW_SHUT
    ok = [(g, grip) for g, grip in enumerate(_grips(p)) if grip["width"] >= shut_gap + JAW_MIN_SQUEEZE]
    return sorted(ok, key=lambda t: _floor(p, t[1]) is not None)


def _bearing(pt):
    return math.atan2(pt[1] - PAN_XY[1], pt[0] - PAN_XY[0])


def _turn_z(v, th):
    c, s_ = math.cos(th), math.sin(th)
    return np.array([c * v[0] - s_ * v[1], s_ * v[0] + c * v[1], v[2]])


def _face_tilt(arm, q):
    """How far from vertical the jaws' faces stand at q (deg). A tool tilted off vertical closes its jaws along a tilted
    line unless they close across the arm's plane, and squeezed between tilted faces a flat-sided object turns to lie
    along them: the cuvette came up 20 deg off vertical and wouldn't go in its slot."""
    return math.degrees(math.asin(min(1.0, abs(arm.ik.fk_R(q)[2, 0]))))


def _place_poses(arm, obj, grip, well, tilt, depth, q0, x_rel, worst=False):
    """_grip_poses for lowering obj into well, held as it was picked: the tool at `tilt`, the jaws `depth` past the grip
    point, and closing along x_rel turned with the arm's pan, so the object hangs in the jaws as it stood (keeping the
    jaws' direction in the room instead would tilt it, at another bearing). Or None (with worst, the error)."""
    seat = well.meta.get("collar", well.pos)            # where the held grip point is when the object sits in it
    x = _turn_z(x_rel, _bearing(seat))
    # shut, the jaws have pushed the object onto the fixed jaw's face, and squeezing sinks it in a little
    found = _grip_poses(arm, seat + grip["at"], x, grip["width"] / 2 + HELD_FACE_X - JAW_FACE_X, q0, tilts=(tilt,), depth=depth, signs=(1.0,))
    return found if isinstance(found, tuple) or worst else None


def _search(arm, to, axis, limit, bias):
    """The held object met something short of its seat: most often a step on it caught the bore's rim, a millimetre or two
    off (the servos' dead band, and the object leaning a few degrees in the jaws). Feel round for it as a person would:
    up a little, over by SEARCH_MM in turn, down again, starting over from wherever it gets further down, until the jaws
    are at the seat or SEARCH_TRIES run out. Returns (at the seat, tries, peak force)."""
    def there():
        return arm.tip_pose()[0][2] < to[2] + SEARCH_DONE

    stop, peak, tries, k = arm.tip_pose()[0], 0.0, 0, 0
    offsets = [r * 1e-3 * np.array([math.cos(2 * math.pi * j / SEARCH_DIRS), math.sin(2 * math.pi * j / SEARCH_DIRS), 0.0])
               for r in SEARCH_MM for j in range(SEARCH_DIRS)]
    while not there() and tries < SEARCH_TRIES and k < len(offsets):
        d = offsets[k]
        tries, k = tries + 1, k + 1
        _line(arm, stop + np.array([0, 0, SEARCH_LIFT]), axis, PICK_SPEED, bias=bias)
        _line(arm, stop + d + np.array([0, 0, SEARCH_LIFT]), axis, PICK_SPEED / 2, bias=bias)
        pk, _ = _line(arm, to + (stop - to) * np.array([1, 1, 0]) + d, axis, PICK_SPEED / 2, limit=limit, bias=bias, hold_s=0.3)
        peak = max(peak, pk)
        now = arm.tip_pose()[0]
        if now[2] < stop[2] - SEARCH_GAIN:  # further down: carry on from here
            stop, k = now, 0
    return there(), tries, peak


def _carry(arm, q_to):
    """Take what the jaws hold over to q_to, the pose above where it goes, without sweeping it through the device: up
    to the higher of the two heights first, across there, then down. A joint move straight there swung a tube hanging
    60 mm under the jaws into the side of the device it was going onto, and it turned in the jaws."""
    q_now = arm.cmd.copy()
    (p0, a0), (p1, a1) = arm.ik.fk(q_now), arm.ik.fk(q_to)
    z = max(p0[2], p1[2])
    up, ok_up, *_ = _solve_rolled(arm, np.array([p0[0], p0[1], z]), a0, q_now)
    over, ok_over, *_ = _solve_rolled(arm, np.array([p1[0], p1[1], z]), a1, q_to)
    if not (ok_up and ok_over):
        return
    if z - p0[2] > 0.002:
        _line(arm, np.array([p0[0], p0[1], z]), a0, PICK_SPEED * 2)
    # across slowly: a held object turns in the jaws if swung, as they hold it near its top by their fingertips
    q0 = arm.cmd.copy()
    n = int(max(np.linalg.norm(p1[:2] - p0[:2]) / CARRY_SPEED, np.max(np.abs(over - q0)) / CARRY_RAD_S, 0.5) * CONTROL_HZ)
    for i in range(1, n + 1):
        arm.send(q0 + (0.5 - 0.5 * math.cos(math.pi * i / n)) * (over - q0))
        arm.tick()


def _grip_check(arm, p):
    if getattr(arm, "effector", "probe") != "stock" or not hasattr(arm, "grip"):
        return (f"the probe hangs along the fixed jaw's inner face, where {p.id} would sit between the jaws: "
                "pick and place need the stock gripper (effector stock)")
    return None


def pick(arm, parts, i, step):
    """Jaws open, down either side of the object's flats, shut, lift. The servo's own position says whether it holds
    anything: shut on nothing, it closes all the way. OBSERVED, with the width it read, since a pick moves nothing
    the device reads."""
    p = parts[i]
    result = {"skill": "pick", "target": p.id, "verdict": "REFUSED", "channel": None, "readout_change": {}}
    why = _grip_check(arm, p)
    if why is None and getattr(arm, "holding", None):
        why = f"already holding {arm.holding}"
    if why:
        result["reason"] = why
        return result
    grip_at = p.meta.get("collar", p.pos)
    plans, worst = [], float("inf")
    wells = [w for w in parts if w.kind == "well" and w.meta.get("reads")]
    for g, grip in _grip_order(p):  # every pair of faces the jaws can reach and lift from, best first
        for deg in GRIP_TILTS:
            found = _grip_poses(arm, grip_at + grip["at"], grip["axis"], grip["width"] / 2 + JAW_CLEAR, arm.cmd, tilts=(deg,), depth=grip["depth"], floor=_floor(p, grip))
            if not isinstance(found, tuple):
                worst = min(worst, found)
                continue
            # the jaws hold it at this tilt until they let go: rank by whether the faces stand square (FACE_TILT) and a
            # well it would go in takes the same tilt and roll, then by the device's order and the steepest tilt
            x_rel = _turn_z(arm.ik.fk_R(found[1])[:, 0], -_bearing(grip_at))
            square = _face_tilt(arm, found[1]) <= FACE_TILT
            fits = all(_place_poses(arm, p, grip, w, deg, found[4], arm.cmd, x_rel) is not None for w in wells)
            plans.append(((not (square and fits), not fits, not square), g, grip, found, x_rel))
            if square and fits:
                break
    plans = [t[1:] for t in sorted(plans, key=lambda t: t[0])]
    if not plans:
        result["reason"] = f"{p.id} is out of reach with the jaws on its faces and room to lift it: best IK is {worst * 1000:.1f} mm off"
        return result
    app, t0, log0 = arm.app, arm.d.time, len(arm.force_log)
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    arm.status = f"pick {p.id}"
    body = p.meta.get("body")
    blocked = []
    try:
        for g, grip, (tilt, q, qa, axis, depth), x_rel in plans[:MAX_TRIES]:
            down_at, above = arm.ik.fk(q)[0], arm.ik.fk(qa)[0]
            arm.grip(_jaw_open(grip["width"]), 0.5)
            bias = _settle(arm, qa)
            arm.held = {arm.m.body(body).id} if body else set()
            peak, ok_down = _line(arm, down_at, axis, PICK_SPEED, limit=PLACE_FORCE_N, bias=bias, hold_s=0.5)
            if not ok_down:
                # the jaws met something on the way down, before closing: the device round the object, most likely.
                # Back up and come down on the next pair of faces, from another side
                blocked.append(f"{peak:.1f} N going down on faces {g + 1}")
                arm.held = set()
                _line(arm, above, axis, PICK_SPEED, bias=bias)
                continue
            # the tool's centre now stands JAW_CLEAR off: shutting pushes the object onto the fixed jaw
            width_read = _close_on(arm, bias)
            # lift from where the squeeze left the arm, without pulling it back to where it was
            bias[:] = arm.cmd - arm.read_q()
            _line(arm, arm.tip_pose()[0] + (above - down_at), axis, PICK_SPEED, bias=bias, follow=False)
            # still squeezing something once it's up: the servo is held short of its command, and loaded
            held = arm.jaw() > JAW_EMPTY or arm.jaw_load() > JAW_LOAD
            peak = max((f for _, f in arm.force_log[log0:]), default=0.0)
            if held:
                arm.holding, arm.hold_tilt, arm.hold_grip, arm.hold_depth, arm.hold_x = p.id, tilt, g, depth, x_rel
                result.update(verdict="OBSERVED", tilt_deg=tilt, reason=f"holding {p.id}, tool {tilt} deg below level: the jaws stopped at {math.degrees(arm.jaw()):.1f} deg, squeezing at {arm.jaw_load():.2f} N.m, {LIFT_M * 1000:.0f} mm up")
                parts[i] = replace(p, T=_moved_T(p.T, above - down_at), meta={**p.meta, "collar": grip_at + (above - down_at), "held": True})
            else:
                arm.grip(0.2, 0.3)  # what it touched may still be against the jaws: let go before they count as hitting it
                _line(arm, arm.tip_pose()[0] + np.array([0, 0, 0.02]), axis, PICK_SPEED, bias=bias)
                arm.held = set()
                result.update(verdict="MISSED", reason=f"the jaws shut on nothing ({math.degrees(width_read):.1f} deg)")
            result.update(peak_force_n=round(peak, 2), jaw_deg=round(math.degrees(arm.jaw()), 1))
            break
        else:
            result.update(verdict="MISSED", reason=f"the jaws met something going down over {p.id} on every pair of faces: {'; '.join(blocked)}",
                          peak_force_n=round(max((f for _, f in arm.force_log[log0:]), default=0.0), 2))
    except SafetyStop as e:
        result.update(verdict="ABORTED", reason=f"safety stop: {e}")
        arm.held, arm.holding = set(), None
        try:
            arm.grip(0.2, 0.3)
            arm.tare(False)
            skills.go_home(arm)
        except SafetyStop:
            pass
    result.update(readout_change=_changes(app, before, n_events), lcd=app.lcd, duration_s=round(arm.d.time - t0, 2),
                  collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
    arm.status = "idle"
    return result


def _moved_T(T, d):
    T = T.copy()
    T[:3, 3] += d
    return T


def place(arm, parts, i, step):
    """Carry what the jaws hold over a well, lower it until it seats or meets something, let go and lift clear.
    PASS when the device's reading changed; FAIL when the well reads and nothing changed, with how far above its seat
    the object stopped; OBSERVED where nothing on the device reads that well."""
    p, params = parts[i], step.get("params", {})
    result = {"skill": "place", "target": p.id, "verdict": "REFUSED", "channel": None, "readout_change": {}}
    why = _grip_check(arm, p)
    held = getattr(arm, "holding", None)
    if why is None and not held:
        why = "the jaws hold nothing: pick something first"
    into = params.get("into", p.id)
    well = next((x for x in parts if x.id == into), None)
    if why is None and (well is None or well.kind != "well"):
        why = f"{into} is not a well"
    if why:
        result["reason"] = why
        return result
    k = next(j for j, x in enumerate(parts) if x.id == held)
    obj = parts[k]
    seat = well.meta.get("collar", well.pos)            # where the held grip point is when the object sits in it
    # the jaws hold it at the tilt they picked it with: tilting the tool now would tilt the object
    grip = _grips(obj)[arm.hold_grip]
    width = grip["width"]
    found = _place_poses(arm, obj, grip, well, arm.hold_tilt, arm.hold_depth, arm.cmd, arm.hold_x, worst=True)
    if not isinstance(found, tuple):
        result["reason"] = (f"{into} is out of reach holding {held} {arm.hold_tilt} deg below level, with room to lower it in: "
                            f"best IK is {found * 1000:.1f} mm off")
        return result
    _, q, qa, axis, _ = found
    down_at, above = arm.ik.fk(q)[0], arm.ik.fk(qa)[0]
    seated_at = down_at
    drop_mm = float(params.get("drop_mm", 0.0))
    if drop_mm:
        return _drop(arm, parts, k, obj, well, grip, seat, seated_at, qa, axis, drop_mm, params, result)
    # the jaws hold the object above its seat by their depth: where that puts them into the well's mouth, stop short
    short = well.pos[2] + PLACE_CLEAR - (down_at[2] - _jaw_low(arm, q))
    if short > 0:
        down_at = down_at + np.array([0, 0, short])
    # the estimate drifts by up to its noise floor over a 70 mm descent at these stretched poses: a stop under that was a
    # phantom, 30 mm up. The way down ends at the seat anyway, so a real meeting is pushed against only briefly
    limit = params.get("force_limit", PLACE_FORCE_N + getattr(arm, "noise_n", 0.0))
    app, t0, log0 = arm.app, arm.d.time, len(arm.force_log)
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    arm.status = f"place {held} in {into}"
    try:
        _carry(arm, qa)
        bias = _settle(arm, qa)
        arm.tare()
        peak, reached = _line(arm, down_at + np.array([0, 0, 0.001]), axis, PICK_SPEED / 2, limit=limit, bias=bias)
        searched = 0
        if not reached or arm.tip_pose()[0][2] > down_at[2] + SEARCH_DONE:
            reached, searched, peak2 = _search(arm, down_at + np.array([0, 0, 0.001]), axis, limit, bias)
            peak = max(peak, peak2)
        stopped_at, _ = arm.tip_pose()
        high_mm = (stopped_at - seated_at)[2] * 1000
        arm.grip(_jaw_open(width), 0.8)
        arm.holding = None
        # the jaws may still brush what they let go of on the way up: only once clear does touching it count as a hit
        _line(arm, stopped_at + (above - seated_at), axis, PICK_SPEED, bias=bias)
        arm.held = set()
        for _ in range(int(SETTLE_S * CONTROL_HZ)):
            arm.send(arm.cmd)
            arm.tick()
        seq = _changes(app, before, n_events)
        moved = [c for c in seq if app.readings.get(c) != before.get(c)]
        result.update(peak_force_n=round(peak, 2), stop="end" if reached else "force_limit", let_go_mm_above_seat=round(high_mm, 1), readout_change=seq)
        where = f"let go {high_mm:.1f} mm above where it seats" + ("" if reached else f", after meeting {peak:.1f} N")
        if searched:
            where += f" ({searched} tries feeling round for the bore)"
        if moved:
            result.update(verdict="PASS", channel=moved[0], reason=f"{held} into {into}: {moved[0]} {' -> '.join(map(str, seq[moved[0]]))}; {where}")
        elif well.meta.get("reads"):
            result.update(verdict="FAIL", reason=f"{held} into {into}, and no reading changed: {where}")
        else:
            result.update(verdict="OBSERVED", reason=f"{held} into {into}: {where}. Nothing on this device reads it")
        parts[k] = replace(obj, T=_moved_T(obj.T, seat - obj.meta["collar"]), meta={**obj.meta, "collar": seat, "held": False, "in": into})
    except SafetyStop as e:
        result.update(verdict="ABORTED", reason=f"safety stop: {e}")
        try:
            arm.grip(0.2, 0.3)
            arm.held, arm.holding = set(), None
            arm.tare(False)
            skills.go_home(arm)
        except SafetyStop:
            pass
    result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
    arm.status = "idle"
    return result



def _ease_jaws(arm, to, secs):
    """Open (or shut) the jaws to `to` a little each control tick across secs, instead of all at once."""
    start, n = arm.jaw(), max(1, int(secs * CONTROL_HZ))
    for i in range(1, n + 1):
        arm.grip(start + (to - start) * (0.5 - 0.5 * math.cos(math.pi * i / n)), 1.0 / CONTROL_HZ)


def _drop_high(arm, qa, q_drop, drop_at, axis):
    """The highest pose up to DROP_CARRY_M above the higher of qa and the release pose, straight over the release point:
    where _drop carries the object across before going down to let go. None when not even the lower of those reaches."""
    base = max(arm.ik.fk(qa)[0][2], drop_at[2])
    for up in np.arange(DROP_CARRY_M, -1e-9, -0.005):
        q, ok, err, _ = _solve_rolled(arm, np.array([drop_at[0], drop_at[1], base + up]), axis, q_drop)
        if err <= DROP_REACH_M:
            return q
    return None


def _drop(arm, parts, k, obj, well, grip, seat, seated_at, qa, axis, drop_mm, params, result):
    """place with drop_mm: carry what the jaws hold over the well, hold it with its grip point drop_mm above where it
    sits once seated (the jaws clear of whatever surrounds the well's mouth), let go and let gravity seat it. Goes only
    by the well's seat and the held grip, from the Part: nothing about any one device. Judged as place is."""
    held, into = obj.id, well.id
    if not 0 < drop_mm <= DROP_MAX_MM:
        result["reason"] = f"drop_mm must be over 0 and at most {DROP_MAX_MM:g}"
        return result
    drop_at = seated_at + np.array([0.0, 0.0, drop_mm * 1e-3])
    q_drop, _, err, _ = arm.ik.solve(drop_at, axis, qa)
    if err > DROP_REACH_M:
        result["reason"] = f"{into} is out of reach to let go {drop_mm:g} mm above its seat: best IK is {err * 1000:.1f} mm off"
        return result
    limit = params.get("force_limit", PLACE_FORCE_N + getattr(arm, "noise_n", 0.0))
    app, t0, log0 = arm.app, arm.d.time, len(arm.force_log)
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    arm.status = f"place {held} in {into}, dropped from {drop_mm:g} mm"
    try:
        q_high = _drop_high(arm, qa, q_drop, drop_at, axis)
        if q_high is None:
            result["reason"] = f"{into} is out of reach to carry {held} over it clear of the device"
            return result
        _carry(arm, q_high)
        bias = _settle(arm, q_high)
        arm.tare()
        peak, reached = _line(arm, drop_at, axis, PICK_SPEED / 2, limit=limit, bias=bias, hold_s=DROP_HOLD_S)
        let_go_at, _ = arm.tip_pose()
        high_mm = (let_go_at - seated_at)[2] * 1000
        _ease_jaws(arm, _jaw_open(grip["width"]), DROP_OPEN_S)
        arm.holding = None
        for _ in range(int(DROP_SETTLE_S * CONTROL_HZ)):
            arm.send(arm.cmd)
            arm.tick()
        _line(arm, let_go_at + np.array([0.0, 0.0, 0.03]), axis, PICK_SPEED, bias=bias)
        arm.held = set()
        seq = _changes(app, before, n_events)
        moved = [c for c in seq if app.readings.get(c) != before.get(c)]
        result.update(peak_force_n=round(peak, 2), stop="end" if reached else "force_limit", let_go_mm_above_seat=round(high_mm, 1),
                      drop_mm=drop_mm, readout_change=seq)
        where = f"let go {high_mm:.1f} mm above where it seats and let it fall" + ("" if reached else f", after meeting {peak:.1f} N on the way over")
        if moved:
            result.update(verdict="PASS", channel=moved[0], reason=f"{held} into {into}: {moved[0]} {' -> '.join(map(str, seq[moved[0]]))}; {where}")
        elif well.meta.get("reads"):
            result.update(verdict="FAIL", reason=f"{held} into {into}, and no reading changed: {where}")
        else:
            result.update(verdict="OBSERVED", reason=f"{held} into {into}: {where}. Nothing on this device reads it")
        parts[k] = replace(obj, T=_moved_T(obj.T, seat - obj.meta["collar"]), meta={**obj.meta, "collar": seat, "held": False, "in": into})
    except SafetyStop as e:
        result.update(verdict="ABORTED", reason=f"safety stop: {e}")
        try:
            arm.grip(0.2, 0.3)
            arm.held, arm.holding = set(), None
            arm.tare(False)
            skills.go_home(arm)
        except SafetyStop:
            pass
    result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
    arm.status = "idle"
    return result

# --- swing: a door on a vertical hinge, with the arm's own jaws --------------------------------------------------------
# hook_pull lifts a lid from under its lip, about a level hinge. A door on a vertical hinge swings its handle round a
# horizontal arc instead, and the SO-101 keeps its tool in the vertical plane through its pan axis: a tool square to the
# handle with the door shut meets it 50-60 deg off square once the door is 45 deg open, and from about 70 deg the handle
# faces away from the arm altogether. So swing works the door three ways, each over the part of the arc where it can:
#   grip      the jaws shut on the handle's bar from in front and draw it round the arc: unlatching, up to SWING_GRIP_DEG
#   straddle  the jaws, opened wide, come down astride the leaf's top edge (found first by touching down on it) and carry
#             it round the arc either way, the tool steep and the jaws' gap across the leaf
#   push      the last SWING_GRIP_DEG of a close: the shut fingertip on the bar's front, on past shut so a latch catches
# It goes only by the handle's hinge line, range, bar size and clearance from the leaf (the Part's meta and size), and
# what it measures: nothing about any one device.
SWING_FORCE_N = 11.0        # default force limit. A snap latch takes about 4 N at a handle, and drawing it from a stretched,
                            # level arm the servos' estimate read about 1.6 x the jaws' true pull + 3.8 N (10.9 N for 4.4,
                            # 17.5 for 8.2): their joints' friction at a crawl. The jaws themselves held 15 N without slipping
SWING_CAP_MARGIN_N = 1.5    # whatever is asked, stop this far under the hard cap: a FAIL with its angle, not a safety stop
SWING_STALL_M = 0.010       # the arm's reading this far behind its command along the arc: the door isn't following
SWING_GRIP_STALL_M = 0.020  # in the jaws, with no bias following, the arm lags its path by its compliance under the pull itself
SWING_DWELL_S = 1.5          # at the limit in the jaws, hold this long for the door to give: a latch, past its peak, lets go
SWING_DWELL_M = 0.0005       # and it's still giving while the tip moves this far in that time
SWING_DWELL_OVER_N = 1.0     # held at the limit, the force passing it by this much ends it (the hard cap is near)
SWING_GRIP_DEG = 50.0       # the jaws on the bar from shut to here: past 50 deg the bar's front faces 60 deg and more off the arm
SWING_LET_GO = 0.25         # rad past the bar's width, letting go of it (the moving jaw swings away from the leaf)
SWING_CATCH_S = 0.6         # at the end of a draw, held there while the arm catches up with its sag
SWING_SPEED = 0.02          # m/s along the arc
SWING_UNLATCH_SPEED = 0.005  # and over the first SWING_UNLATCH_DEG from shut, where a latch holds: the force builds slowly
SWING_UNLATCH_DEG = 4.0
SWING_IN_SPEED = 0.01       # m/s going in to the bar and down astride the leaf
SWING_OUT = 0.04            # start this far out from the bar, along the tool
SWING_GRIP_DEPTH = 0.010    # the fixed jaw's tip this far past the bar's middle, along the tool: 8 mm past its back, where
                            # the jaws narrow behind it. At 8 mm (just past its middle) the bar slid out of them at 4 N
SWING_GRIP_TILTS = (0, 10, 20, 30)            # deg below level, flattest first: the bar stands upright
SWING_TOP_TILTS = (90, 80, 70, 60, 50, 40)    # astride the leaf, steepest first
SWING_STRADDLE_OPEN = 0.35  # gripper (rad) astride the leaf: 42 mm between the jaws' tips
SWING_STRADDLE_ANG = 6.0    # deg of tool-axis error allowed astride the leaf: the jaws' 42 mm take it up
SWING_ROLL_TOL = 0.03       # cos: a wrist roll this near the best line-up is as good, if it's nearer the last
SWING_CLEAR_ABOVE = 0.08    # over the door's top by this, going round it: the wrist camera hangs below the tool
SWING_TRANSIT_N = 10.0      # going round the door through free air: the estimate swings 5 N and more on nothing there
SWING_STRADDLE_INSET = 0.025  # astride the leaf this far in from the bar's radius: the handle's legs stand out at the bar
SWING_STRADDLE_BACK = 0.003   # up off the leaf's top, once it has met the gripper between the jaws
SWING_JAW_LEN = 0.04          # about how far the jaws' gap reaches up from the tip, for clearing the door after
SWING_STRADDLE_SLACK = 0.002  # what's left of the gap between the pushing jaw and the leaf, as aimed
SWING_LEAF_T = 0.003        # the leaf's thickness, assumed: only its middle plane is aimed at, and the jaws are 42 mm apart
SWING_TOUCH_ABOVE = 0.08    # coming down astride the leaf starts this far above the handle's top
SWING_TOUCH_SPEED = 0.01
SWING_TOUCH_N = 1.5         # over the arm's noise, touching down: the leaf's top
SWING_LIFT = 0.04           # up off the leaf's top before moving over or away
SWING_PAST_DEG = 4.0        # a close pushes on this far past shut; the door's stop ends it
SWING_SHUT_DEG = 2.0        # within this of shut counts as shut
SWING_STEP_DEG = 2.0        # the arc is planned at this spacing
SWING_DENSE_M = 0.003       # and any straight move between poses at this


def _door_unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _swing_check(arm, p, to_deg):
    if p.kind != "handle":
        return f"{p.id} is a {p.kind}: swing works a door by its handle"
    if p.grip == "pinch":
        return f"{p.id} needs a pinch grip; the no-thumbs rule allows only the fingertips"
    if abs(_door_unit(p.meta["hinge_axis"])[2]) < math.cos(math.radians(20)):
        return f"{p.id}'s hinge isn't upright: swing is for a door on a vertical hinge (hook_pull lifts a lid)"
    if getattr(arm, "effector", "probe") != "stock" or not hasattr(arm, "grip"):
        return "swing needs the stock gripper's jaws (effector stock)"
    if not 0 <= to_deg <= p.meta["open_deg"]:
        return f"angle must be between 0 and {p.meta['open_deg']:g} deg"
    return None


class _Door:
    """Where the handle's bar and the leaf are at any angle th from shut (rad), from the Part as it is now."""

    def __init__(self, p):
        self.H, self.k = np.asarray(p.meta["hinge"], float), _door_unit(p.meta["hinge_axis"])
        now = p.meta.get("angle", 0.0)
        self.bar0 = self.H + _rotate(np.asarray(p.pos, float) - self.H, self.k, -now)
        self.n0 = _rotate(np.asarray(p.normal, float), self.k, -now)
        self.r_bar = float(p.size[1]) / 2                  # the bar's radius, from its width across
        self.face = float(p.size[2]) / 2 + float(p.meta["clear"])   # bar's middle to the leaf's outer face, along the normal
        self.bar_top = float(p.pos[2]) + float(p.size[0]) / 2
        self.top = None                                      # about where the leaf's top edge is, once the jaws have met it

    def bar(self, th):
        return self.H + _rotate(self.bar0 - self.H, self.k, th)

    def n(self, th):
        return _rotate(self.n0, self.k, th)

    def leaf(self, th, inset=0.0):
        """The leaf's middle plane, at the bar's radius less `inset` (toward the hinge) and the bar's height."""
        p = self.bar(th) - (self.face + SWING_LEAF_T / 2) * self.n(th)
        e = np.cross(self.k, self.n(th))
        e = e if e @ (p - self.H) > 0 else -e
        return p - inset * e

    def turn(self, planned, actual):
        """How far round the hinge (rad, opening positive) a point is from where it was planned to be: from the arm's
        own reading of its tip, where the door it held really went."""
        u, v = planned - self.H, actual - self.H
        u, v = u - (u @ self.k) * self.k, v - (v @ self.k) * self.k
        return math.atan2(float(self.k @ np.cross(u, v)), float(u @ v))


def _swing_roll(arm, q, axis, want):
    """q with the wrist rolled so the tip frame's x points as near `want` as the tool's axis allows: searched over the
    roll's whole range, then of the rolls near enough the best, the one nearest q's own (no flip mid-arc)."""
    a = _door_unit(axis)
    w = np.asarray(want, float) - (np.asarray(want, float) @ a) * a
    if np.linalg.norm(w) < 1e-6:
        return q
    w = _door_unit(w)
    lo, hi = arm.m.jnt_range[arm.m.joint("wrist_roll").id]
    rolls = np.r_[np.linspace(lo, hi, 64), q[4]]
    fit = np.array([arm.ik.fk_R(np.r_[q[:4], r])[:, 0] @ w for r in rolls])
    r = rolls[np.argmax(fit)]
    step = (hi - lo) / 63
    for _ in range(12):   # refine about the best by halving steps
        step /= 2
        r = max((np.clip(r + d, lo, hi) for d in (-step, 0.0, step)), key=lambda x: arm.ik.fk_R(np.r_[q[:4], x])[:, 0] @ w)
    best = arm.ik.fk_R(np.r_[q[:4], r])[:, 0] @ w
    near = [x for x, f in zip(rolls, fit) if f >= best - SWING_ROLL_TOL] + [r]
    return np.r_[q[:4], min(near, key=lambda x: abs(x - q[4]))]


def _swing_dense(poses):
    """Poses (tip, axis, want_x, th) with any long straight move between two split up, for planning."""
    out = [poses[0]]
    for p1 in poses[1:]:
        p0 = out[-1]
        n = max(1, int(np.linalg.norm(p1[0] - p0[0]) / SWING_DENSE_M))
        for i in range(1, n + 1):
            f = i / n
            w = None if p1[2] is None else (p1[2] if p0[2] is None else _door_unit(p0[2] + (p1[2] - p0[2]) * f))
            out.append((p0[0] + (p1[0] - p0[0]) * f, _door_unit(p0[1] + (p1[1] - p0[1]) * f), w, p0[3] + (p1[3] - p0[3]) * f))
    return out


def _swing_plan(arm, poses, q0, ang_max=3.0):
    """IK along (tip, axis, want_x, th) poses, densely, each seeded from the last; the jaws' x keeps its sign along the
    way, so the wrist doesn't roll over half way. Returns [(q, tip, th)], or None if a pose is out of reach or a step
    jumps IK branch."""
    out, q, x_prev = [], np.asarray(q0, float), None
    for tip, axis, want, th in _swing_dense(poses):
        arm.check_workspace(tip)
        # the first pose from where the arm is, or failing that from home: IK from a pose far off can stall short
        for seed in ([q] if out else [q, getattr(arm, "home_q", q)]):
            q1, *_ = arm.ik.solve(tip, axis, seed, iters=60)
            if want is not None:
                w = np.asarray(want, float)
                if x_prev is not None and w @ x_prev < 0:
                    w = -w
                q1 = _swing_roll(arm, q1, axis, w)
            q1, ok, err, ang = _solve_rolled(arm, tip, axis, q1, iters=60)
            if ok and ang <= ang_max:
                break
        if not ok or ang > ang_max or (out and np.max(np.abs(q1 - q)) > BRANCH_RAD):
            if os.environ.get("SWING_DEBUG"):
                print(f"  plan: pose {len(out)} at {np.round(tip, 3)} ok {ok} ang {ang:.1f} dq {np.round(q1 - q, 2)}")
            return None
        out.append((q1, tip, th))
        q, x_prev = q1, arm.ik.fk_R(q1)[:, 0]
    return out


def _swing_go(arm, plan, speed, bias, limit, stall=SWING_STALL_M, follow=True, dwell=0.0):
    """Through a plan at `speed` along the tip's path, the bias following the sag (unless not `follow`: holding a bar in
    the jaws, a bias that follows what the door won't give winds the pull up past any latch, and the jaws pry). Stops
    when the force passes limit, or when the arm's reading falls `stall` behind its command (what it holds isn't
    following). With `dwell` (s), the force limit holds the command instead of stopping, and it goes on again once the
    force is back under it: a pull held at the limit, so a latch's hold, which falls off as it opens, is drawn through
    at a crawl. It stops only when the tip, held there, moves less than SWING_DWELL_M in `dwell` seconds.
    Returns (peak force, the index reached, why it stopped short or None)."""
    peak = 0.0
    for k in range(1, len(plan)):
        (q0, p0, th0), (q1, p1, th1) = plan[k - 1], plan[k]
        v = speed if min(th0, th1) > math.radians(SWING_UNLATCH_DEG) else min(speed, SWING_UNLATCH_SPEED)
        n = max(1, int(np.linalg.norm(p1 - p0) / v * CONTROL_HZ))
        i, f, held, mark = 0, 0.0, 0, None
        while i < n:
            if not (dwell and f > limit):
                i += 1
                held, mark = 0, None
            else:   # at the limit: hold the command here, and watch whether what it holds still gives
                if mark is None:
                    mark = arm.tip_pose()[0]
                held += 1
                if float(np.linalg.norm(arm.tip_pose()[0] - mark)) > SWING_DWELL_M:
                    held, mark = 0, arm.tip_pose()[0]
                elif held > dwell * CONTROL_HZ:
                    return peak, k - 1, f"met {limit:.1f} N and held there {dwell:g} s"
            q = q0 + (q1 - q0) * i / n
            arm.send(q + bias)
            arm.tick()
            if follow:
                bias += SAG_FOLLOW * (q - arm.read_q())
            f = float(np.linalg.norm(arm.tip_force_vec()))
            peak = max(peak, f)
            if f > limit and not dwell:
                return peak, k - 1, f"met {f:.1f} N"
            if f > limit + SWING_DWELL_OVER_N:   # held, the force still climbing: nothing more to wait for
                return peak, k - 1, f"met {f:.1f} N"
            lag = float(np.linalg.norm(arm.ik.fk(q)[0] - arm.tip_pose()[0]))
            if stall and lag > stall:
                return peak, k - 1, f"stalled {lag * 1000:.0f} mm behind its path at {f:.1f} N"
    return peak, len(plan) - 1, None


def _door_arc(a, b):
    n = max(2, int(abs(b - a) / math.radians(SWING_STEP_DEG)) + 1)
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def _door_grip_poses(arm, door, ths, tilt, held=np.zeros(3)):
    """The jaws across the bar, level, the moving one (out along x) on the side away from the leaf: off square, the
    leaf's face comes in close on one side of the bar, and the moving jaw opening there to let go drove into it."""
    up = np.array([0, 0, 1.0])
    far = max(ths, key=lambda th: abs(th))
    a_far = _tool_axis(arm, door.bar(far), math.radians(tilt))
    sign = 1.0 if np.cross(a_far, up) @ door.n(far) >= 0 else -1.0
    out = []
    for th in ths:
        b = door.bar(th)
        a = _tool_axis(arm, b, math.radians(tilt))
        x = sign * _door_unit(np.cross(a, up))     # across the bar, level
        out.append((b + SWING_GRIP_DEPTH * a - (JAW_FACE_X + door.r_bar + JAW_CLEAR) * x + held, a, x, th))
    return out


def _door_top_poses(arm, door, ths, z, tilt, x_c, shift=0.0):
    """Astride the leaf's top edge, SWING_STRADDLE_INSET in from the bar's radius (clear of the handle): the tip at
    height z, the middle of the jaws' gap (x_c out along x from the tip) on the leaf's middle plane, or `shift` off it
    along the leaf's normal, x across the leaf."""
    out = []
    for th in ths:
        s = door.leaf(th, SWING_STRADDLE_INSET) + shift * door.n(th)
        s[2] = z
        a = _tool_axis(arm, s, math.radians(tilt))
        x = _door_unit(door.n(th) - (door.n(th) @ a) * a)
        out.append((s - x_c * x, a, x, th))
    return out


def _door_backed(pose, d=SWING_OUT):
    return (pose[0] - d * pose[1], *pose[1:])


def _door_line(arm, to, axis, speed=SWING_SPEED, limit=SWING_TRANSIT_N):
    """A straight move of the tip to `to` with the tool along `axis`, planned densely so no step jumps IK branch (_line
    re-solves each step on its own, and up by the leaf at 45 deg it flipped the wrist 1.5 rad in one tick: 75 N on the
    hard cap). Zeroed where it starts. Returns whether it went (False: no such path, or it met `limit`)."""
    tip, now = arm.tip_pose()
    x = arm.ik.fk_R(arm.read_q())[:, 0]
    plan = _swing_plan(arm, [(tip, now, x, math.pi), (np.asarray(to, float), axis, x, math.pi)], arm.read_q(), SWING_STRADDLE_ANG)
    if plan is None:
        return False
    arm.tare()
    try:
        peak, k, why = _swing_go(arm, plan, speed, arm.cmd - arm.read_q(), limit, stall=None)
    finally:
        arm.tare(False)
    return not why


def _door_rise(arm, door):
    """Straight up to the door's top, as the tool is: home from low by the leaf, the joint move swept a jaw through it."""
    tip, axis = arm.tip_pose()
    top = door.top if door.top is not None else door.bar_top + SWING_TOUCH_ABOVE
    for z in np.arange(top, float(tip[2]), -0.01):
        if _door_line(arm, np.r_[tip[:2], z], axis):
            return


def _door_transit(arm, door, q_to):
    """To q_to over the door, not through it: straight up from where the tool is to well above the door's top, a joint
    move across at that height to above q_to's tip with its tool direction and roll, and straight down to it. A joint
    move between a low level pose and a high steep one swept the jaws or the camera through the leaf, and shut it.
    Nothing if q_to is where the tool is, and as high as reaches if the clear height doesn't."""
    tip, axis = arm.tip_pose()
    to, to_axis = arm.ik.fk(q_to)
    if np.linalg.norm(to - tip) < 0.01:
        return
    top = door.top if door.top is not None else door.bar_top + SWING_TOUCH_ABOVE
    for z in np.arange(max(top + SWING_CLEAR_ABOVE, float(tip[2]), float(to[2])), float(to[2]) - 1e-6, -0.01):
        q_over, ok_over, _, ang_over = _solve_rolled(arm, np.r_[to[:2], z], to_axis, np.asarray(q_to, float), iters=80)
        if ok_over and ang_over < SWING_STRADDLE_ANG and _door_line(arm, np.r_[tip[:2], z], axis):
            break
    else:
        return
    arm.tare()
    skills.move_joints(arm, q_over + (arm.cmd - arm.read_q()))
    arm.tare(False)
    _door_line(arm, to, to_axis)


def swing(arm, parts, i, step):
    """Swing a door on a vertical hinge to params.angle (deg from shut) by its handle, with the stock gripper's jaws:
    gripping the bar to unlatch it, astride the leaf's top edge for the rest of the way, and pushing the bar for the last
    of a close. PASS: the door's reading changed, as it must when the door leaves shut or reaches it. FAIL: the door held
    against the force limit (a seized hinge, a jammed latch), or it reached shut, or left it, and nothing read so.
    OBSERVED: moved between two open angles, which nothing reads. MISSED: the jaws never got hold of it."""
    p, params = parts[i], step.get("params", {})
    result = {"skill": "swing", "target": p.id, "verdict": "REFUSED", "channel": None, "readout_change": {}}
    to_deg = float(params.get("angle", p.meta.get("open_deg", 90.0) - 5.0))
    why = _swing_check(arm, p, to_deg)
    now, to = p.meta.get("angle", 0.0), math.radians(to_deg)
    if why is None and abs(to - now) < math.radians(SWING_SHUT_DEG):
        why = f"{p.id} is already at {to_deg:g} deg"
    if why:
        result["reason"] = why
        return result
    limit = float(params.get("force_limit", SWING_FORCE_N))
    # the estimate's own floor on top (low and near level it reads 4-5 N on nothing, D32), under the hard cap
    sensed = min(limit + (arm.noise_n if arm.sensing else 0.0), HARD_FORCE_CAP_N - SWING_CAP_MARGIN_N)
    door = _Door(p)
    grip = math.radians(SWING_GRIP_DEG)
    legs = []   # (how, from, to)
    if to > now:
        if now < grip:
            legs.append(("grip", now, min(to, grip)))
        if to > grip:
            legs.append(("straddle", max(now, grip), to))
    else:
        if now > grip:
            legs.append(("straddle", now, max(to, grip)))
        if to < grip:
            legs.append(("push", min(now, grip), to))
    app, t0, log0 = arm.app, arm.d.time, len(arm.force_log)
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    arm.status = f"swing {p.id}"
    reached, stop, peak, notes = now, "end", 0.0, []
    try:
        for how, a, b in legs:
            if how == "grip":
                got = _swing_grip(arm, door, a, b, sensed)
            elif how == "straddle":
                got = _swing_straddle(arm, door, a, b, sensed)
            else:
                got = _swing_push(arm, door, a, b, sensed)
            peak = max(peak, got.get("peak", 0.0))
            reached = got.get("reached", reached)
            notes.append(got["note"])
            if got["status"] != "end":
                stop = got["status"]
                break
        _door_rise(arm, door)
        skills.go_home(arm)
    except SafetyStop as e:
        result.update(verdict="ABORTED", reason=f"safety stop: {e}", readout_change=_changes(app, before, n_events))
        try:
            arm.grip(JAW_SHUT, 0.3)
            arm.tare(False)
            skills.go_home(arm)
        except SafetyStop:
            pass
        result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
        arm.status = "idle"
        return result
    for _ in range(int(SETTLE_S * CONTROL_HZ)):
        arm.send(arm.cmd)
        arm.tick()
    seq = _changes(app, before, n_events)
    moved = [c for c in seq if app.readings.get(c) != before.get(c)]
    shut_end = min(abs(now), abs(reached)) < math.radians(SWING_SHUT_DEG)   # it left shut or got there: a door sensor's change
    reached_deg = max(0.0, math.degrees(reached))
    result.update(peak_force_n=round(peak, 2), force_limit_n=limit, stop={"end": "end", "force": "force_limit"}.get(stop, stop),
                  readout_change=seq, reached_deg=round(reached_deg, 1), how="; ".join(notes))
    if stop == "missed":
        result.update(verdict="MISSED", reason=f"{notes[-1]}, so the door wasn't tested")
    elif stop == "force":
        result.update(verdict="FAIL", reason=f"{p.id} held at {reached_deg:.0f} deg of the {to_deg:g} asked: {notes[-1]}",
                      channel=moved[0] if moved else None)
    elif moved:
        result.update(verdict="PASS", channel=moved[0], reason=f"{p.id} swung to {to_deg:g} deg: {moved[0]} {' -> '.join(map(str, seq[moved[0]]))}")
    elif _has_reading_for(arm, p) and shut_end:
        result.update(verdict="FAIL", reason=f"the arm swung {p.id} to {to_deg:g} deg and no reading changed")
    else:
        result.update(verdict="OBSERVED", reason=f"the arm carried {p.id} to {to_deg:g} deg, peak {peak:.1f} N. Nothing reads it between open angles")
    went = to if result["verdict"] in ("PASS", "OBSERVED") else reached
    if abs(went - now) > math.radians(SWING_SHUT_DEG):   # a later leg MISSED: where the earlier ones left it
        th, k, H = went - now, door.k, door.H
        T = p.T.copy()
        T[:3, 3] = H + _rotate(p.pos - H, k, th)
        T[:3, :3] = np.c_[_rotate(p.T[:3, 0], k, th), _rotate(p.T[:3, 1], k, th), _rotate(p.T[:3, 2], k, th)]
        parts[i] = replace(p, T=T, state=went, range=(-went, math.radians(p.meta["open_deg"]) - went),
                           meta={**p.meta, "angle": went, "pull": _rotate(p.meta["pull"], k, th), "under": _rotate(p.meta["under"], k, th)})
    result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions), force_trace=arm.force_log[log0:])
    arm.status = "idle"
    return result


def _swing_grip(arm, door, a, b, limit):
    """The jaws round the bar, shut on it, and draw it from a to b round the arc; then let go and back off."""
    ths = _door_arc(a, b)
    for tilt in SWING_GRIP_TILTS:
        poses = _door_grip_poses(arm, door, ths, tilt)
        plan = _swing_plan(arm, [_door_backed(poses[0])] + poses, arm.cmd)
        if plan is not None:
            break
    else:
        return {"status": "missed", "note": "the handle's bar is out of reach for the jaws"}
    arm.grip(_jaw_open(2 * door.r_bar), 0.5)
    bias = _settle(arm, plan[0][0])   # the first leg, from home: in front of the door, nothing to go round
    arm.tare()
    a_in = poses[0][1]
    peak, went = _line(arm, poses[0][0], a_in, SWING_IN_SPEED, limit=PLACE_FORCE_N + getattr(arm, "noise_n", 0.0), bias=bias)
    if not went:
        arm.tare(False)
        _line(arm, plan[0][1], a_in, SWING_SPEED, bias=bias)
        arm.grip(JAW_SHUT, 0.3)
        return {"status": "missed", "peak": peak, "note": f"going in round the handle's bar the jaws met {peak:.1f} N"}
    _close_on(arm, bias)
    for _ in range(int(0.3 * CONTROL_HZ)):
        arm.send(arm.cmd)
        arm.tick()
    # zeroed with the jaws shut on the bar: the squeeze twists the wrist, and the estimate read that couple as 4-6 N of
    # pull before any was made (and 10 N once the door was free). What it zeroes with it, the 2 N or so the squeeze
    # pushes the arm back by, only makes the pull read that much low
    arm.tare()
    if not (arm.jaw() > JAW_EMPTY or arm.jaw_load() > JAW_LOAD):
        arm.grip(_jaw_open(2 * door.r_bar), 0.3)
        arm.tare(False)
        _line(arm, plan[0][1], a_in, SWING_SPEED, bias=bias)
        arm.grip(JAW_SHUT, 0.3)
        return {"status": "missed", "note": f"the jaws shut on nothing at the handle's bar ({math.degrees(arm.jaw()):.1f} deg)"}
    # from wherever the squeeze left the tip, with the bar between the jaws
    held = arm.ik.fk(arm.read_q())[0] - poses[0][0]
    bias[:] = arm.cmd - arm.read_q()
    sweep = _swing_plan(arm, _door_grip_poses(arm, door, ths, tilt, held), arm.read_q()) or [(q, t, th) for q, t, th in plan if th >= a][-len(ths):]
    peak2, k, why = _swing_go(arm, sweep, SWING_SPEED, bias, limit, stall=SWING_GRIP_STALL_M, follow=False, dwell=SWING_DWELL_S)
    if not why:   # the door free past the latch, let the arm catch up with its last pose: it trailed it by its own sag
        for _ in range(int(SWING_CATCH_S * CONTROL_HZ)):
            arm.send(sweep[-1][0] + bias)
            arm.tick()
            bias += SAG_FOLLOW * (sweep[-1][0] - arm.read_q())
    reached = sweep[k][2] + door.turn(sweep[k][1], arm.ik.fk(arm.read_q())[0])   # where the bar is, not where it was sent
    arm.grip(_jaw_open(2 * door.r_bar) + SWING_LET_GO, 0.4)   # wide: the moving jaw is on the side away from the leaf
    arm.tare()   # let go, nothing held: zeroed again here (with the zero dropped, the hard cap read 50 N on nothing)
    tip, ax = arm.tip_pose()
    _line(arm, tip - SWING_OUT * ax, ax, SWING_SPEED, bias=bias)
    arm.grip(JAW_SHUT, 0.3)
    if why:
        return {"status": "force", "peak": max(peak, peak2), "reached": reached,
                "note": f"the jaws on the bar, drawing it round, {why} at {math.degrees(reached):.0f} deg"}
    return {"status": "end", "peak": max(peak, peak2), "reached": reached,
            "note": f"jaws on the bar from {math.degrees(a):.0f} to {math.degrees(b):.0f} deg, tool {tilt} deg down"}


def _swing_straddle(arm, door, a, b, limit):
    """Astride the leaf's top edge, from a to b. The jaws, open wide, come down on either side of the leaf from above
    the handle until the leaf's top meets the gripper between them (its height needn't be known: the gap is what lands
    on it, so a few mm off still comes down square), back off SWING_STRADDLE_BACK and sweep, the jaw behind the leaf
    pushing it."""
    ths = _door_arc(a, b)
    x_c = (2 * JAW_FACE_X + JAW_GAP[0] + JAW_GAP[1] * SWING_STRADDLE_OPEN) / 2   # the gap's middle, out along x from the tip
    hi = door.top + SWING_LIFT if door.top is not None else door.bar_top + SWING_TOUCH_ABOVE
    for tilt in SWING_TOP_TILTS:
        down = _swing_plan(arm, _door_top_poses(arm, door, [a, a], hi, tilt, x_c)[:1] + _door_top_poses(arm, door, [a], door.bar_top, tilt, x_c),
                           arm.cmd, SWING_STRADDLE_ANG)
        if down and _swing_plan(arm, _door_top_poses(arm, door, ths, hi, tilt, x_c), down[0][0], SWING_STRADDLE_ANG):
            break
    else:
        return {"status": "missed", "note": "the leaf's top edge is out of reach along the arc"}
    arm.grip(SWING_STRADDLE_OPEN, 0.4)
    _door_transit(arm, door, down[0][0])
    bias = _settle(arm, down[0][0])
    arm.tare()
    # the bias held as it is coming down: following the readings, it wound up the push on the leaf's top, and the sweep
    # after dragged on it with that (19 mm of command under the tip)
    peak, k, why = _swing_go(arm, down, SWING_TOUCH_SPEED, bias, SWING_TOUCH_N + getattr(arm, "noise_n", 0.0), stall=None, follow=False)
    if not why:
        arm.tare(False)
        _line(arm, down[0][1], _tool_axis(arm, down[0][1], math.radians(tilt)), SWING_IN_SPEED * 2, bias=bias)
        arm.grip(JAW_SHUT, 0.3)
        return {"status": "missed", "peak": peak, "note": "coming down astride the leaf, it wasn't there down to the handle's top"}
    z = float(arm.ik.fk(arm.read_q())[0][2]) + SWING_STRADDLE_BACK   # where the leaf's top met the gripper, backed off
    door.top = z + SWING_JAW_LEN                                     # about: for going round the door after
    arm.tare(False)
    half = (JAW_GAP[0] + JAW_GAP[1] * SWING_STRADDLE_OPEN - SWING_LEAF_T) / 2 - SWING_STRADDLE_SLACK
    # swept with the jaw that pushes (behind the leaf, going its way) on the leaf's face, not the gap's middle: the leaf
    # is left where it was sent, not up to half the gap short of it
    plan = _swing_plan(arm, _door_top_poses(arm, door, [a], z, tilt, x_c) + _door_top_poses(arm, door, ths, z, tilt, x_c, half if b > a else -half),
                       arm.read_q(), SWING_STRADDLE_ANG)
    if not plan:
        _line(arm, arm.tip_pose()[0] + np.array([0, 0, SWING_LIFT]), _tool_axis(arm, arm.tip_pose()[0], math.radians(tilt)), SWING_IN_SPEED * 2, bias=bias)
        arm.grip(JAW_SHUT, 0.3)
        return {"status": "missed", "peak": peak, "note": "astride the leaf's top edge is out of reach along the arc"}
    for _ in range(int(SETTLE_S * CONTROL_HZ)):   # off the leaf's top, onto the sweep's first pose
        arm.send(plan[0][0] + bias)
        arm.tick()
    arm.tare()
    peak2, k, why = _swing_go(arm, plan, SWING_SPEED, bias, limit)
    reached = plan[k][2]
    arm.tare(False)
    _line(arm, arm.tip_pose()[0] + np.array([0, 0, SWING_LIFT]), _tool_axis(arm, plan[k][1], math.radians(tilt)), SWING_IN_SPEED * 2, bias=bias)
    arm.grip(JAW_SHUT, 0.3)
    if why:
        return {"status": "force", "peak": max(peak, peak2), "reached": reached,
                "note": f"astride the leaf, {why} at {math.degrees(reached):.0f} deg"}
    return {"status": "end", "peak": max(peak, peak2), "reached": reached,
            "note": f"astride the leaf's top edge from {math.degrees(a):.0f} to {math.degrees(b):.0f} deg, tool {tilt} deg down"}


def _swing_push(arm, door, a, b, limit):
    """The shut fingertip on the bar's front, pushing it from a round to b and on past shut by SWING_PAST_DEG, so a
    latch catches: the door's stop ends it, and meeting the force limit within SWING_SHUT_DEG of shut is that stop."""
    end = b - math.radians(SWING_PAST_DEG) if b < math.radians(SWING_SHUT_DEG) else b
    ths = _door_arc(a, end)
    for tilt in SWING_GRIP_TILTS:
        poses = []
        for th in ths:
            bb = door.bar(th)
            ax = _tool_axis(arm, bb, math.radians(tilt))
            poses.append((bb - (door.r_bar - 0.001) * ax, ax, None, th))
        plan = _swing_plan(arm, [_door_backed(poses[0])] + poses, arm.cmd)
        if plan is not None:
            break
    else:
        return {"status": "missed", "note": "the handle's bar is out of reach to push it shut"}
    _door_transit(arm, door, plan[0][0])
    bias = _settle(arm, plan[0][0])
    arm.tare()
    peak, k, why = _swing_go(arm, plan, SWING_SPEED, bias, limit)
    reached = plan[k][2]
    for _ in range(int(0.5 * CONTROL_HZ)):   # held there while a latch takes it
        arm.send(arm.cmd)
        arm.tick()
    arm.tare(False)
    _line(arm, arm.tip_pose()[0] - SWING_OUT * poses[0][1], poses[0][1], SWING_SPEED, bias=bias)
    if why and reached > math.radians(SWING_SHUT_DEG):
        return {"status": "force", "peak": peak, "reached": reached, "note": f"pushing the bar shut, {why} at {math.degrees(reached):.0f} deg"}
    return {"status": "end", "peak": peak, "reached": max(0.0, min(reached, b)) if not why else 0.0,
            "note": f"pushed the bar from {math.degrees(a):.0f} deg to shut, tool {tilt} deg down"}
