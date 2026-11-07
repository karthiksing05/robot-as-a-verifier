"""Part-level skills: guarded motions and readout-backed verdicts from features.Part records, no CAD.

    steps = plan_tests(parts)              # buttons left to right, toggle, slider, dial, door last
    results = run_plan(arm, parts, steps)  # on_step(step, None) before each step, on_step(step, result) after
    r = run_step(arm, parts, {"skill": "turn", "target": "dial_1", "params": {"angle": 60}})
    qs = preview(arm, part, step, parts)   # joint vectors at approach, contact and end, for ghost arms
    run_plan(arm, parts, steps, refine=lambda arm, p: perceive.refine(arm, wrist, p))

Step params: force_limit (N; 6 for press and push_latch, 5 for sideways pushes), slide "to" (0..1 along
the part's +x, its state convention), turn "angle" (degrees about the part's axis, right-handed).

Each skill is a rule in the part frame (GAPartNet style). press and push_latch push along -normal until
a force limit or 4 mm past first contact. slide, turn and flip lower the pad beside the moving part and
push it sideways (along the slot, around the dial's axis, across the lever), watching the force on the
pad. Before a slide or turn the pad touches the surface it will move over and stands off from where it
really is, as the arm's own height error is several times the clearance. A turn that moved nothing tries
once more further out or in along the fin, as the arm's error along it can leave the pad too near the
axis (the push stalls) or past the fin's end (it slips off).

Verdicts compare arm.app.readings and arm.app.events before and after, so a PASS also names the readout
channel the part drives. FAIL means the part was really pushed and nothing registered; a step that could
not test the part (the pad missed it, slipped off it, or the arm gave way), or whose reading changed more
than the push can explain, is MISSED. When a reading changed and the step isn't MISSED, run_step moves the
target in `parts` to where the step left it (knob position, fin angle, lever side, door latch), so later
steps find it without looking again.

Real servos sag under gravity and give under load (SimArm(slop=True)). Each approach pose is commanded
again until the joint readings land on it, and the command-minus-reading left then is added to every
command until the next approach. Under load the command still runs ahead of the tip, so contact, travel
and depth are read from the joints (arm.tip_pose()), never from the command. With refine, each step
calls refine(arm, part) once at its approach pose and plans the rest of the step from the part it returns:
the wrist camera and the probe share the gripper, so that removes most of the arm's calibration error.

With servo sensing (SimArm(sensing="current"), no force sensor) every guarded motion tares the estimate, goes by it
only once moving, and keeps its thresholds above arm.noise_n; verdicts still rest on the readout. With a pad or load
cell on the probe (arm.axial_sensor) the force along the probe counts from the start, and descents go by it alone; the
force across the probe is still the servos'.
"""
import math
from dataclasses import dataclass, replace

import numpy as np

import skills
from features import canonical_x, frame
from rig import CONTACT_N, CONTROL_HZ, SafetyStop

PAD_R, PAD_T = 0.006, 0.003       # probe pad; the tip site is the centre of its face, and the rod ends inside it
HOVER = 0.03            # a sideways push starts this far above the pad's first position
GAP = 0.004             # pad to face before a sideways push
CLEAR = 0.002           # the pad's lowest point above the surface it moves over
PUSH_SPEED = 0.01       # m/s, sideways
TOUCH_SPEED = 0.004     # m/s, descending near the parts: landing on a rigid part at 20 mm/s peaked at 17 N
TOUCH_BAND = 0.004      # a touch this close to where the floor should be is the floor
END_ZONE, END_SPEED = 0.004, 0.003  # creep through the last 4 mm of a push, so an end stop isn't hit hard
PRESS_TRAVEL = 0.004    # a press stops on force or this far past first contact: no CAD travel
LANDED_N = 1.0          # force on the pad that ends a descent
LOW_N = 2.0             # mid-push, a force off the panel above this and above the resistance: the pad is too low
SIDE_BAND = 0.004       # first sideways contact further than this from the face probably wasn't the part
RETRY = 0.004           # after landing on a part, start this much further back
INSET = 0.003           # turn: push the fin this far in from its end
FLIP_PAST = math.radians(10)  # push a lever this far past centre; its snap does the rest
TURN_TOL = math.radians(2)    # a turn may end this far past where the part thinks its stop is
SETTLE_S = 1.0          # after a latch push, time for the door to pop
LATCH_RETREAT = 0.01    # m/s off a door pad: slow enough that the popping door rides out on the pad
SAG_TOL = 0.0003        # an approach pose is commanded again until the joint readings put the tip this close
SAG_HOLD_S = 0.3        # after commanding an approach pose again, time for the servos to settle on it
LEAD_MAX = 0.04         # a guarded motion gives up when its command runs this far ahead of the pad (servo give)
# Joint readings off a guarded path by more than HOLD_FREE are fed back into the command, HOLD_GAIN of the error per
# tick. Under that, a stiff arm's sub-mm yield to a part pushed off-centre is left alone.
HOLD_GAIN, HOLD_FREE = 0.2, 0.001
HOLD_MAX = 0.01         # and the correction stops growing at this
BLOCKED = ("force_limit", "max_lead")  # stops where the pad couldn't go on
UNWIND_SPEED = 0.2      # m/s: after a sideways push the command first comes back to the pad this fast,
UNWIND_STEP = 0.03      # and no joint further than this per tick (rad)
RELEASE = 0.002         # then the pad moves this far the way the contact pushes it,
RELEASE_SPEED = 0.03    # this fast (m/s), like the lift: at 20 mm/s a lever held 5 deg off its rest sprang back onto
                        # it (6.4 N); at 50 mm/s, one tick's 2 mm step swung a stiff arm's pad into a fin's edge (24 N)
GIVE = 2e-4             # m per N per tick: while letting go and lifting, the pad gives way to whatever pushes it
JUMP = 0.0002           # with servo sensing, a pad that closes this much of its command's lead in a tick was let go
SLIP = 0.004            # a push that ran on this far with nothing against it slipped off the part
FLIP_BAND = 0.002       # a lever leans, so first contact further than this off its face means the push was off height
REGRIP = 0.005          # a turn that moved nothing tries once more with the dial taken to be this far along the fin
FORCE_LIMIT = {"press": 6.0, "push_latch": 6.0, "slide": 5.0, "turn": 5.0, "flip": 5.0}
SKILL_FOR = {"button": "press", "slider": "slide", "dial": "turn", "knob": "turn", "toggle": "flip",
             "door": "push_latch"}
NEEDS = {"slider": ("travel", "knob_len", "side_height", "slot_ends", "track_len"),
         "dial": ("fin_length", "fin_width", "fin_height"), "toggle": ("lever_len", "lever_radius", "tip"),
         "door": ("latched",)}


# --- probe geometry ---

def _lowest(a, n):
    """How far the pad's rim reaches below its tip, toward a surface facing n, when the probe points along a."""
    return PAD_R * math.sin(math.acos(float(np.clip(-a @ n, -1, 1))))


