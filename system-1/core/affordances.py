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
from collections import deque
from dataclasses import dataclass, replace

import numpy as np

import skills
from features import canonical_x, frame
from rig import CONTACT_N, CONTROL_HZ, JAW_PUSH_OPEN, JAW_PUSH_SHUT, STOCK_JAW, STOCK_JAW_OPEN, SafetyStop, TipShape, tip_shape

PAD_R, PAD_T = 0.006, 0.003       # probe pad; the tip site is the centre of its face, and the rod ends inside it
HOVER = 0.03            # a sideways push starts this far above the pad's first position
GAP = 0.004             # pad to face before a sideways push
CLEAR = 0.002           # the pad's lowest point above the surface it moves over
PUSH_SPEED = 0.01       # m/s, sideways
TOUCH_SPEED = 0.004     # m/s, descending near the parts: landing on a rigid part at 20 mm/s peaked at 17 N
TOUCH_BAND = 0.004      # a touch this close to where the floor should be is the floor
END_ZONE, END_SPEED = 0.004, 0.003  # creep through the last 4 mm of a push, so an end stop isn't hit hard
ARC_END_ZONE, ARC_END_SPEED = math.radians(8), 0.001  # and through a turn's last 8 deg, slower: a knob coasts
PRESS_SEARCH_MM = 4.0   # and the stock fingertip tries again this far off each way
PRESS_TRAVEL = 0.004    # a press stops on force or this far past first contact: no CAD travel
LANDED_N = 1.0          # force on the pad that ends a descent
LOW_N = 2.0             # mid-push, a force off the panel above this and above the resistance: the pad is too low
SIDE_BAND = 0.004       # first sideways contact further than this from the face probably wasn't the part
RETRY = 0.004           # after landing on a part, start this much further back
INSET = 0.003           # turn: push the fin this far in from its end, unless the hub is in the way (_clear_of_hub)
HUB_CLEAR = 0.001       # and keep the tip this far off the dial's hub
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
ARC_RELEASE = 0.008     # (off a dial's fin: back along the arc, this far: at 4 mm the lift still dragged the fin 3.5-5 deg on)
RELEASE_SPEED = 0.03    # this fast (m/s), like the lift: at 20 mm/s a lever held 5 deg off its rest sprang back onto
                        # it (6.4 N); at 50 mm/s, one tick's 2 mm step swung a stiff arm's pad into a fin's edge (24 N)
GIVE = 2e-4             # m per N per tick: while letting go and lifting, the pad gives way to whatever pushes it
STALL_S, STALL_FRAC = 0.3, 0.2  # with servo sensing alone, a descent has landed once the pad covered under a fifth of
                                # its command's travel over the last STALL_S: creeping at 4 mm/s, stick-slip alone gave
                                # 35-140% over 0.25 s, and a slowly growing lag is the arm sagging
JUMP = 0.0002           # with servo sensing, a pad that closes this much of its command's lead in a tick was let go
SLIP = 0.004            # a push that ran on this far with nothing against it slipped off the part
FLIP_BAND = 0.002       # a lever leans, so first contact further than this off its face means the push was off height
REGRIP = 0.005          # a turn that moved nothing tries once more with the dial taken to be this far along the fin
# The stock gripper turns a dial as two fingers do: the jaws open either side of the knob, shut on it, and the wrist
# turns them about the dial's axis. The angle comes from the wrist, from the moment the jaws hold the knob, so the arm's
# own position error (several mm at these stretched poses, 20 deg and more of a pushed fin's 9 mm radius) drops out.
JAW_PUSH_NARROW = -0.08           # gripper joint (rad): 9.8 mm between the jaws, for a flip with little room
JAW_SLACK = 0.006                 # a flip with the jaws pushes on this much further than the plan's travel
JAW_FACE_X = 0.003                # the stock tip (the fixed jaw's end) to its inner face, along the tip frame's x
PINCH_OPEN = 0.12                 # gripper joint (rad) going down round the knob: 25 mm between the jaws' tips
PINCH_DEPTH = 0.006               # the jaws' tips this far below the knob's top, where they are wide enough to find it
PINCH_LOCATE_OPEN = 0.2           # and finding its axis along the fin: 31 mm
PINCH_RAD_S = math.radians(20)    # turning speed
PINCH_EMPTY = 0.0015              # shut to under the knob's width less this: they missed it, or hold it by an edge, which slips
PINCH_RETRY = 0.005               # a pinch that shut on nothing tries again this far either way along the jaws
PINCH_SLID = 0.001                # shutting, the jaws pushed this far along themselves: the knob was under one's edge
PINCH_SWEEP = math.radians(10)    # room for the jaws is checked every this much of the turn
FORCE_LIMIT = {"press": 6.0, "push_latch": 6.0, "slide": 5.0, "turn": 5.0, "flip": 5.0}
SKILL_FOR = {"button": "press", "slider": "slide", "dial": "turn", "knob": "turn", "toggle": "flip",
             "door": "push_latch"}
NEEDS = {"slider": ("travel", "knob_len", "side_height", "slot_ends", "track_len"),
         "dial": ("fin_length", "fin_width", "fin_height"), "toggle": ("lever_len", "lever_radius", "tip"),
         "door": ("latched",)}


# --- probe geometry ---

def _frames(a, rolls=8):
    """Tip rotations pointing along a, at `rolls` wrist rolls: for a tip shape that isn't round, with the roll unknown."""
    z = -np.asarray(a, float) / np.linalg.norm(a)
    x = np.cross([0, 1.0, 0], z) if abs(z[1]) < 0.9 else np.cross([1.0, 0, 0], z)
    x /= np.linalg.norm(x)
    return [np.column_stack([_rotate(x, z, t), np.cross(z, _rotate(x, z, t)), z]) for t in np.linspace(0, math.pi, rolls, endpoint=False)]


def _lowest(a, n, R=None, shape=None):
    """How far the tip reaches below its site, toward a surface facing n, pointing along a (with R, the tip's rotation,
    for a tip that isn't round; without it, the worst roll)."""
    if shape is None or shape.round:
        return PAD_R * math.sin(math.acos(float(np.clip(-a @ n, -1, 1))))
    return max(float(np.max(-(shape.world(r) @ n))) for r in ([R] if R is not None else _frames(a)))


