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


def _follow(arm, poses, speed, bias, limit, what, follow=False):
    """Move through (tip, axis) poses at speed, watching the force. Returns (peak force, whether it got to the end, why
    not): a soft limit here just records the force, since a part may simply be heavy; the arm's own hard cap still stops
    it. A path whose IK jumps to another branch (a joint more than BRANCH_RAD in one tick) ends there: sent anyway, the
    incubator's closing hook_pull swung the elbow 124 deg at full speed, and the servo estimate read that as 28 N."""
    q, peak = arm.cmd - bias, 0.0
    for (p0, a0), (p1, a1) in zip(poses[:-1], poses[1:]):
        steps = max(1, int(np.linalg.norm(p1 - p0) / speed * CONTROL_HZ))
        for i in range(1, steps + 1):
            f = i / steps
            a = a0 + (a1 - a0) * f
            q1 = arm.ik.solve(p0 + (p1 - p0) * f, a / np.linalg.norm(a), q, iters=30)[0]
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
        _, bias = affordances._approach(arm, entry[0], entry[1], f"hook_pull {p.id}")
        if jaw and arm.sensing:
            # low and near level, the estimate reads 4-5 N with nothing touching (D32): over the noise, not at the bare limit
            limit = params.get("force_limit", FORCE_LIMIT["hook_pull"] + arm.noise_n)
        peak, ok1, why1 = _follow(arm, [entry, poses[0]], HOOK_SPEED, bias, limit, "in", follow=jaw)
        peak2, ok2, why2 = (0.0, False, None)
        if ok1:
            peak2, ok2, why2 = _follow(arm, poses, HOOK_SPEED, bias, limit, "swing", follow=jaw)
        peak3, _, _ = _follow(arm, [(arm.ik.fk(arm.cmd - bias)[0], poses[-1][1]), *leave], HOOK_SPEED, bias, 2 * limit, "out")
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