def _rim(a, m):
    """Offset from the tip to the pad's rim point furthest along m, halfway through its thickness."""
    mp = m - (m @ a) * a
    return -PAD_T / 2 * a + PAD_R * mp / np.linalg.norm(mp)


def _rotate(v, k, th):
    """v rotated about unit axis k by th (Rodrigues)."""
    return v * math.cos(th) + np.cross(k, v) * math.sin(th) + k * (k @ v) * (1 - math.cos(th))


# --- motion with sagging servos ---

def _approach(arm, pos, axis, label):
    """Move the tip to pos, pointing along axis, then command the pose again by however far the joint readings
    fell short, until they are within SAG_TOL of it: gravity sags STS3215 servos about 10 mm at the tip, one
    round leaves about 1.2 mm (friction), two about 0.25. Returns the pose and the bias, command minus
    reading, that holds the arm on poses near it."""
    arm.status = f"{label}: approach"
    q, *_ = arm.ik.solve(pos, axis, arm.cmd)
    skills.move_joints(arm, q)
    for _ in range(3):
        if np.linalg.norm(arm.ik.fk(q)[0] - arm.tip_pose()[0]) < SAG_TOL:
            break
        skills.move_joints(arm, arm.cmd + q - arm.read_q())
        for _ in range(int(SAG_HOLD_S * CONTROL_HZ)):
            arm.send(arm.cmd)
            arm.tick()
    return q, arm.cmd - arm.read_q()


def _line(arm, p_to, axis, speed, bias, give=False):
    """skills.move_line with the approach's bias added to every command. With give, the rest of the line also
    shifts GIVE per newton each tick the way the contact force pushes the pad (never along axis, toward the
    panel), so a part caught against the pad pushes it clear instead of being pried."""
    q, off = arm.cmd - bias, np.zeros(3)
    p_from, _ = arm.ik.fk(q)
    n = max(1, int(np.linalg.norm(p_to - p_from) / speed * CONTROL_HZ))
    for i in range(1, n + 1):
        q = _toward(arm, arm.ik.solve(p_from + (p_to - p_from) * i / n + off, axis, q, iters=30)[0], bias)
        arm.send(q + bias)
        arm.tick()
        if give:
            F = arm.tip_force_vec()
            if np.linalg.norm(F) > arm.noise_n:  # under the sensor's noise it isn't a push
                off += GIVE * (F - max(F @ axis, 0.0) * axis)


def _toward(arm, q, bias):
    """q, or the step to it scaled down whole so that no joint moves more than UNWIND_STEP: robot.send clips each joint
    alone, and that bends the motion (a slop18 arm's command swung 107 mm off its line)."""
    dq = q + bias - arm.cmd
    big = np.max(np.abs(dq))
    return q if big <= UNWIND_STEP else arm.cmd - bias + dq * UNWIND_STEP / big


def _unwind(arm, bias):
    """Bring the command back to the joint readings (plus bias) along a straight line in joint space. A line of the
    tip asked one joint for more than robot.send allows per tick while the others took their full steps, which swung
    a slop18 arm's command 107 mm off the line and loaded a jammed slider to 11.9 N."""
    q0, q1 = arm.cmd.copy(), arm.read_q() + bias
    lead = np.linalg.norm(arm.ik.fk(q0 - bias)[0] - arm.tip_pose()[0])
    k = max(1, math.ceil(lead / UNWIND_SPEED * CONTROL_HZ), math.ceil(np.max(np.abs(q1 - q0)) / UNWIND_STEP))
    for i in range(1, k + 1):
        arm.send(q0 + (q1 - q0) * i / k)
        arm.tick()


# --- sideways pushes ---

@dataclass
class _Push:
    path: object        # (s, s at first contact or None) -> (tip, unit push direction); contact expected at s = gap
    length: float
    until: float        # stop this far past first contact
    n: np.ndarray
    qs: list            # IK at hover, start and end, for preview
    slow: float         # the descent creeps from this far above the start: the tallest part near it, plus 10 mm
    gap: float = GAP
    touch: float = None   # how far below the start the pad should meet the floor; None: don't feel for it
    radius: float = None  # arcs: radius of the contact point, so travel / radius is the angle turned
    what: str = "part"    # what the pad pushes, for verdicts: "knob", "fin" or "lever"
    centre: float = 0.0   # a lever's centre, this far past contact: it can't go over before


def _obstacles(p, parts, datum):
    """The other parts as (position on the plane through p's origin, footprint radius, top above the datum,
    id); datum is the height above the panel that the plan measures from."""
    n = p.normal
    return [(o.pos - ((o.pos - p.pos) @ n) * n, max(o.size[0], o.size[1]) / 2, o.size[2] - datum, o.id)
            for o in parts if o.id != p.id]


def _sideways(arm, face, n, m, floor, contact_h, top, until, what, touch_floor=None, centre=None, k=None,
              obstacles=()):
    """Plan a sideways push of `what`. The pad's leading rim meets `face` moving along m, at height contact_h,
    with its lowest point CLEAR above floor; top is the part's top and touch_floor the surface under the pad at
    the start (heights along n, from face). The path is a line along m, or for an arc about the axis through
    centre along k, a line along m until the pad touches and then the arc through that point. It starts GAP
    before contact, or 1 mm if another part is in the way. Returns a _Push, or why it can't be done."""
    rc = None if centre is None else float(np.linalg.norm(np.cross(face - centre, k)))

    def place(a, drop):
        r = _rim(a, m)
        return face - (r @ m) * m + max(floor + CLEAR + drop, contact_h - r @ n) * n

    def path_from(tip, gap):
        def path(s, c):
            if centre is None or c is None or s < c:
                return tip + (s - gap) * m, m
            # the arc goes through where the pad touched: the arm's own error along m moves its centre too
            th = (s - c) / rc
            return centre + (c - gap) * m + _rotate(tip - centre, k, th), _rotate(m, k, th)
        return path

    def near(pt, c, r, margin):
        d = pt - c
        return np.linalg.norm(d - (d @ n) * n) < PAD_R + r + margin

    for gap in (GAP, 0.001):
        ends = (0.0, gap + until / 2, gap + until)
        tip, q = place(-n, _lowest(-n, n)), arm.cmd
        for _ in range(2):  # the arm can't always point the probe along -n; the tilt lowers one side of the pad
            axes = []
            for s in ends:
                q, *_ = arm.ik.solve(path_from(tip, gap)(s, gap)[0], -n, q)
                axes.append(arm.ik.fk(q)[1])
            tip = place(axes[0], max(_lowest(a, n) for a in axes))
        path = path_from(tip, gap)
        h = (path(0, gap)[0] - face) @ n
        low = h - max(_lowest(a, n) for a in axes)  # the pad's lowest point along the push
        hit = [oid for c, r, ot, oid in obstacles if ot > low and any(near(path(s, gap)[0], c, r, 0.001) for s in ends)]
        if not hit:
            break
    else:
        return f"no room for the pad: {hit[0]} is in the way"
    top = max([top] + [ot for c, r, ot, _ in obstacles if near(path(0, gap)[0], c, r, 0.005)])
    qs, q = [], arm.cmd
    for pt in (path(0, gap)[0] + HOVER * n, *(path(s, gap)[0] for s in ends)):
        q, ok, err, _ = arm.ik.solve(pt, -n, q)
        if not ok:
            return f"out of reach: best IK is {err * 1000:.1f} mm off"
        try:
            arm.check_workspace(pt)
        except SafetyStop as e:
            return str(e)
        qs.append(q)
    touch = None if touch_floor is None else h - _lowest(axes[0], n) - touch_floor
    # a pad that touches up to twice SIDE_BAND late (the arm's own error) still gets its full travel; the descent
    # creeps through a press's 10 mm slow zone above the tallest part, as the arm's height error can be most of it
    return _Push(path, gap + 2 * SIDE_BAND + until, until, n, [qs[0], qs[1], qs[3]],
                 skills.SLOW_ZONE_M + max(top - h, 0.0), gap, touch, rc, what)