def _rim(a, m, R=None, shape=None, n=None, below=math.inf):
    """Offset from the tip to its point furthest along m: the round pad's rim, halfway through its thickness; for another
    shape, the middle of its leading points among those at most `below` above the site along n (a wedge-shaped finger
    widens further back, so what meets a part depends on how tall the part is)."""
    if shape is None or shape.round:
        mp = m - (m @ a) * a
        return -PAD_T / 2 * a + PAD_R * mp / np.linalg.norm(mp)
    w = shape.world(R)
    if n is not None:
        w = w[w @ n <= below + 1e-6]
    v = w @ m
    return w[v >= v.max() - 0.0005].mean(axis=0)


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
    axis: tuple = None    # arcs: (a point on the part's axis, its unit direction), to measure the angle swept
    roll: float = None    # the wrist roll the plan was made with, for a tip that isn't round (rad)
    jaws: str = None      # the stock gripper opens round the part, and this jaw's inner face pushes: "fixed" or "moving"
    opening: float = JAW_PUSH_OPEN  # the gripper joint, opened (rad)


@dataclass
class _Pinch:
    """A dial turned by the stock gripper's jaws shut on its knob (_pinch_plan)."""
    start: np.ndarray     # the tip site with the jaws round the knob, before they shut
    n: np.ndarray
    axis: np.ndarray      # a point on the dial's axis (the knob's top centre)
    angle: float          # rad, right-handed about n
    roll: float           # the wrist roll going down
    gain: float           # rad of wrist roll per rad about n
    qs: list
    slow: float
    radius: float         # the knob's: travel = angle x radius
    fin: np.ndarray = None  # the fin's direction (the part's x)
    reach: tuple = None   # the knob's extent from its axis along +fin and -fin
    locate: tuple = None  # (wrist roll, tip site, +1 or -1: the jaws' x along the fin) to find the axis along the fin
    what: str = "knob"

    def path(self, s, c):
        return self.start, -self.n


LEVER_DISCS = 4


def _obstacles(p, parts, datum):
    """The other parts as (position on the plane through p's origin, footprint radius, top above the datum,
    id); datum is the height above the panel that the plan measures from."""
    n = p.normal

    def flat(v):
        return v - ((v - p.pos) @ n) * n
    out = []
    for o in parts:
        if o.id == p.id:
            continue
        if o.kind == "toggle" and o.meta.get("base_size") is not None and o.meta.get("tip") is not None:
            # a toggle is a low base and a thin lever, not a column as wide as its base and as tall as its lever: taken
            # as one, the coffee grinder's power switch, 20 mm from its timer dial's axis, left no room to turn the dial
            # (the lever as LEVER_DISCS discs along it, seen from above)
            base, c0, c1 = o.meta["base_size"], flat(o.pos), flat(np.asarray(o.meta["tip"], float))
            r = float(np.linalg.norm(c1 - c0)) / (2 * LEVER_DISCS) + o.meta["lever_radius"]
            out += [(c0, max(base[0], base[1]) / 2, base[2] - datum, o.id)] + \
                   [(c0 + (c1 - c0) * (i + 0.5) / LEVER_DISCS, r, o.size[2] - datum, o.id) for i in range(LEVER_DISCS)]
        else:
            out.append((flat(o.pos), max(o.size[0], o.size[1]) / 2, o.size[2] - datum, o.id))
    return out


def _jaws(arm):
    """The stock gripper, which can open: a sideways push goes with the jaws open round the part, the fixed jaw's flat
    inner face against it. Shut, the gripper is a wedge: on the 45 deg panels its flank met a dial's knob on the top
    edge (most of the force along the dial's axis, turns stopped 13-40 deg into -60) and a lever on its end (pressing it
    into its pivot, 5.7 N and no flip). Open, the inner face meets the fin or lever square on its side."""
    return tip_shape(arm).name == "stock" and hasattr(arm, "grip")


def _moving_jaw(opening):
    """The moving jaw's tip, open to `opening` (rad): STOCK_JAW_OPEN moved out along x by the change in the gap."""
    return TipShape("stock_moving", STOCK_JAW_OPEN.pts + [_jaw_gap(opening) - _jaw_gap(JAW_PUSH_OPEN), 0.0, 0.0])


def _roll_toward(arm, pos, n, m, q0=None):
    """An IK seed at pos pointing along -n whose wrist roll turns the tip frame's x (the fixed jaw's inner face normal,
    toward the moving jaw) as near m as the tool's axis allows, or None if the roll joint can't get there."""
    q, *_ = arm.ik.solve(pos, -n, arm.cmd if q0 is None else q0)
    lo, hi = arm.ik.lo[4], arm.ik.hi[4]
    best = None
    for _ in range(3):
        R = arm.ik.fk_R(q)
        z = R[:, 2]
        want = m - (m @ z) * z
        want /= np.linalg.norm(want)
        th = math.atan2(float(np.cross(R[:, 0], want) @ z), float(R[:, 0] @ want))
        trial = []
        for sgn in (1.0, -1.0):  # which way the roll joint turns x: try both, keep the better
            for wrap in (0.0, 2 * math.pi, -2 * math.pi):
                qt = q.copy()
                qt[4] = q[4] + sgn * th + wrap
                if lo <= qt[4] <= hi:
                    qt, *_ = arm.ik.solve(pos, -n, qt)
                    if lo <= qt[4] <= hi:
                        trial.append((float(arm.ik.fk_R(qt)[:, 0] @ want), qt))
        if not trial:
            break
        dot, q = max(trial, key=lambda t: t[0])
        best = q if dot > 0.95 else None
    return best


def _roll_gain(arm, q, k):
    """Wrist roll (rad) per rad that turns the tip frame about k, at joints q."""
    R0, q1 = arm.ik.fk_R(q), q.copy()
    q1[4] += 0.01
    R1 = arm.ik.fk_R(q1)
    about_z = math.copysign(1.0, float(np.cross(R0[:, 0], R1[:, 0]) @ R0[:, 2]))
    return about_z * math.copysign(1.0, float(R0[:, 2] @ k))


def _sideways(arm, face, n, m, floor, contact_h, top, until, what, touch_floor=None, centre=None, k=None,
              obstacles=(), seed=None, jaw=None, gaps=None, opening=JAW_PUSH_OPEN):
    """Plan a sideways push of `what`. The pad's leading rim meets `face` moving along m, at height contact_h,
    with its lowest point CLEAR above floor; top is the part's top and touch_floor the surface under the pad at
    the start (heights along n, from face). The path is a line along m, or for an arc about the axis through
    centre along k, a line along m until the pad touches and then the arc through that point. It starts GAP
    before contact, or 1 mm if another part is in the way (or each of `gaps`). With the stock gripper's jaws open (jaw:
    "fixed" or "moving", the one whose inner face pushes, with seed's wrist roll turning it to face m), the other jaw
    goes down on the part's far side and counts for room. Returns a _Push, or why it can't be done."""
    rc = None if centre is None else float(np.linalg.norm(np.cross(face - centre, k)))
    jaws = _jaws(arm) and jaw is not None
    moving = _moving_jaw(opening)
    shape = (moving if jaw == "moving" else STOCK_JAW) if jaws else tip_shape(arm)

    def place(R, drop):
        a = -R[:, 2]
        if shape.round:
            r = _rim(a, m)
            return face - (r @ m) * m + max(floor + CLEAR + drop, contact_h - r @ n) * n
        # a wedge: as low as it may go, and what meets the part is its widest section up to the part's top
        h = floor + CLEAR + drop
        r = _rim(a, m, R, shape, n, top - h)
        return face - (r @ m) * m + max(h, contact_h - r @ n) * n

    def path_from(tip, gap):
        def path(s, c):
            if centre is None or c is None or s < c:
                return tip + (s - gap) * m, m
            # the arc goes through where the pad touched: the arm's own error along m moves its centre too
            th = (s - c) / rc
            return centre + (c - gap) * m + _rotate(tip - centre, k, th), _rotate(m, k, th)
        return path

    seed = arm.cmd if seed is None else seed  # IK keeps the seed's wrist roll: a tip that isn't round plans with it
    R0 = arm.ik.fk_R(arm.ik.solve(face + HOVER * n, -n, seed)[0])
    if not shape.round:  # the tip's own footprint at the part's heights, not a circle round its widest point
        wf = shape.world(R0)
        if jaws:  # the other jaw goes down beside the part too
            wf = np.vstack([wf, (STOCK_JAW if jaw == "moving" else moving).world(R0)])
        wz = wf @ n  # each point's height over the tip site
        if not jaws:
            wf, wz = wf[wz <= top + 1e-6], None
        wf = wf - np.outer(wf @ n, n)

    def near(pt, c, r, margin, ot=None):
        d = pt - c
        d = d - (d @ n) * n
        if shape.round:
            return np.linalg.norm(d) < PAD_R + r + margin
        w = wf
        if wz is not None and ot is not None:  # open jaws reach far: only what is below the other part's top counts
            w = wf[(pt - face) @ n + wz < ot + margin]
            if not len(w):
                return False
        return float(np.min(np.linalg.norm(d + w, axis=1))) < r + margin

    for gap in gaps or (GAP, 0.001):
        ends = (0.0, gap + until / 2, gap + until)
        tip, q = place(R0, _lowest(-R0[:, 2], n, R0, shape)), seed
        for _ in range(2):  # the arm can't always point the probe along -n; the tilt lowers one side of the pad
            axes, Rs = [], []
            for s in ends:
                q, *_ = arm.ik.solve(path_from(tip, gap)(s, gap)[0], -n, q)
                Rs.append(arm.ik.fk_R(q))
                axes.append(-Rs[-1][:, 2])
            tip = place(Rs[0], max(_lowest(a, n, R, shape) for a, R in zip(axes, Rs)))
        path = path_from(tip, gap)
        h = (path(0, gap)[0] - face) @ n
        low = h - max(_lowest(a, n, R, shape) for a, R in zip(axes, Rs))  # the pad's lowest point along the push
        hit = [oid for c, r, ot, oid in obstacles if ot > low and any(near(path(s, gap)[0], c, r, 0.001, ot) for s in ends)]
        if not hit:
            break
    else:
        return f"no room for the pad: {hit[0]} is in the way"
    top = max([top] + [ot for c, r, ot, _ in obstacles if near(path(0, gap)[0], c, r, 0.005)])
    qs, q = [], seed
    for pt in (path(0, gap)[0] + HOVER * n, *(path(s, gap)[0] for s in ends)):
        q, ok, err, _ = arm.ik.solve(pt, -n, q)
        if not ok:
            return f"out of reach: best IK is {err * 1000:.1f} mm off"
        try:
            arm.check_workspace(pt)
        except SafetyStop as e:
            return str(e)
        qs.append(q)
    touch = None if touch_floor is None else h - _lowest(axes[0], n, Rs[0], shape) - touch_floor
    # a pad that touches up to twice SIDE_BAND late (the arm's own error) still gets its full travel; the descent
    # creeps through a press's 10 mm slow zone above the tallest part, as the arm's height error can be most of it
    return _Push(path, gap + 2 * SIDE_BAND + until, until, n, [qs[0], qs[1], qs[3]],
                 skills.SLOW_ZONE_M + max(top - h, 0.0), gap, touch, rc, what,
                 axis=None if centre is None else (np.asarray(centre, float), np.asarray(k, float) / np.linalg.norm(k)),
                 roll=None if shape.round else float(seed[4]), jaws=jaw if jaws else None, opening=opening)


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
    """Push the fin near one end along an arc about the dial's axis; whichever end the arm reaches better. A one-sided
    fin (meta one_sided: from the axis out along +x) has only the one end."""
    if _jaws(arm):
        return _pinch_plan(arm, p, angle, parts)
    n, x, y = p.normal, p.x, p.T[:3, 1]
    if p.meta.get("one_sided"):
        ends = (1,)
    fl, fw, fh = (p.meta[k] for k in ("fin_length", "fin_width", "fin_height"))
    s, plans = math.copysign(1, angle), []
    for e in ends:
        m = s * e * y  # the way this end of the fin moves
        # a tip that isn't round fits beside the fin at some wrist rolls and not others: the stock gripper's block is
        # off centre, toward the moving jaw, so pushing one way it always rode the hub until rolled half a turn
        seeds = _roll_seeds(arm)
        for seed in seeds:
            r_push, clear = _clear_of_hub(arm, p, e, m, seed)
            if clear:
                break
        else:
            seed = seeds[0]
            r_push, _ = _clear_of_hub(arm, p, e, m, seed)
        face = p.pos + e * r_push * x - m * fw / 2
        plans.append(_sideways(arm, face, n, m, 0.0, fh / 2, fh, abs(angle) * math.hypot(r_push, fw / 2),
                               "fin", touch_floor=-p.meta.get("floor_gap", 0.0), centre=p.pos, k=s * n,
                               obstacles=_obstacles(p, parts, p.size[2] - fh), seed=seed))
    ok = [pl for pl in plans if not isinstance(pl, str)]
    return min(ok, key=lambda pl: _tilt(arm, pl)) if ok else plans[0]