def _slide_plan(arm, p, to, parts):
    n, x = p.normal, p.x
    m = x * math.copysign(1, to - p.state)
    floor = 2 * p.meta["side_height"] - p.size[2]  # the knob's underside, on the rails
    face = p.pos - p.size[2] * n - m * p.meta["knob_len"] / 2  # the trailing face, at the panel
    until = abs(to - p.state) * p.meta["travel"] + (0.002 if to in (0, 1) else 0.0)  # to an end: on into the stop
    # the pad touches the rails if it starts right over the track; else expect the panel, which if it was
    # the rails after all only stands the pad 1.5 mm higher
    off = abs((face - (PAD_R + GAP) * m) @ x - np.mean(p.meta["slot_ends"], axis=0) @ x)
    touch = floor if off + PAD_R < p.meta["track_len"] / 2 else 0.0
    return _sideways(arm, face, n, m, floor, (floor + p.size[2]) / 2, p.size[2], until, "knob", touch,
                     obstacles=_obstacles(p, parts, 0.0))


def _turn_plan(arm, p, angle, parts, ends=(1, -1)):
    """Push the fin near one end along an arc about the dial's axis; whichever end the arm reaches better."""
    n, x, y = p.normal, p.x, p.T[:3, 1]
    fl, fw, fh = (p.meta[k] for k in ("fin_length", "fin_width", "fin_height"))
    s, plans = math.copysign(1, angle), []
    for e in ends:
        m = s * e * y  # the way this end of the fin moves
        face = p.pos + e * (fl / 2 - INSET) * x - m * fw / 2
        plans.append(_sideways(arm, face, n, m, 0.0, fh / 2, fh, abs(angle) * math.hypot(fl / 2 - INSET, fw / 2),
                               "fin", touch_floor=0.0, centre=p.pos, k=s * n,
                               obstacles=_obstacles(p, parts, p.size[2] - fh)))
    ok = [pl for pl in plans if not isinstance(pl, str)]
    return min(ok, key=lambda pl: _tilt(arm, pl)) if ok else plans[0]


def _tilt(arm, plan):
    return max(math.acos(float(np.clip(-arm.ik.fk(q)[1] @ plan.n, -1, 1))) for q in plan.qs[1:])


def _flip_plan(arm, p, parts):
    """Push the lever across, 3/4 of the way up, from the side it leans to."""
    n, x = p.normal, p.x
    v, r = p.meta["tip"] - p.pos, p.meta["lever_radius"]
    lean = math.atan2(v @ x, v @ n)
    h = 0.75 * p.meta["lever_len"] * math.cos(lean) - r * math.sin(lean)  # the lever's +x side, 3/4 of the way up
    side = lambda tilt: h * math.tan(tilt) + r / math.cos(tilt)  # where that side is at height h
    plan = _sideways(arm, p.pos + side(lean) * x, n, -x, 0.0, h, v @ n + r, side(lean) - side(-FLIP_PAST), "lever",
                     obstacles=_obstacles(p, parts, p.size[2] - v @ n - r))
    return plan if isinstance(plan, str) else replace(plan, centre=side(lean) - side(0.0))