def _roll_seeds(arm):
    """IK seeds: the arm's own, and for a tip that isn't round the same with the wrist rolled a quarter, half and three
    quarters of a turn (within the joint's range)."""
    if tip_shape(arm).round:
        return [arm.cmd]
    out = []
    for d in (0.0, math.pi, math.pi / 2, -math.pi / 2):
        q = arm.cmd.copy()
        r = q[4] + d
        r = r - 2 * math.pi if r > arm.ik.hi[4] else r + 2 * math.pi if r < arm.ik.lo[4] else r
        if arm.ik.lo[4] <= r <= arm.ik.hi[4]:
            q[4] = r
            out.append(q)
    return out


def _clear_of_hub(arm, p, e, m, seed=None):
    """How far out along the fin (end e) to push it, so that the tip, its leading points on the fin's face, stays
    HUB_CLEAR off the dial's hub: the nearest such point from INSET in from the end outward, while the tip's leading edge
    still overlaps the fin. Pushed 3 mm in from the end, the round pad's rim rode the 5 mm hub (both 11 mm tall) and
    dragged the dial by friction: turns ended anywhere from -64 to -103 deg for -60, or at the hard cap. Where nothing
    clears it, INSET in from the end as before."""
    n, x = p.normal, p.x
    fl, fw, fh = (p.meta[k] for k in ("fin_length", "fin_width", "fin_height"))
    hub = p.meta.get("knob_radius")
    if not hub:
        return fl / 2 - INSET, True
    shape = tip_shape(arm)
    R = arm.ik.fk_R(arm.ik.solve(p.pos + e * (fl / 2) * x + HOVER * n, -n, arm.cmd if seed is None else seed)[0])
    w = shape.world(R)
    w = w[w @ n <= fh + 1e-6]  # what is at the fin's heights, with the tip down at its base
    w = w - np.outer(w @ n, n)
    v = w @ m
    rim = w[v >= v.max() - 0.0005].mean(axis=0)
    lead = w[v >= v.max() - 0.001]
    for r in np.arange(fl / 2 - INSET, fl / 2 + 0.004, 0.00025):
        site = e * r * x - m * fw / 2 - (rim @ m) * m  # relative to the axis, in the dial's plane
        if np.min(np.linalg.norm(site + w, axis=1)) < hub + HUB_CLEAR:
            continue
        if np.min((site + lead) @ (e * x)) > fl / 2:
            break  # its leading edge is past the fin's end
        return float(r), True
    # nowhere clears the hub (a generated dial's fin is short for its hub): push where the plan always did, which may
    # rub the hub, rather than lose a dial the skill could turn before
    return fl / 2 - INSET, False


def _jaw_gap(angle):
    """The gap between the jaws' tips (m) at a gripper joint angle (rad)."""
    import manipulate

    return manipulate.JAW_GAP[0] + manipulate.JAW_GAP[1] * angle


def _pinch_plan(arm, p, angle, parts):
    """The stock gripper's jaws open either side of the knob, across the fin so it lies along them and not between them,
    and the turn's wrist roll within the joint's range; and first, a roll a quarter turn round, the jaws along the fin, to
    find the knob's axis along it (_pinch). Returns a _Pinch, or why it can't be done."""
    n = p.normal
    hub, kh = p.meta.get("knob_radius"), p.meta.get("knob_height", p.size[2])
    if not hub:
        return "no knob for the jaws to hold"
    gap = _jaw_gap(PINCH_OPEN)
    across = np.cross(n, p.x)
    obstacles = _obstacles(p, parts, p.size[2] - kh)
    lo, hi = arm.ik.lo[4], arm.ik.hi[4]
    above = p.pos + (kh + HOVER) * n
    fl = p.meta.get("fin_length", 2 * hub)
    reach = (fl / 2, hub if p.meta.get("one_sided") else fl / 2)  # the knob's extent along +x and -x from its axis
    locate = None
    for xs in (p.x, -p.x):
        q = _roll_toward(arm, above, n, xs)
        if q is not None and (locate is None or abs(q[4] - arm.cmd[4]) < abs(locate[0][4] - arm.cmd[4])):
            locate = (q, float(np.sign(arm.ik.fk_R(q)[:, 0] @ p.x)))
    why = "the wrist can't roll the jaws across the knob"
    for xs in (across, -across):
        seed = _roll_toward(arm, above, n, xs)
        if seed is None:
            continue
        x = arm.ik.fk_R(seed)[:, 0]
        x = x - (x @ n) * n
        x /= np.linalg.norm(x)
        start = p.pos + (kh - PINCH_DEPTH) * n - (JAW_FACE_X + gap / 2) * x  # a dial's origin is its knob's base
        gain = _roll_gain(arm, seed, n)
        if not lo <= seed[4] + gain * angle <= hi:
            why = f"the wrist roll can't turn {math.degrees(angle):+.0f} deg from where the jaws go round the knob"
            continue
        qs, q, bad = [], seed, None
        for th, lift in ((0.0, HOVER), (0.0, 0.0), (angle, 0.0)):
            pt = p.pos + _rotate(start - p.pos, n, th) + lift * n
            q = q.copy()
            q[4] = seed[4] + gain * th
            q, ok, err, _ = arm.ik.solve(pt, -n, q)
            if not ok or abs(q[4] - (seed[4] + gain * th)) > 1e-6:
                bad = f"out of reach: best IK is {err * 1000:.1f} mm off"
                break
            try:
                arm.check_workspace(pt)
            except SafetyStop as e:
                bad = str(e)
                break
            qs.append(q)
        if bad:
            why = bad
            continue
        # the jaws' footprint at the knob's heights, swept through the turn, against the other parts
        R0 = arm.ik.fk_R(qs[1])
        w = np.vstack([STOCK_JAW.world(R0), _moving_jaw(PINCH_OPEN).world(R0)])
        wz = kh - PINCH_DEPTH + w @ n  # each point's height above the knob's base
        w = w - np.outer(w @ n, n)
        hit = None
        for th in np.linspace(0.0, angle, max(2, int(abs(angle) / PINCH_SWEEP) + 1)):
            foot = np.array([p.pos + _rotate(start - p.pos + v, n, th) for v in w])
            for c, r, ot, oid in obstacles:
                d = foot[wz < ot + 0.001] - c  # only what is below the other part's top
                d = d - np.outer(d @ n, n)
                if len(d) and float(np.min(np.linalg.norm(d, axis=1))) < r + 0.001:
                    hit = oid
                    break
            if hit:
                break
        if hit:
            why = f"no room for the jaws: {hit} is in the way"
            continue
        loc = None
        if locate is not None:
            xl = arm.ik.fk_R(locate[0])[:, 0]
            xl = xl - (xl @ n) * n
            xl /= np.linalg.norm(xl)
            loc = (float(locate[0][4]), p.pos + (kh - PINCH_DEPTH) * n - (JAW_FACE_X + gap / 2) * xl, locate[1])
        return _Pinch(start, n, p.pos.copy(), angle, float(seed[4]), gain, qs, skills.SLOW_ZONE_M, hub,
                      p.x.copy(), reach, loc)
    return why