def _guarded(arm, path, length, n, limit, speed, bias, until=None, expect=None, track=False, centre=0.0):
    """Push the pad along path(s, contact) -> (tip, direction) for s in [0, length], IK every tick, slowing as
    the force against the motion nears limit and through the last END_ZONE before `until`. Stops at limit
    (force_limit); at twice limit in all or, given `until` (a push, not a descent), at limit across the motion
    (side_force: pressed on a part's side or end); when something below pushes the pad off (LOW_N, and more
    than it resists the motion: a rounded edge pushes up a little too); `until` past first contact; at the
    end; or when the command has run LEAD_MAX ahead of the pad. Force is arm.tip_force_vec(), the 3D contact
    force on the probe. "held" is how far along the pad was when something last pushed back. When the part lets
    go, the command is put back on the pad.

    Soft servos give under load, so "at", the pad's progress along the path, comes from the joint readings,
    and the command leads it by however far the commanded progress s has run ahead, along the path's
    direction there (on an arc, a point further round would pull the pad off it). Errors across the path
    over HOLD_FREE are fed back into the command, up to HOLD_MAX, as a sideways load pushes soft servos down and
    along too. With servo sensing a light part can push back less than the estimate's floor, so once the pad is past
    `expect`, where contact should come, the push goes on as if the part was met there ("met"). With track (a slider's
    knob, whose reading follows it), a reading that first moves further on says where the part was really met. With
    servo sensing, a part can't let go before the pad is `centre` past where it was met (a lever's centre)."""
    q, s, at, f, hold, freed, lead = arm.cmd - bias, 0.0, 0.0, 0.0, np.zeros(3), -1.0, 0.0
    g = {"stop": None, "contact": None, "held": None, "peak": 0.0, "trace": [], "ats": [], "reads": []}
    # with servo sensing the force is ignored until a second tare once moving (skills.TARE_AFTER_S), and checks allow
    # for its noise, which along the probe (too_low) is up to 3 times arm.noise_axial
    contact_n, low_n, side_n = max(CONTACT_N, arm.noise_n), max(LOW_N, 3 * arm.noise_axial), limit + arm.noise_n
    arm.tare()
    ticks, armed, moved = 0, not arm.sensing, None

    def met():
        c = g["contact"]
        if arm.sensing and expect is not None and at >= expect and (c is None or c > expect):
            return expect if moved is None else max(expect, moved)
        return c
    while g["stop"] is None:
        v = speed * float(np.clip(1 - f / limit, 0.15, 1))
        if until is not None and met() is not None and at - met() > until - END_ZONE:
            v = min(v, END_SPEED)
        s += v / CONTROL_HZ
        tip, m = path(at, met())
        q = _toward(arm, arm.ik.solve(tip + (s - at) * m + hold, -n, q, iters=30)[0], bias)  # a reset jumps the target
        arm.send(q + bias)
        arm.tick()
        now, a = arm.tip_pose()
        at += (now - tip) @ m
        tip, m = path(at, met())
        e = tip - now - ((tip - now) @ m) * m
        ticks += 1
        if not armed and ticks >= round(skills.TARE_AFTER_S * CONTROL_HZ):
            arm.tare()
            armed = True
        F = Fm = arm.tip_force_vec() if armed else np.zeros(3)  # Fm: what the force limit and too_low go by
        if arm.axial_sensor:
            # a sensor on the probe reads the force along it from the first tick, with no servo noise: until the tare it
            # is all there is, and a descent (no until: moving along the probe) goes by it alone, as with the probe tilted
            # off -n the servo estimate's noise across the probe leaked into the landing check
            F = F if armed else -arm.tip_force() * a
            Fm = -arm.tip_force() * a if until is None else F
        if np.linalg.norm(e) > HOLD_FREE:
            hold += HOLD_GAIN * e
            hold *= min(1.0, HOLD_MAX / np.linalg.norm(hold))
        was, f = f, float(-Fm @ m)  # resistance: the part of the force that opposes the motion
        led, lead = lead, float(np.linalg.norm((s - at) * m + hold + e))  # how far the command is from the pad
        g["trace"].append((arm.d.time, f))
        if arm.sensing:
            g["ats"].append(at)
            g["reads"].append(dict(arm.app.readings))
            if track and moved is None and g["reads"][-1] != g["reads"][0]:
                moved = g["ats"][-2]
        g["peak"] = max(g["peak"], f)
        # with servo sensing a lever's push-back (2-3 N) is about the estimate's floor and eases off as it nears centre,
        # so both let-go checks below fired before it went over: with the command put back on the pad, the lever pushed
        # the pad back 1-5 mm and never went over. So they wait until the pad is past where the lever's centre should be
        early = centre > 0 and arm.sensing and met() is not None and at - met() < centre
        if f > contact_n:
            g["held"] = at
            if g["contact"] is None:
                g["contact"] = at
        elif was > contact_n and until is not None and lead > HOLD_FREE and at - freed > HOLD_FREE and not early:
            # the part let go (a lever snapped over, or the pad slipped off): a soft arm's command leads the pad by
            # mm, and following it launched the pad 2 mm on into a lever at its stop (9 N). So the command comes back
            # onto the pad, across the path too: a correction for a pad held up by a fin's end, kept, dropped it onto
            # the panel (16.9 N). Only once per mm of progress, as a fin's stick-slip let go every 0.2 s without end.
            s, freed, hold, lead = at, at, -e, 0.0
        if arm.sensing and met() is not None and until is not None and led - lead > JUMP and at - freed > HOLD_FREE \
                and not early:
            # the servo estimate lags and reads the arm's own acceleration as force, the joints don't: the pad catching
            # up with its command means the part let go
            s, freed, hold, lead = at, at, -e, 0.0
        if f >= limit:
            g["stop"] = "force_limit"
        elif np.linalg.norm(F) >= limit + side_n or (until is not None and np.linalg.norm(F + f * m) >= side_n):
            g["stop"] = "side_force"
        elif Fm @ n >= max(low_n, f):
            g["stop"] = "too_low"
        elif until is not None and met() is not None and at - met() >= until:
            g["stop"] = "travel"
        elif at >= length:
            g["stop"] = "end"
        elif s - at >= LEAD_MAX:
            g["stop"] = "max_lead"
    g["s"], g["at"], g["F"], g["met"] = s, at, F, met()
    return g


def _descend(arm, start, n, slow, touch, bias):
    """Lower the pad onto start from HOVER above: fast down to `slow` above it, then creeping. With touch
    (how far below start the pad should meet the floor), creep on until it does. Returns (dz, None, peak),
    dz being how far above start the push should run, or (None, why, peak) if it landed on something."""
    top = start + HOVER * n
    landed = max(LANDED_N, 2 * arm.noise_axial)
    g = _guarded(arm, lambda s, c: (top - s * n, -n), max(HOVER - slow, 0.0), n, landed, skills.APPROACH_SPEED, bias)
    if g["stop"] == "end":
        s0 = g["s"]
        deep = HOVER + (0.0 if touch is None else touch + TOUCH_BAND)
        # creeping, a servo estimate with nothing touching reads less than moving fast (2.8 N at most, against 4): at
        # landed (5 N), pads rested for seconds on a knob's edge reading 2-3 N, then slid off it at up to 25 N
        g = _guarded(arm, lambda s, c: (top - (s0 + s) * n, -n), deep - s0, n, max(LANDED_N, 1.5 * arm.noise_axial),
                     TOUCH_SPEED, bias)
        g["at"] += s0
    z = g["at"] - HOVER  # how far below start the pad stopped
    dz = 0.0
    if g["stop"] in ("force_limit", "side_force"):
        if touch is None or abs(z - touch) > TOUCH_BAND:
            return None, f"pad landed on something {-z * 1000:.1f} mm above the push's start height", g["peak"]
        dz = touch - z  # the floor is dz higher than the part said
        if arm.sensing:
            _unwind(arm, bias)  # a late landing left the command mm into the floor
    _line(arm, start + dz * n, -n, TOUCH_SPEED, bias)
    arm.tare(False)  # with servo sensing, the zero is dropped only once the pad is clear (see _poke)
    return dz, None, g["peak"]