def _pinch_down(arm, plan, start, roll, label, g, widths, opening=PINCH_OPEN, retry=True):
    """Roll the wrist, open the jaws over `start`, go down and shut them. Shut on nothing, or landed on the knob's top,
    the arm's error was along the jaws, where they can't feel the knob: try again PINCH_RETRY either way along them (a
    knob under one jaw's edge pushes the jaws away as they shut, so that way first), unless not `retry`. Returns (width
    held, bias, the shift along the jaws that held), or (None, bias, why)."""
    import manipulate

    n = plan.n
    q = arm.cmd.copy()
    q[4] = roll
    arm.status = f"{label}: roll the wrist"
    skills.move_joints(arm, q)
    arm.status = f"{label}: open the jaws"
    arm.grip(opening, 0.4)
    y = arm.ik.fk_R(q)[:, 1]
    y = y - (y @ n) * n
    y /= np.linalg.norm(y)
    shifts, tried, why, bias = [0.0], 0, None, np.zeros(5)
    while shifts:
        shift = shifts.pop(0)
        tried += 1
        at = start + shift * y
        _, bias = _approach(arm, at + HOVER * n, -n, label)
        arm.status = f"{label}: descend"
        dz, why, peak = _descend(arm, at, n, plan.slow, None, bias)
        g["landing"] = max(g["landing"], peak)
        if why is None:
            arm.status = f"{label}: close"
            before = arm.tip_pose()[0]
            width = _jaw_gap(manipulate._close_on(arm, bias))
            if width >= min(widths) - PINCH_EMPTY:
                return width, bias, shift
            slid = float((arm.tip_pose()[0] - before) @ y)
            why = "the jaws shut on nothing: the knob wasn't between them"
            if tried == 1 and retry:
                first = -PINCH_RETRY if slid > PINCH_SLID else PINCH_RETRY if slid < -PINCH_SLID else None
                shifts = [first] if first is not None else [PINCH_RETRY, -PINCH_RETRY]
            arm.grip(opening, 0.4)
            _line(arm, arm.ik.fk(arm.cmd - bias)[0] + HOVER * n, -n, 0.03, bias, give=True)
        else:
            if tried == 1 and retry:
                shifts = [PINCH_RETRY, -PINCH_RETRY]
            _line(arm, at + HOVER * n, -n, 0.03, bias)
            arm.tare(False)
    return None, bias, why


def _midpoint(arm, n, axis):
    """Where the shut jaws' midline is, in the dial's plane, and the jaws' x there."""
    qr = arm.read_q()
    R, tip = arm.ik.fk_R(qr), arm.ik.fk(qr)[0]
    pt = tip + (JAW_FACE_X + _jaw_gap(arm.jaw()) / 2) * R[:, 0]
    x = R[:, 0] - (R[:, 0] @ n) * n
    return pt - ((pt - axis) @ n) * n, x / np.linalg.norm(x)