def _push(arm, plan, limit, label):
    """Hover, descend (guarded, feeling for the floor), push along the plan, let go, lift."""
    n = plan.n
    for s0 in (0.0, -RETRY):
        start = plan.path(s0, None)[0]
        _, bias = _approach(arm, start + HOVER * n, -n, label)
        arm.status = f"{label}: descend"
        dz, why, peak = _descend(arm, start, n, plan.slow, plan.touch, bias)
        if why is None:
            break
        _line(arm, start + HOVER * n, -n, 0.03, bias)  # landed on something: back up, start further back
        arm.tare(False)
    else:
        return {"stop": "landed", "peak": 0.0, "landing": peak, "travel": 0.0, "contact_offset_mm": None, "trace": [],
                "missed": why}

    def path(s, c):
        tip, m = plan.path(s0 + s, None if c is None else s0 + c)
        return tip + dz * n, m

    arm.status = f"{label}: push"
    # with the pad or load cell, where a slider's reading starts to move marks where the pad met its knob: with one knob
    # scanned 20 mm off, the push measured from where it should have been and ran out 4 mm into it (current mode is left
    # as it was measured)
    g = _guarded(arm, path, plan.length - s0, n, limit, PUSH_SPEED, bias, plan.until, plan.gap - s0,
                 plan.what == "knob" and arm.axial_sensor, plan.centre)
    arm.status = f"{label}: lift"
    # First the command comes back to where the joints say the pad is: a soft arm's command runs ahead of the pad
    # and would carry it on (a slop18 arm carried a lever 8 mm on and over centre). It goes in steps (_unwind), as
    # jumping back in one tick swung the joints through other poses (15 N on a lever), and it drops the push's
    # correction across the path, as keeping that let a pad fall onto the dial (18 N) once the fin let go. Then
    # it lets go, moving level the way the contact pushes the pad and quickly, so a dial left on top of a detent
    # can't follow the pad and get dragged back. Then a line backs off to its start, as a lever that didn't flip
    # leans over the pad; an arc lifts straight off, as a chord back would cut across the dial. All of it gives
    # way to the part: a tilted pad caught on a fin's end wedges if it rises before it is clear (15 N on one dial).
    F, now = g["F"], arm.tip_pose()[0]
    u = F - (F @ n) * n
    contact_n = max(CONTACT_N, arm.noise_n)  # as _guarded's
    u = u / np.linalg.norm(u) if np.linalg.norm(u) > contact_n else -path(g["at"], g["met"])[1]
    _unwind(arm, bias)
    _line(arm, now + RELEASE * u, -n, RELEASE_SPEED, bias, give=True)
    arm.tare(False)
    if plan.radius is None:
        _line(arm, path(0, None)[0], -n, 0.03, bias, give=True)
    _line(arm, arm.ik.fk(arm.cmd - bias)[0] + HOVER * n, -n, 0.03, bias, give=True)
    c, w = g["contact"], plan.what
    off = None if c is None else (c + s0 - plan.gap) * 1000
    f, prev = g["trace"][-1][1], (g["trace"][-2][1] if len(g["trace"]) > 1 else 0.0)  # at the stop, a tick before
    missed = None
    if c is None:
        missed = "no contact: the pad pushed through where the part should be"
    elif g["stop"] == "too_low":
        missed = (f"something pushed the pad off the panel side ({max(LOW_N, 3 * arm.noise_axial):g} N): it is touching the "
                  "panel or riding the part")
    elif abs(off) > SIDE_BAND * 1000:
        missed = f"first contact {off:+.1f} mm from where the part's face should be, so probably not the part"
    elif g["stop"] == "max_lead":
        missed = f"the arm gave way: its command ran {LEAD_MAX * 1000:.0f} mm ahead of the pad at {f:.1f} N"
    elif g["stop"] == "side_force":
        missed = (f"much of the force was across the push ({np.linalg.norm(g['F']):.1f} N in all, {f:.1f} N "
                  f"against it): the probe pressed on the {w}'s side, end or corner")
    elif g["stop"] == "force_limit" and prev < limit / 2:
        missed = f"a jolt ({f:.1f} N for one tick, from {prev:.1f} N) stopped the push before the {w} was pushed hard"
    elif g["at"] - g["held"] > SLIP:
        missed = f"the pad ran on {(g['at'] - g['held']) * 1000:.1f} mm with nothing against it: it slipped off the {w}"
    elif w == "lever" and g["stop"] != "force_limit":  # one that went over snaps away from the pad and switches
        missed = (f"the lever still pushed back ({f:.1f} N) when the push ran out, so it never went over centre"
                  if f > contact_n else "the force let go before the push ended: the pad slipped off the lever (or it "
                  "went over and its switch is dead; force and travel can't tell which)")
    elif w == "lever" and abs(off) > FLIP_BAND * 1000:
        missed = (f"the pad met the lever {off:+.1f} mm from where its face should be; as the lever leans, the push "
                  f"was well off its planned height, so being held at {f:.1f} N there doesn't show the lever is stuck")
    travel = 0.0 if g["met"] is None else g["at"] - g["met"]
    if g["met"] != c and w == "knob":
        # servo sensing: a light knob can push back less than the estimate's floor, so the push was measured from where
        # it should have been met. The readout starts changing once the knob moves, so measure from there
        k = next((k for k, r in enumerate(g["reads"]) if r != g["reads"][0]), 0)
        travel = g["at"] - g["ats"][k - 1] if k else travel
    return {"stop": g["stop"], "peak": g["peak"], "landing": peak, "travel": travel,
            "turned": None if plan.radius is None else travel / plan.radius,
            "contact_offset_mm": None if off is None else round(off, 1), "trace": g["trace"], "missed": missed,
            "touch_mm": round(dz * 1000, 1)}


def _pushed(g):
    return f"pushed {g['travel'] * 1000:.1f} mm past contact (peak {g['peak']:.1f} N, stopped by {g['stop']})"


def _turn(arm, p, plan, params, parts, label):
    """Push the fin. If that moved no reading without being a fair test, the arm's error along the fin probably
    put the pad too near the axis to beat a detent (it stalled: force_limit or max_lead) or past the fin's end
    (it slipped off, rode or pressed on the end, or never touched), so try once more with the dial taken to be
    REGRIP further out or in along the fin. If that moves no reading either, the step is MISSED. If it does, the
    dial is believed to be where that try took it, as the first try's stall or slip says which way the pad was
    off: on 8 runs tried both ways, return turns planned from the shifted dial first touched the fin 0.3 to 5.1 mm
    from plan, from the unshifted one 2.5 to 6.2 mm or not at all (2). Returns the push and the part and plan used."""
    before = dict(arm.app.readings)
    g = _push(arm, plan, params["force_limit"], label)
    if arm.app.readings != before or g["stop"] == "landed" or not (g["missed"] or g["stop"] in BLOCKED):
        return g, p, plan
    e = math.copysign(1, (plan.path(0, None)[0] - p.pos) @ p.x)  # the end of the fin it pushed
    out = REGRIP if g["stop"] in BLOCKED else -REGRIP
    T = p.T.copy()
    T[:3, 3] += out * e * p.x
    q = replace(p, T=T, origin=None if p.origin is None else p.origin + out * e * p.x)
    again = _turn_plan(arm, q, math.radians(params["angle"]), parts, (e,))
    if isinstance(again, str):
        g["missed"] = g["missed"] or (f"it {_pushed(g)}, and a try {REGRIP * 1000:.0f} mm further "
                                      f"{'out' if out > 0 else 'in'} along the fin is not possible: {again}")
        return g, p, plan
    g2 = _push(arm, again, params["force_limit"], label)
    g2.update(peak=max(g["peak"], g2["peak"]), landing=max(g["landing"], g2["landing"]), trace=g["trace"] + g2["trace"],
              regrip_mm=out * 1000)
    if arm.app.readings == before:
        g2["missed"] = (f"neither try moved a reading. First, {g['missed'] or _pushed(g)}. Then, "
                        f"{REGRIP * 1000:.0f} mm further {'out' if out > 0 else 'in'} along the fin, "
                        f"{g2['missed'] or _pushed(g2)}")
    return g2, (q if arm.app.readings != before else p), again