def _pinch(arm, plan, limit, label):
    """Turn a dial with the jaws, as two fingers do. First the jaws shut on the knob along its fin, which finds its axis
    along the fin (the knob alone, or knob and fin, between them: either way the middle of what they hold is a known way
    from the axis); then they shut across it, which finds the axis across, and holds it. The wrist and the tip turn about
    that axis by the plan's angle; the angle is the wrist's from the moment the jaws hold the knob, so the arm's own error
    drops out. Then open, lift, shut. Turned about the scanned axis, 5 mm off along the jaws, they slid round the knob
    instead of turning it (-31 deg for -60)."""
    n, g = plan.n, {"stop": None, "peak": 0.0, "landing": 0.0, "travel": 0.0, "turned": 0.0, "contact_offset_mm": None,
                    "trace": [], "missed": None, "touch_mm": None}
    axis, start = plan.axis.copy(), plan.start
    try:
        if plan.locate is not None:
            roll, at, sx = plan.locate
            at = at - (_jaw_gap(PINCH_LOCATE_OPEN) - _jaw_gap(PINCH_OPEN)) / 2 * sx * plan.fin \
                + (plan.reach[0] - plan.reach[1]) / 2 * plan.fin  # the jaws' middle over the middle of knob and fin
            full, hub_only = sum(plan.reach), 2 * plan.radius
            # opened wide: along the fin, opened as for the turn, a jaw came down on the fin's end and turned the dial 39
            # deg before the turn began
            width, bias, shift = _pinch_down(arm, plan, at, roll, f"{label} (find its axis)", g, (full, hub_only),
                                             PINCH_LOCATE_OPEN)
            if width is not None:
                mid, xl = _midpoint(arm, n, axis)
                # what's between the jaws: the knob alone (its middle is the axis) or the knob and its fin
                off = 0.0 if abs(width - hub_only) < abs(width - full) else sx * (plan.reach[0] - plan.reach[1]) / 2
                along = float((mid - axis) @ (sx * xl)) - off * sx  # how far the axis is from where the plan put it, along the fin
                if abs(along) < 2 * PINCH_RETRY:
                    axis = axis + along * plan.fin
                    start = plan.start + along * plan.fin
                g["located_mm"] = round(along * 1000, 1)
            arm.status = f"{label}: let go"
            arm.grip(PINCH_OPEN, 0.4)
            _line(arm, arm.ik.fk(arm.cmd - bias)[0] + HOVER * n, -n, 0.03, bias, give=True)
        width, bias, why = _pinch_down(arm, plan, start, plan.roll, label, g, (2 * plan.radius,))
        if width is None:
            g.update(stop="landed", missed=why)
        else:
            arm.status = f"{label}: turn"
            centre, x0 = _midpoint(arm, n, axis)  # across the jaws, where they hold it; along them, where it was found
            centre = centre + float((axis - centre) @ np.cross(n, x0)) * np.cross(n, x0)
            qr = arm.read_q()
            tip0 = arm.ik.fk(qr)[0]
            q, th = arm.cmd - bias, 0.0
            roll0 = q[4]
            arm.tare()
            ticks, armed = 0, not arm.sensing
            while g["stop"] is None:
                f = float(np.linalg.norm(arm.weighted_force_vec() if arm.sensing else arm.tip_force_vec())) if armed else 0.0
                th = min(abs(plan.angle), th + PINCH_RAD_S / CONTROL_HZ * float(np.clip(1 - f / limit, 0.15, 1)))
                a = math.copysign(th, plan.angle)
                q = q.copy()
                q[4] = roll0 + plan.gain * a
                q = _toward(arm, arm.ik.solve(centre + _rotate(tip0 - centre, n, a), -n, q, iters=30)[0], bias)
                arm.send(q + bias)
                arm.tick()
                ticks += 1
                if not armed and ticks >= round(skills.TARE_AFTER_S * CONTROL_HZ):
                    arm.tare()
                    armed = True
                g["trace"].append((arm.d.time, f))
                g["peak"] = max(g["peak"], f)
                if f >= limit + arm.noise_n:
                    g["stop"] = "force_limit"
                elif th >= abs(plan.angle):
                    g["stop"] = "travel"
            for _ in range(int(0.3 * CONTROL_HZ)):  # let the knob settle in the jaws, then read where the wrist left it
                arm.send(arm.cmd)
                arm.tick()
            _, x = _midpoint(arm, n, axis)
            turned = math.atan2(float(np.cross(x0, x) @ n), float(x0 @ x))
            g["turned"] = max(0.0, math.copysign(1, plan.angle) * turned)
            g["travel"] = g["turned"] * plan.radius
        arm.status = f"{label}: let go"
        arm.grip(PINCH_OPEN, 0.4)
        arm.tare(False)
        _line(arm, arm.ik.fk(arm.cmd - bias)[0] + HOVER * n, -n, 0.03, bias, give=True)
    except SafetyStop:
        arm.grip(JAW_PUSH_SHUT)
        raise
    arm.grip(JAW_PUSH_SHUT, 0.4)
    return g


def _tilt(arm, plan):
    return max(math.acos(float(np.clip(-arm.ik.fk(q)[1] @ plan.n, -1, 1))) for q in plan.qs[1:])


def _flip_plan(arm, p, parts):
    """Push the lever across, 3/4 of the way up, from the side it leans to."""
    n, x = p.normal, p.x
    v, r = p.meta["tip"] - p.pos, p.meta["lever_radius"]
    lean = math.atan2(v @ x, v @ n)
    h = 0.75 * p.meta["lever_len"] * math.cos(lean) - r * math.sin(lean)  # the lever's +x side, 3/4 of the way up
    side = lambda tilt: h * math.tan(tilt) + r / math.cos(tilt)  # where that side is at height h
    until = side(lean) - side(-FLIP_PAST)
    if not _jaws(arm):
        plan = _sideways(arm, p.pos + side(lean) * x, n, -x, 0.0, h, v @ n + r, until, "lever",
                         obstacles=_obstacles(p, parts, p.size[2] - v @ n - r))
        return plan if isinstance(plan, str) else replace(plan, centre=side(lean) - side(0.0))
    # the stock gripper: the jaws open along the throw with the lever between them, and either jaw's inner face pushes,
    # whichever the wrist can roll to face the push. The push runs JAW_SLACK further, as the arm's own error along the
    # throw (up to 6 mm at the test devices' panels) is unseen with servo sensing: a lever already over is held at its
    # stop, which stops the push at the force limit
    # Opened less where the other jaw has no room (a beaker on the hotplate beside its switch)
    plan = "the wrist can't roll the jaws along the lever's throw"
    for opening in (JAW_PUSH_OPEN, JAW_PUSH_NARROW):
        for jaw, xs in (("fixed", -x), ("moving", x)):
            seed = _roll_toward(arm, p.pos + side(lean) * x + HOVER * n, n, xs)
            if seed is None:
                continue
            plan = _sideways(arm, p.pos + side(lean) * x, n, -x, 0.0, h, v @ n + r, until + JAW_SLACK, "lever",
                             obstacles=_obstacles(p, parts, p.size[2] - v @ n - r), seed=seed, jaw=jaw, opening=opening)
            if not isinstance(plan, str):
                return replace(plan, centre=side(lean) - side(0.0))
    return plan