# --- pushes along the normal ---

def _aim(p):
    """Where a push along -normal aims. A door's push pad sits near the flap's free edge, so the probe aims as
    far toward the hinge as keeps it on the pad: landing a few mm toward the edge puts its rim on the panel
    across the seam, which stops the door going in."""
    return p.pos - max(p.meta.get("pad_radius", PAD_R) - PAD_R, 0.0) * p.x if p.kind == "door" else p.pos


def _poke(arm, p, limit, label, settle=0.0, retreat=0.03):
    """skills.py's guarded push along -normal, with no CAD travel and the approach's bias on every command:
    from 30 mm out, creep in until limit or PRESS_TRAVEL past first contact, retreat, then wait `settle`
    seconds."""
    n, aim = p.normal, _aim(p)
    pre = aim + skills.APPROACH_M * n
    q, bias = _approach(arm, pre, -n, label)
    arm.status = f"{label}: guarded push"
    arm.tare()  # does nothing with the perfect sensor
    depth, contact, peak, stop, travel, creep, seen = 0.0, None, 0.0, None, 0.0, 0, []
    armed = not arm.sensing or arm.axial_sensor  # a sensor on the probe needs no tare, so it counts from the start
    contact_n = max(CONTACT_N, arm.noise_axial)  # tip_force() is along the probe
    deepest = skills.APPROACH_M + PRESS_TRAVEL + 0.006
    while stop is None:
        f = arm.tip_force() if armed else 0.0
        fast = contact is None and depth < skills.APPROACH_M - skills.SLOW_ZONE_M
        v = skills.APPROACH_SPEED if fast else skills.CONTACT_SPEED * float(np.clip(1 - f / limit, 0.15, 1))
        depth += v / CONTROL_HZ
        q, *_ = arm.ik.solve(pre - depth * n, -n, q, iters=30)
        arm.send(q + bias)
        f = arm.tick()
        if not armed:
            f = 0.0  # until the creep's tare, only the hard cap (in tick) goes by the reading
        peak = max(peak, f)
        tip, _ = arm.tip_pose()
        seen.append((f, tip))
        if contact is None and f > contact_n:
            # with servo sensing alone, where the estimate last sat near zero, as in _guarded
            servo = arm.sensing and not arm.axial_sensor
            contact = next((t for f0, t in reversed(seen) if f0 <= contact_n / 4), tip) if servo else tip
        travel = 0.0 if contact is None else float((contact - tip) @ n)
        if f >= limit:
            stop = "force_limit"
        elif travel >= PRESS_TRAVEL:
            stop = "travel"
        elif depth > deepest + (0.0 if contact is None else LEAD_MAX):
            stop = "no_contact" if contact is None else "max_depth"
        creep += not fast
        if creep == 1:
            crept = (tip, depth)
        if creep == round(skills.TARE_AFTER_S * CONTROL_HZ):
            if arm.sensing and stop is None and contact is None and (crept[0] - tip) @ n < (depth - crept[1]) / 2:
                contact, stop = tip, "held"  # as skills._guarded_push
            arm.tare()
            armed = True
    arm.status = f"{label}: retreat"
    _line(arm, pre, -n, retreat, bias)
    arm.tare(False)  # only once clear: dropped while pressing, the zero's friction and hidden force read as 16 N
    for _ in range(int(settle * CONTROL_HZ)):
        arm.send(arm.cmd)
        arm.tick()
    off = None if contact is None else round(float((contact - aim) @ n) * 1000, 1)
    lo, hi = skills.CONTACT_OFFSET_OK_MM
    missed = None
    if off is None:
        missed = "no contact: nothing where the part should be"
    elif not lo <= off <= hi:
        missed = f"first contact {off:+.1f} mm off the part's surface, so the probe hit something else"
    elif stop == "max_depth":
        missed = f"the arm gave way: its command ran {LEAD_MAX * 1000:.0f} mm past the push at {f:.1f} N"
    return {"stop": stop, "peak": peak, "travel": travel, "contact_offset_mm": off, "missed": missed}


# --- validation, verdicts, belief ---

def _never(p):
    """Why no skill may touch this part, or None. Displays are just read."""
    if p.grip == "pinch":
        return f"{p.id} needs a pinch grip; the no-thumbs rule allows only the fingertip pad"
    if p.kind not in SKILL_FOR and p.kind != "display":
        return f"{p.id} ({p.kind}): no skill is known for this kind of part, so it is not touched"
    return None


def _check(arm, p, step, parts=()):
    """(why refused or None, params, plan) before anything moves; plan is a _Push for sideways skills.
    parts, if given, are obstacles for sideways pushes."""
    skill = step.get("skill")
    if p is None:
        return f"unknown target '{step.get('target')}'", None, None
    why = _never(p) or (f"{p.id} is a {p.kind}: nothing to actuate" if p.kind not in SKILL_FOR else None)
    if why:
        return why, None, None
    if skill != SKILL_FOR[p.kind]:
        return f"{skill} can't actuate a {p.kind} (it takes {SKILL_FOR[p.kind]})", None, None
    missing = [k for k in NEEDS.get(p.kind, ()) if k not in p.meta]
    if missing:
        return f"{p.id} has no {', '.join(missing)} in its meta", None, None
    params = {"force_limit": FORCE_LIMIT[skill], **step.get("params", {})}
    if not all(isinstance(v, (int, float)) for v in params.values()):
        return f"params must be numbers, got {params}", None, None
    if not 0 < params["force_limit"] <= skills.MAX_FORCE_LIMIT_N:
        return f"force_limit must be between 0 and {skills.MAX_FORCE_LIMIT_N:g} N", None, None
    plan = None
    if skill == "slide":
        to = params.get("to")
        if to is None or not 0 <= to <= 1:
            return "slide needs params.to, a position between 0 and 1", None, None
        if abs(to - p.state) * p.meta["travel"] < 0.001:
            return f"{p.id} is already at {p.state:.2f}", None, None
        plan = _slide_plan(arm, p, to, parts)
    elif skill == "turn":
        a, (lo, hi) = math.radians(params.get("angle", 0)), p.range
        if a == 0:
            return "turn needs params.angle, in degrees", None, None
        if (lo, hi) != (0, 0) and not lo - TURN_TOL <= a <= hi + TURN_TOL:
            return (f"turning {params['angle']:+g} deg would pass a stop (room: {math.degrees(lo):+.0f} to "
                    f"{math.degrees(hi):+.0f} deg)"), None, None
        plan = _turn_plan(arm, p, a, parts)
    elif skill == "flip":
        plan = _flip_plan(arm, p, parts)
    else:
        if skill == "push_latch" and not p.meta["latched"]:
            return f"{p.id} is already open", None, None
        q = arm.cmd
        for pt in (_aim(p) + skills.APPROACH_M * p.normal, _aim(p) - PRESS_TRAVEL * p.normal):
            q, ok, err, _ = arm.ik.solve(pt, -p.normal, q)
            if not ok:
                return f"{p.id} is out of reach: best IK is {err * 1000:.1f} mm off", None, None
    if isinstance(plan, str):
        return f"{p.id}: {plan}", None, None
    return None, params, plan