def _guarded(arm, path, length, n, limit, speed, bias, until=None, expect=None, track=False, centre=0.0, stall=False,
             turn=None, read_stop=False):
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
    servo sensing, a part can't let go before the pad is `centre` past where it was met (a lever's centre).

    With turn, (a point on the axis, its unit direction, angle in rad), an arc's travel is the angle the pad has swept
    about the axis since it met the part, not its distance: while the pad bears on a fin's face it keeps its angle to
    the fin, so this is the angle turned whatever radius it touches at. Travel over the arc's contact radius turned
    the centrifuge's dial 39 deg for 60 by geometry, and slips on top of that ended turns anywhere from -5 to -103.
    With read_stop, the push ends ("switched") once a reading moves:
    a lever that went over needs no more, and pushed on into its stop, the servo estimate at the test panels' stretched
    poses read 13-16 N (the hard cap) with 3 N really on the jaw (decisions.md D32).

    With stall (a descent) and servos the only sensing, a force stop also needs the pad held back: over the last
    STALL_S it covered under STALL_FRAC of its command's travel (an absolute lead growth also caught along-path sag, and
    landed the incubator's flip 9.2 mm above its start on nothing). At low, stretched poses the estimate drifts with the pose (on
    the centrifuge's toggle, 0.3 N per mm of creep in free air, 8 N by the end), and descents landed on nothing."""
    q, s, at, f, hold, freed, lead = arm.cmd - bias, 0.0, 0.0, 0.0, np.zeros(3), -1.0, 0.0
    stall = stall and arm.sensing and not arm.axial_sensor
    p_met = None  # turn: where the pad was when it met the part
    hist, fw = deque(maxlen=round(STALL_S * CONTROL_HZ)), 0.0  # stall: recent (s, at), and the weighted force along the path
    g = {"stop": None, "contact": None, "held": None, "peak": 0.0, "trace": [], "ats": [], "reads": []}
    # with servo sensing the force is ignored until a second tare once moving (skills.TARE_AFTER_S), and checks allow
    # for its noise, which along the probe (too_low) is up to 3 times arm.noise_axial
    contact_n, low_n, side_n = max(CONTACT_N, arm.noise_n), max(LOW_N, 3 * arm.noise_axial), limit + arm.noise_n
    arm.tare()
    ticks, armed, moved = 0, not arm.sensing, None
    reads0 = dict(arm.app.readings) if read_stop else None

    def swept(pt):
        c, k = turn[0], turn[1]
        u, v = p_met - c, pt - c
        u, v = u - (u @ k) * k, v - (v @ k) * k
        return math.atan2(float(np.cross(u, v) @ k), float(u @ v))

    def met():
        c = g["contact"]
        if arm.sensing and expect is not None and at >= expect and (c is None or c > expect):
            return expect if moved is None else max(expect, moved)
        return c
    while g["stop"] is None:
        v = speed * float(np.clip(1 - (fw if stall else f) / limit, 0.15, 1))  # stall: the plain estimate's drift slowed
        # a descent onto the centrifuge's panel to 15% while the pad pressed 4-6 N into it
        if turn is not None and p_met is not None:
            # a dial's knob has little friction: left turning at 3 mm/s at the fin it coasted 4-5 deg on, so the last
            # ARC_END_ZONE of the angle creeps
            if swept(arm.tip_pose()[0]) > turn[2] - ARC_END_ZONE:
                v = min(v, ARC_END_SPEED)
        elif until is not None and met() is not None and at - met() > until - END_ZONE:
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
        if stall:
            hist.append((s, at))
            # a part that gives way (a dial's fin landed on: it turned 17.7 deg under the pad) never stalls it, so the
            # estimate counts too, weighted by how well the joints feel each direction (see weighted_force_vec)
            fw = float(-arm.weighted_force_vec() @ m) if armed else 0.0
            if fw >= limit:
                g["stop"], g["peak"] = "force_limit", max(g["peak"], fw)
                g["contact"] = at if g["contact"] is None else g["contact"]
                continue
            ds, dat = (hist[-1][0] - hist[0][0], hist[-1][1] - hist[0][1]) if armed and len(hist) == hist.maxlen else (0, 0)
            if not (ds > 0 and dat < STALL_FRAC * ds):  # the pad keeps up with its command: nothing holds it
                if not g["stop"] and at >= length:
                    g["stop"] = "end"
                continue
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
        if turn is not None and p_met is None and met() is not None:
            p_met = now.copy()
        # checks that give up on a force read it weighted by how well the joints feel each direction (see
        # weighted_force_vec): unweighted, 7.8 N read across the dial's push with 0.2 N there stopped every turn
        Fw = arm.weighted_force_vec() if armed and arm.sensing else F
        Fwm = Fw if Fm is F else Fm
        if f >= limit:
            g["stop"] = "force_limit"
        elif np.linalg.norm(Fw) >= limit + side_n or (until is not None and np.linalg.norm(Fw + f * m) >= side_n):
            g["stop"] = "side_force"
        elif Fwm @ n >= max(low_n, f):
            g["stop"] = "too_low"
        elif turn is not None and p_met is not None and swept(now) >= turn[2]:
            g["stop"] = "travel"
        elif read_stop and arm.app.readings != reads0:
            g["stop"] = "switched"
        elif turn is None and until is not None and met() is not None and at - met() >= until:
            g["stop"] = "travel"
        elif at >= length:
            g["stop"] = "end"
        elif s - at >= LEAD_MAX:
            g["stop"] = "max_lead"
    g["s"], g["at"], g["F"], g["met"] = s, at, F, met()
    g["swept"] = None if turn is None or p_met is None else swept(arm.tip_pose()[0])
    return g


def _descend(arm, start, n, slow, touch, bias):
    """Lower the pad onto start from HOVER above: fast down to `slow` above it, then creeping. With touch
    (how far below start the pad should meet the floor), creep on until it does. Returns (dz, None, peak),
    dz being how far above start the push should run, or (None, why, peak) if it landed on something."""
    top = start + HOVER * n
    landed = max(LANDED_N, 2 * arm.noise_axial)
    g = _guarded(arm, lambda s, c: (top - s * n, -n), max(HOVER - slow, 0.0), n, landed, skills.APPROACH_SPEED, bias,
                 stall=True)
    if g["stop"] == "end":
        s0 = g["s"]
        deep = HOVER + (0.0 if touch is None else touch + TOUCH_BAND)
        # creeping, a servo estimate with nothing touching reads less than moving fast (2.8 N at most, against 4): at
        # landed (5 N), pads rested for seconds on a knob's edge reading 2-3 N, then slid off it at up to 25 N
        g = _guarded(arm, lambda s, c: (top - (s0 + s) * n, -n), deep - s0, n, max(LANDED_N, 1.5 * arm.noise_axial),
                     TOUCH_SPEED, bias, stall=True)
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
    if plan.roll is not None and abs(arm.cmd[4] - plan.roll) > math.radians(2):
        arm.status = f"{label}: roll the wrist"
        q = arm.cmd.copy()
        q[4] = plan.roll
        skills.move_joints(arm, q)
    if plan.jaws:
        arm.status = f"{label}: open the jaws"
        arm.grip(plan.opening, 0.4)
    try:
        g = _push_open(arm, plan, limit, label, n)
    except SafetyStop:
        if plan.jaws:
            arm.grip(JAW_PUSH_SHUT)  # commanded only: they shut as the arm goes home, with no motion here after a stop
        raise
    if plan.jaws:
        arm.grip(JAW_PUSH_SHUT, 0.4)  # lifted clear: shut again, as the stock tip is otherwise used
    return g