def _refine(arm, p, plan, refine, label, result):
    """refine(arm, p) from the step's approach pose (30 mm out from a press, over a sideways push's start);
    notes in result whether it found the part and how far it moved it."""
    if plan is None:
        _approach(arm, _aim(p) + skills.APPROACH_M * p.normal, -p.normal, label)
    else:
        _approach(arm, plan.path(0, None)[0] + HOVER * plan.n, -plan.n, label)
    arm.status = f"{label}: refine"
    p = refine(arm, p)
    result.update(refined=bool(p.meta.get("refined")), refine_shift_mm=round(p.meta.get("refine_shift", 0.0) * 1000, 2))
    if p.meta.get("refine_why"):
        result["refine_why"] = p.meta["refine_why"]
    return p


def _changes(app, before, n_events):
    """({channel: [value before, then each logged value, or the value now]}, channels that logged events)."""
    seq = {}
    for _, ch, v in app.events[n_events:]:
        seq.setdefault(ch, [before.get(ch)]).append(v)
    logged = list(seq)
    for ch, v in app.readings.items():
        if ch not in seq and v != before.get(ch):
            seq[ch] = [before.get(ch), v]
    return seq, logged


def _judge(skill, p, params, g, app, before, seq, logged, known):
    """(verdict, reason, channel). PASS needs the change a skill should cause: an event for a press, a
    reading that moved for the others (the same way as last time for a slider or dial)."""
    hits = logged if skill == "press" else [ch for ch in seq if app.readings.get(ch) != before.get(ch)]
    if g["stop"] == "landed":  # it never pushed: a reading that moved was nudged by the descent
        return "MISSED", g["missed"], None
    if not hits:
        if g["missed"]:
            return "MISSED", g["missed"], None
        if skill == "push_latch":
            return "FAIL", f"door stayed shut after a {g['peak']:.1f} N push", None
        return "FAIL", f"{_pushed(g)} but no reading changed", None
    ch = hits[0]
    was, now, went = before.get(ch), app.readings.get(ch), " -> ".join(map(str, seq[ch]))
    if skill == "press":
        found = f"{p.id} drives {ch}"
    elif skill in ("slide", "turn"):
        step = p.meta.get("detent_step") if skill == "turn" else None
        if step and isinstance(was, int):  # a detent only goes over once the dial is turned half a step; its snap
            need = step / 2  # can carry it over the next ones (a 61 deg push went three), so only the first counts
            if (g.get("turned") or 0.0) < need / 2:
                return "MISSED", (f"{ch} changed ({went}), but the pad turned {p.id} "
                                  f"{math.degrees(g.get('turned') or 0.0):.1f} deg, far short of the "
                                  f"{math.degrees(need):.0f} deg that takes: something else turned it (the pad "
                                  f"slipping off the fin?), so which way it went is unknown"), None
        cmd = math.copysign(1, params["to"] - p.state if skill == "slide" else params["angle"])
        first = seq[ch][1]  # the way the push moved it: a dial can slip back a detent as the pad lets go
        sign = math.copysign(1, first - was) * cmd
        how = "raises" if first > was else "lowers"
        found = (f"pushing {p.id} toward {'+' if cmd > 0 else '-'}x {how} {ch}" if skill == "slide"
                 else f"turning {p.id} {params['angle']:+g} deg {how} {ch}")
        if known is not None:
            if known.get(p.id, (ch, sign)) != (ch, sign):
                return "FAIL", f"{found} ({went}), the opposite of what it did before", ch
            known[p.id] = (ch, sign)
        if (now - was) * (first - was) < 0:
            return "FAIL", f"{found} ({went}), but it ended up back past where it started", ch
        if skill == "slide" and g["stop"] in BLOCKED:
            short = abs(params["to"] - p.state) * p.meta["travel"] - g["travel"]
            if short > 0.003:
                found += f", but it was blocked at {g['peak']:.1f} N {short * 1000:.0f} mm short"
    elif skill == "flip":
        found = f"{p.id} switches {ch}"
    else:
        found = f"{p.id} opened ({ch})"
    extra = [c for c in seq if c != ch]
    return "PASS", f"{found} ({went})" + (f"; also changed: {', '.join(extra)}" if extra else ""), ch


def _moved(p, skill, params, g, plan, counted=None):
    """The part where this step left it, as the robot believes from its own motion. Called only when a reading
    changed: without one, the pad's travel says nothing about where the part went. counted: how many steps a
    counting reading moved the way the push went (negative if it ended up the other way), if one moved."""
    if skill == "slide":
        tr, f0 = p.meta["travel"], p.state
        f = f0 + math.copysign(g["travel"], params["to"] - f0) / tr
        if g["stop"] in BLOCKED and params["to"] in (0, 1) and abs(f - params["to"]) * tr < 0.003:
            f = params["to"]  # pushed into the end stop; further short, something else stopped it
        f = float(np.clip(f, 0, 1))
        T = p.T.copy()
        T[:3, 3] += (f - f0) * tr * p.x
        return replace(p, T=T, origin=T[:3, 3].copy(), state=f, range=(-f * tr, (1 - f) * tr))
    if skill == "turn":
        th, step = math.copysign(g["travel"] / plan.radius, params["angle"]), p.meta.get("detent_step")
        if step:  # the detent settles it; a reading that counts detents says how many better than the pad's travel
            th = math.copysign(step, params["angle"]) * counted if counted is not None else round(th / step) * step
        k = p.axis / np.linalg.norm(p.axis)
        rng = p.range if tuple(p.range) == (0, 0) else (p.range[0] - th, p.range[1] - th)
        return replace(p, T=frame(p.pos, p.normal, canonical_x(_rotate(p.x, k, th), p.normal)), range=rng,
                       meta={**p.meta, "angle": p.meta.get("angle", 0.0) + th})
    if skill == "flip":
        v = p.meta["tip"] - p.pos
        meta = {**p.meta, "tip": p.meta["tip"] - 2 * (v @ p.x) * p.x, "angle": -p.meta.get("angle", 0.0),
                "on": not p.meta.get("on", True)}
        return replace(p, T=frame(p.pos, p.normal, -p.x), axis=-p.axis, meta=meta)
    if skill == "push_latch":
        return replace(p, meta={**p.meta, "latched": False})
    return p


# --- public API ---