def _push_open(arm, plan, limit, label, n):
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
                 plan.what == "knob" and arm.axial_sensor, plan.centre,
                 turn=None if plan.axis is None else (*plan.axis, plan.until / plan.radius),
                 read_stop=plan.jaws is not None and plan.what == "lever")
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
    release = RELEASE
    if plan.axis is not None:  # an arc: straight back off the fin's face. Going by the servo estimate's direction left
        u, release = -path(g["at"], g["met"])[1], ARC_RELEASE  # the pad on the fin, and the lift dragged it 7 deg on
    _unwind(arm, bias)
    _line(arm, now + release * u, -n, RELEASE_SPEED, bias, give=True)
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
            "turned": None if plan.radius is None else (g["swept"] if g.get("swept") is not None else travel / plan.radius),
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
    if isinstance(plan, _Pinch):
        return _pinch(arm, plan, params["force_limit"], label), p, plan
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


def _press(arm, p, limit, label):
    """_poke, and with a fingertip smaller than the pad (the stock gripper's fixed jaw, 6 x 6 mm against the probe's 12
    mm) a press that moved no reading tries again PRESS_SEARCH_MM off each way across the face, until one does. The arm's
    own error at the test devices (5-7 mm) is more than a 10 mm cap's radius: on the wall thermostat, 2 presses in 5
    landed on the cap's rounded rim or the bezel and held at the limit with the button unmoved. Where a press can't tell
    the rim from a stuck button, all five fail, and a stuck button is still a FAIL."""
    before = dict(arm.app.readings)
    g = _poke(arm, p, limit, label)
    if tip_shape(arm).round or arm.app.readings != before:
        return g
    n, x = p.normal, p.x
    y = np.cross(n, x)
    for k, d in enumerate((x, -x, y, -y)):
        T = p.T.copy()
        T[:3, 3] += PRESS_SEARCH_MM * 1e-3 * d
        q = replace(p, T=T, origin=None if p.origin is None else p.origin + PRESS_SEARCH_MM * 1e-3 * d)
        g2 = _poke(arm, q, limit, f"{label} (search {k + 1})")
        g2["peak"] = max(g["peak"], g2["peak"])
        g2["search_mm"] = [round(float(v) * PRESS_SEARCH_MM, 1) for v in (d @ x, d @ y)]
        g = g2
        if arm.app.readings != before:
            break
    return g


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
        th, step = math.copysign(g.get("turned") or 0.0, params["angle"]), p.meta.get("detent_step")
        if step:  # the detent settles it; a reading that counts detents says how many better than the pad's travel
            th = math.copysign(step, params["angle"]) * counted if counted is not None else round(th / step) * step
        k = p.axis / np.linalg.norm(p.axis)
        rng = p.range if tuple(p.range) == (0, 0) else (p.range[0] - th, p.range[1] - th)
        x_now = _rotate(p.x, k, th)
        return replace(p, T=frame(p.pos, p.normal, x_now if p.meta.get("one_sided") else canonical_x(x_now, p.normal)), range=rng,
                       meta={**p.meta, "angle": p.meta.get("angle", 0.0) + th})
    if skill == "flip":
        v = p.meta["tip"] - p.pos
        meta = {**p.meta, "tip": p.meta["tip"] - 2 * (v @ p.x) * p.x, "angle": -p.meta.get("angle", 0.0),
                "on": not p.meta.get("on", True)}
        return replace(p, T=frame(p.pos, p.normal, -p.x), axis=-p.axis, meta=meta)
    if skill == "push_latch":
        return replace(p, meta={**p.meta, "latched": False})
    return p


def _observe(arm, p, target, result):
    """No motion: what the device's readout says its display shows. OBSERVED counts a display as covered, and says
    nothing about whether what it shows is right."""
    if p is None:
        result["reason"] = f"unknown target '{target}'"
    elif p.kind != "display":
        result["reason"] = f"{p.id} is a {p.kind}: only a display can be observed"
    elif getattr(arm.app, "lcd", None) is None:
        result.update(verdict="MISSED", reason=f"nothing reads {p.id} on this rig")
    else:
        result.update(verdict="OBSERVED", reason=f'{p.id} shows "{arm.app.lcd}"', channel="LCD", lcd=arm.app.lcd, duration_s=0.0)
    return result


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
    if skill == "observe":
        return _observe(arm, p, target, result)
    if p is not None and skill in ("hook_pull", "swing", "pick", "place"):  # reposition is the backend's: it moves the device, not a part
        import manipulate

        return getattr(manipulate, skill)(arm, parts, i, step)
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
                g = (_press(arm, p, params["force_limit"], label) if skill == "press" else
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
            result.update({k: g[k] for k in ("touch_mm", "regrip_mm", "located_mm", "search_mm") if k in g})
            if "landing" in g:
                result["landing_n"] = round(float(g["landing"]), 2)
            if skill == "turn" and plan.radius and g.get("turned") is not None:
                result["turned_deg"] = round(math.degrees(g["turned"]), 1)
            # steps a counting reading moved, signed by the way its first change went (the way the push went)
            counted = ((seq[ch][-1] - seq[ch][0]) * math.copysign(1, seq[ch][1] - seq[ch][0])
                       if ch and isinstance(seq[ch][-1], int) else None)
            if app.readings != before and verdict != "MISSED":
                parts[i] = _moved(p, skill, params, g, plan, counted)
    except SafetyStop as e:
        seq, _ = _changes(app, before, n_events)
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