def run_step(arm, parts, step, known=None, refine=None):
    """Validate, act, judge. Returns a result dict like skills.run_step's (verdict, reason, peak_force_n,
    travel_mm, stop, contact_offset_mm, duration_s, collisions, force_trace) plus channel, readout_change
    ({channel: [before, ..., after]}) and lcd; never raises on a failed test. force_trace is (t, N): the
    load cell's axial force for press and push_latch, the force against the motion for sideways pushes, and
    peak_force_n is its largest value; a sideways push also has landing_n, the peak of the descent's touch.
    PASS: the expected reading changed. FAIL: the part was pushed through its motion (or held at the force
    limit) and no reading changed, or a reading went the wrong way. MISSED: the step could not test the part
    (it never touched it, slipped off, or the arm could not deliver the push), or a reading changed that the
    push can't account for. If a reading changed and the verdict isn't MISSED, updates the target in `parts`.
    `known` ({part id: (channel, sign)}) makes a slider or dial that moves its reading the other way from an
    earlier step FAIL; run_plan keeps one. refine(arm, part) -> part, if given, runs once at the approach pose
    and its part is used for the rest of the step; the result then has refined (whether it found the part),
    refine_shift_mm and, if it failed, refine_why. A turn that moved nothing
    and tried again has regrip_mm, how far out (+) or in it took the dial to be."""
    skill, target = step.get("skill"), step.get("target")
    result = {"skill": skill, "target": target, "verdict": "REFUSED", "channel": None, "readout_change": {}}
    i = next((i for i, p in enumerate(parts) if p.id == target), None)
    p = None if i is None else parts[i]
    why, params, plan = _check(arm, p, step, parts)
    if why:
        result["reason"] = why
        return result
    app = arm.app
    before, n_events = dict(app.readings), len(app.events)
    arm.seen_collisions = set()
    t0, log0 = arm.d.time, len(arm.force_log)
    label = f"{skill} {target}"
    trace = []
    try:
        if refine:
            p = _refine(arm, p, plan, refine, label, result)
            why, params, plan = _check(arm, p, step, parts)
        if why:
            result["reason"] = f"after refine: {why}"
        else:
            if skill in ("press", "push_latch"):
                g = (_poke(arm, p, params["force_limit"], label) if skill == "press" else
                     _poke(arm, p, params["force_limit"], label, SETTLE_S, LATCH_RETREAT))
                trace = arm.force_log[log0:]
            elif skill == "turn":
                g, p, plan = _turn(arm, p, plan, params, parts, label)
                trace = g["trace"]
            else:
                g = _push(arm, plan, params["force_limit"], label)
                trace = g["trace"]
            seq, logged = _changes(app, before, n_events)
            verdict, reason, ch = _judge(skill, p, params, g, app, before, seq, logged, known)
            peak = max([g["peak"]] + [f for _, f in trace])  # a popping door loads the probe after the push
            result.update(verdict=verdict, reason=reason, channel=ch, readout_change=seq,
                          peak_force_n=round(float(peak), 2), travel_mm=round(g["travel"] * 1000, 2), stop=g["stop"],
                          contact_offset_mm=g["contact_offset_mm"], force_limit_n=params["force_limit"])
            result.update({k: g[k] for k in ("touch_mm", "regrip_mm") if k in g})
            if "landing" in g:
                result["landing_n"] = round(float(g["landing"]), 2)
            if skill == "turn" and plan.radius:
                result["turned_deg"] = round(math.degrees(g["travel"] / plan.radius), 1)
            # steps a counting reading moved, signed by the way its first change went (the way the push went)
            counted = ((seq[ch][-1] - seq[ch][0]) * math.copysign(1, seq[ch][1] - seq[ch][0])
                       if ch and isinstance(seq[ch][-1], int) else None)
            if app.readings != before and verdict != "MISSED":
                parts[i] = _moved(p, skill, params, g, plan, counted)
    except SafetyStop as e:
        try:
            seq, _ = _changes(app, before, n_events)
        except SafetyStop:  # the readout itself is what stopped (an unplugged Pico): back off without it
            seq = {}
        result.update(verdict="ABORTED", reason=f"safety stop: {e}", readout_change=seq)
        trace = arm.force_log[log0:]
        arm.tare(False)
        try:
            skills.go_home(arm)
        except SafetyStop:
            pass  # the arm has already backed off; leave it there
    result.update(lcd=app.lcd, duration_s=round(arm.d.time - t0, 2), collisions=sorted(arm.seen_collisions),
                  force_trace=trace)
    arm.status = "idle"
    return result


def run_plan(arm, parts, steps, on_step=None, refine=None):
    """Run the steps in order, then go home. on_step(step, None) before each, on_step(step, result) after.
    refine is passed to every run_step."""
    known, results = {}, []
    for step in steps:
        if on_step:
            on_step(step, None)
        results.append(run_step(arm, parts, step, known, refine))
        if on_step:
            on_step(step, results[-1])
    try:
        skills.go_home(arm)
    except SafetyStop:
        pass
    return results


def plan_tests(parts):
    """Steps in the plan format: buttons left to right as the arm sees them, toggle flip and flip back,
    slider to its far end and back to the middle, dial +60 and -60 deg (first toward the side with more
    room), steps for parts no skill may touch (they will be REFUSED; "why" says so), and the door last."""
    def step(skill, p, **params):
        return {"skill": skill, "target": p.id, "params": {"force_limit": FORCE_LIMIT[skill], **params}}

    def of(kind):
        return [p for p in parts if p.kind == kind]

    steps = [step("press", p) for p in sorted(of("button"), key=lambda p: -p.pos[1])]
    for p in of("toggle"):
        steps += [step("flip", p), step("flip", p)]
    for p in of("slider"):
        steps += [step("slide", p, to=float(p.state < 0.5)), step("slide", p, to=0.5)]
    for p in of("dial"):
        a = 60 if tuple(p.range) == (0, 0) or p.range[1] >= -p.range[0] else -60
        steps += [step("turn", p, angle=a), step("turn", p, angle=-a)]
    steps += [{"skill": SKILL_FOR.get(p.kind, "none"), "target": p.id, "params": {}, "why": _never(p)}
              for p in parts if _never(p)]
    steps += [step("push_latch", p) for p in of("door")]
    return steps


def preview(arm, part, step, parts=()):
    """Joint vectors for a step's key poses (approach, contact, end of the push), moving nothing. Empty if
    the step would be refused. Pass parts to plan around the other parts as run_step does. It plans from
    the part as it is now, so for a step that follows another on the same part (flip back, slide back),
    call it from on_step(step, None), after run_step has updated parts."""
    why, params, plan = _check(arm, part, step, parts)
    if why:
        return []
    if plan is not None:
        return plan.qs
    n, a, q, qs = part.normal, _aim(part), arm.cmd, []
    for pt in (a + skills.APPROACH_M * n, a, a - 0.002 * n):
        q, *_ = arm.ik.solve(pt, -n, q)
        qs.append(q)
    return qs
