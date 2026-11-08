"""The probe's touch and the USB wrist camera's last look, for perception without a depth camera.

    plane, spots = touch_plane(arm, scene)           # 4x4 panel frame from 3 touch-offs on clear panel
    parts = touch_parts(arm, scene, parts, plane)    # heights read by touch, as the touch plan places them
    refine = make_refine(usb_wrist, plane)           # affordances.run_plan(arm, parts, steps, refine=refine)

A touch is a guarded move along the panel normal through affordances._guarded, as the skills' descents use: fast
to a little above where the surface should be, then creeping until the force against the pad passes the contact
threshold. The contact point comes from the joint readings, so it is in the probe's own frame: it carries the
arm's calibration error at that spot, which is what the probe needs. Servo-current sensing reads noisy until
tared (_guarded tares once the creep is moving), so the creep starts far enough out for that tare before contact
and the threshold sits well above the noise (_contact_n). Such a threshold presses a button, or pushes a door's
pad until it unlatches, before it registers, so those then go untouched. The plane comes from the probe, not
from vision: vision planes carry the arm's calibration error, 1.5-2.6 mm at the probe (up to 10 mm), against
0.03-0.08 mm under the controls for three touch-offs.

Touches go where the measured plan puts them, with the pad's real 12 mm width: the top of a button, door pad,
knob or slider knob; a dial's plateau beside its fin, never the fin; a toggle's base beyond the lever, never the
lever. A round part over ROUND3_D across with no fin gets three: its centre and two on its rim 90 deg apart, so a
fin under the centre shows as a step (at 0.7 of the radius, as first tested with a 2 mm disc, the 12 mm pad landed
on the fin with all three on 6 of 13 sim dials, and the step went unseen). When rgbperceive's
scene.rgb["touch_hints"] is present, only the parts it names are touched, still where this plan puts the pad.
The pad hangs past a toggle's base and a dial's rim there, and a scan position 1-3 mm off can put it on a lever
root, a fin or the panel, so a touch that disagrees with the scan's height by more than TRUST_M is not believed.

refine follows perceive.refine's contract with one RGB frame: from the step's approach pose it projects the
believed part into the frame, outlines it with SAM from that box, casts the outline onto the touched plane at the
part's height, and moves the part there. Camera and fingertip share the gripper, so joint calibration errors mostly
cancel; the camera mount's error stays in.
Only buttons and door pads are refined (see REFINED).
"""
import math
import os
import pickle
import time
from dataclasses import replace

import cv2
import numpy as np
from scipy import ndimage

import affordances
import features
import perceive
import skills
from rig import CONTACT_N, SafetyStop, tip_shape

PAD_R = affordances.PAD_R
CREEP_M = 0.005         # creep from this far above where a part's top should be, and give up this far past it
PLANE_SLACK = 0.012     # the same for a touch-off: the scan's plane is up to 10 mm off at the probe, and meeting
                        # the panel at approach speed peaked at 12 N
CREEP_SPEED = 0.002     # m/s: at the skills' 4 mm/s (affordances.TOUCH_SPEED) the pad met the panel at up to 4.1 N
                        # and buttons at their 1.5 N preload before contact registered; at 2 mm/s 1.5 N and 1.05 N
RETREAT_SPEED = 0.03    # m/s back out after a touch, as a press retreats
EDGE_M = 0.012          # panel touch-offs stay this far inside the scanned panel: near an edge the arm can't
                        # reach squarely, and a probe arriving 10.6 deg off the normal hit the 15 N cap
CLEAR_M = 0.004         # and this far beyond the pad's rim from every outline the scan found
GRID_M = 0.002          # spacing of the candidate spots
RETRY_M = 0.015         # after a touch-off, the next spot is at least this far from it
TILT_DEG = (8.0, 12.0)  # spots the probe can point at within the first of these come first, then the second
FIN_CLEAR = 0.002       # the pad's rim this far from a dial's fin (scan positions are ~1 mm off at the probe)
LEVER_CLEAR = 0.0015    # and from a toggle lever's root
FACE_M = 0.003          # a tip's face: its hull points this near the front (the stock nub, and the jaws 1.7 mm behind it)
ROUND3_D = 0.020        # a finless round part wider than this gets three touches
BESIDE_M = 0.001        # one of those reading under this landed on the panel beside it (1 of 3 knobs on RGB scans)
TRUST_M = 0.0015        # a touch further than this from the scan's height landed on something else: a fin or
                        # lever root reads 2-7 mm high, the panel past a toggle's base 2 mm low (RGB scan heights:
                        # 93-95% within 1 mm)
NOISE_X = 2.0           # contact at this many times the arm's force noise floor along the probe (arm.noise_axial):
                        # at 1x, touch-offs stopped short and put the plane 1-9 mm off on 9 of 10 devices
PLANE_TRUST_M = 0.006   # a touch-off further than this from the scan's plane is taken as a false contact: on 74 test
                        # devices the scan's plane was at most 5.5 mm off, and servo sensing's false contacts put it 7-23 mm off
PLANE_TILT = 5.0        # deg: three touch-offs whose plane is further than this off the scan's have one on a part (a
                        # button cap's rim put one 3.7 mm over the other two and the plane 15.6 deg off); good ones
                        # were 0.1-3.1 deg off in the other 73 logged explore runs
SPRING_N = 1.5          # a button's spring preload (Rev B's): a touch that needs more force presses it. At 6 N,
                        # touches also pushed a door's pad 1-3 mm in and unlatched 2 doors of 10
TOUCH_SIGMA = 0.0003    # touch height noise (0.05-0.2 mm on rigid tops with the sim's force sensor); scales the
                        # dial rule in touch_kind
PAD_TOP = 0.0019        # a round part this low is a door's push pad (pads are under 2 mm, buttons 1.8-6 mm)
KNOB_TOP = 0.0065       # one this tall is a knob (knobs are 7 mm and up)
# refine
REFINED = ("button", "door")  # Not sliders: the probe hides most of the knob from the slide's hover pose. Not toggles:
                        # the dark base merges with its shadow and is cut by the lever (both further off than
                        # scanned, on seeds 1000-1019). Not dials: fin, skirt and shadow left wrong circles that
                        # moved 3 of 9 RGB-scanned dials 1.8-3.4 mm off. Knobs need a pinch, so no skill runs.
AREA = (0.6, 1.6)       # a SAM mask outside this many times the fitted circle's silhouette is another object
FAR = 0.3               # the far rim: outline normals at least this far along the view, away from the camera
RADIUS_TOL = 0.0015     # a fitted circle this much bigger than scanned is another object,
SHRINK = 0.6            # or one under this share of it (RGB scans put door pads' 9 mm radius at 11.2)
SEARCH_M = 0.006        # SAM's box grows this much all round when its first outline doesn't fit, and a part found
                        # further than this from where it was believed is a neighbour (11+ mm off a part 4 mm
                        # from where it was scanned)
FIT_TRIM = 0.0015       # outline points further than this from the fitted circle are something else
MIN_EDGE = 30           # outline points needed for a fit
FIT_FROM_OUTLINE = False  # start the far-rim fit from the middle of SAM's outline, not the believed centre (hw_rig)
SHIFT_MAX = None        # a look this far from the scan is a neighbour (default SEARCH_M)
LOOK_DIR = None         # a folder: each look's frame is saved there with SAM's outline and the fitted circle drawn
TWO_VIEW = None         # m: a second frame this far across the panel, and the cap's centre triangulated from both (hw_rig)
RAY_GAP = 0.003         # the two rays through the fitted centres passing further apart than this disagree
HEIGHT_MAX = 0.010      # a triangulated top further than this from the scan's is not believed
RADIUS_GAP = 0.0006     # nor one whose two circles, at that height, differ in radius by more (one fit took another arc)


# --- touch ---

def _contact_n(arm):
    """Force (N) a touch takes as contact: CONTACT_N, or NOISE_X times the sensor's floor along the probe."""
    return max(CONTACT_N, NOISE_X * arm.noise_axial)


def touch(arm, at, n, top, bottom=-CREEP_M, label="touch", on=None):
    """Guarded touch along -n onto the point `at`: from skills.APPROACH_M out, fast to `top` above it, then creeping
    until contact or `bottom` (negative: below it). Returns (surface point, "") or (None, why). The point is under
    the tip at the height the pad met the surface (_depth; on is the touched part's footprint), from the joint
    readings. Contact before the creep means something stands more than `top` above where the surface should be,
    and counts as a miss."""
    limit = _contact_n(arm)
    start = at + skills.APPROACH_M * n
    try:
        _, bias = affordances._approach(arm, start, -n, label)
        arm.status = f"{label}: touch"
        if arm.stall_m:  # one creep from the start: a stall can't be told from a new move's start-up (affordances._stall)
            g = affordances._guarded(arm, lambda s, c: (start - s * n, -n), skills.APPROACH_M - bottom, n, limit,
                                     CREEP_SPEED, bias)
            fast = g["contact"] is not None and g["contact"] < skills.APPROACH_M - top
        else:
            g = affordances._guarded(arm, lambda s, c: (start - s * n, -n), skills.APPROACH_M - top, n, limit,
                                     skills.APPROACH_SPEED, bias)
            fast = g["stop"] != "end"
            if not fast:
                g = affordances._guarded(arm, lambda s, c: (at + (top - s) * n, -n), top - bottom, n, limit,
                                         CREEP_SPEED, bias)
        tip, a = arm.tip_pose()
        if arm.sensing:
            affordances._unwind(arm, bias)  # a late contact left the command mm into the surface
        affordances._line(arm, start, -n, RETREAT_SPEED, bias)
        arm.tare(False)  # with servo sensing, the zero is dropped only once the pad is clear, as the skills do
    except SafetyStop as e:
        return None, f"safety stop: {e}"
    s = tip - _depth(tip, a, n, on, arm.ik.fk_R(arm.read_q()), tip_shape(arm)) * n
    if fast:
        return None, f"touched something {(s - at) @ n * 1000:.1f} mm above where the surface should be"
    if g["stop"] in ("end", "max_lead"):
        return None, f"no contact down to {-bottom * 1000:.0f} mm past the surface" if g["stop"] == "end" else \
            "the arm gave way before contact"
    return s, ""


_DISC = [(rho * math.cos(t), rho * math.sin(t)) for rho in np.linspace(0, PAD_R, 7)
         for t in np.linspace(0, 2 * math.pi, 48, endpoint=False)]


def _face(shape, k=9):
    """k x k grids over each layer of a tip shape's hull points within FACE_M of its front, in the tip's frame."""
    z, out, g = shape.pts[:, 2], [], np.linspace(0, 1, k)
    for zl in np.unique(z[z <= z.min() + FACE_M]):
        f = shape.pts[z == zl]
        (x0, y0), (x1, y1) = f[:, :2].min(0), f[:, :2].max(0)
        out += [(x0 + u * (x1 - x0), y0 + v * (y1 - y0), zl) for u in g for v in g]
    return np.array(out)


def _reach(arm):
    """How far the tip's face reaches from the tip across its axis, whatever the wrist roll."""
    shape = tip_shape(arm)
    return PAD_R if shape.round else float(np.max(np.linalg.norm(_face(shape)[:, :2], axis=1)))


def _depth(tip, a, n, on=None, R=None, shape=None):
    """How far below the tip, along -n, the tip met the surface: at its lowest point (affordances._lowest, with R the
    tip's rotation and shape its rig.TipShape), or, given on(points) -> bool, the footprint of the part touched, at the
    tip's lowest point over it. A probe a few degrees off square whose pad hangs past a part's edge meets the edge
    first, not its own lowest rim: 0.85 mm low on a toggle's base."""
    if on is not None:
        if shape is None or shape.round:
            e1 = np.cross(a, n if abs(a @ n) < 0.999 else np.eye(3)[np.argmin(np.abs(a))])
            e1 /= np.linalg.norm(e1)
            P = tip + np.asarray(_DISC) @ np.vstack([e1, np.cross(a, e1)])
        else:
            P = tip + _face(shape) @ np.asarray(R).T
        over = on(P)
        if over.any():
            return float(-((P[over] - tip) @ n).min())
    return affordances._lowest(a, n, R, shape)


def _footprints(scene, parts):
    """Arm-frame outlines of everything on the panel: every blob the scan outlined and every part."""
    out = [b["outline"] for b in getattr(scene, "blobs", [])]
    for p in parts:
        if p.kind == "door":
            out.append(p.meta["corners"])
        elif p.points is not None and len(p.points):
            out.append(p.points)
        r = 0.5 * max(p.size[0], p.size[1])
        th = np.linspace(0, 2 * math.pi, 16, endpoint=False)
        out.append(p.pos + r * (np.outer(np.cos(th), p.x) + np.outer(np.sin(th), np.cross(p.normal, p.x))))
        if p.kind == "slider":
            out.append(np.asarray(p.meta["slot_ends"]))
    return out


def _clear_spots(scene, parts, reach=PAD_R):
    """Points on the scanned panel plane where the whole tip lands on clear panel: EDGE_M inside its extent and
    reach (the tip's, _reach) + CLEAR_M from the convex hull of every footprint."""
    T, (u0, u1, v0, v1) = scene.plane
    us, vs = np.arange(u0 + EDGE_M, u1 - EDGE_M, GRID_M), np.arange(v0 + EDGE_M, v1 - EDGE_M, GRID_M)
    busy = np.zeros((len(us), len(vs)), np.uint8)
    for pts in _footprints(scene, parts):
        uv = (np.asarray(pts) - T[:3, 3]) @ T[:3, :2]
        ij = np.round((uv - [us[0], vs[0]]) / GRID_M)[:, ::-1].astype(np.int32)  # (col, row) for OpenCV
        cv2.fillConvexPoly(busy, cv2.convexHull(ij), 1)
    free = ndimage.distance_transform_edt(busy == 0) * GRID_M >= reach + CLEAR_M
    i, j = np.nonzero(free)
    return T[:3, 3] + np.outer(us[i], T[:3, 0]) + np.outer(vs[j], T[:3, 1])


def _next_spot(spots, got):
    """The candidate that spreads the touch-offs most: furthest from the middle of the clear panel, then
    furthest from the first touch, then making the biggest triangle with the first two."""
    if not len(spots):
        return None
    if not got:
        d = np.linalg.norm(spots - spots.mean(0), axis=1)
    elif len(got) == 1:
        d = np.linalg.norm(spots - got[0], axis=1)
    else:
        d = np.linalg.norm(np.cross(got[1] - got[0], spots - got[0]), axis=1)
    return spots[np.argmax(d)]


def touch_plane(arm, scene, parts=None):
    """(plane, touches): the panel plane in the probe's frame from 3 touch-offs on clear panel, a 4x4 frame like
    perceive's (z out of the panel, x down the slope) with its origin at the touches' middle, and the touched
    points. Spots come from scene.plane (the scan's plane and extent) and keep clear of scene.blobs and of parts
    (default scene.parts); the probe must point within TILT_DEG of square at them, and a touch that fails is
    swapped for the next best. With fewer than 3 touches the plane is the scan's, moved onto the touches if any.
    Parks the arm at home."""
    parts = scene.parts if parts is None else parts
    T = scene.plane[0]
    n = T[:3, 2]
    spots = _clear_spots(scene, parts, _reach(arm))
    tilt = np.array([arm.ik.solve(at + skills.APPROACH_M * n, -n, arm.cmd)[3] for at in spots])
    free, got = np.ones(len(spots), bool), []
    for limit in TILT_DEG:
        while len(got) < 3:
            at = _next_spot(spots[free & (tilt <= limit)], got)
            if at is None:
                break
            free &= np.linalg.norm(spots - at, axis=1) > RETRY_M
            p, _ = touch(arm, at, n, PLANE_SLACK, -PLANE_SLACK, label="touch panel")
            if p is not None and abs((p - T[:3, 3]) @ n) <= PLANE_TRUST_M:  # else a false contact: try the next spot
                got.append(p)
            if len(got) == 3 and math.degrees(math.acos(min(abs(_normal(got) @ n), 1.0))) > PLANE_TILT:  # odd one out
                d = np.array([(g - T[:3, 3]) @ n for g in got])
                got.pop(int(np.argmax(np.abs(d - np.median(d)))))
    skills.go_home(arm)
    if len(got) < 3:  # the scan's plane, through the touches made
        T = T.copy()
        if got:
            T[:3, 3] += ((np.mean(got, axis=0) - T[:3, 3]) @ n) * n
        return T, got
    m = _normal(got)
    return perceive.plane_frame(m * np.sign(m @ n), np.mean(got, axis=0)), got


def _normal(pts):
    """Unit normal of the plane through three points."""
    m = np.cross(pts[1] - pts[0], pts[2] - pts[0])
    return m / np.linalg.norm(m)


def plan_touches(parts):
    """The touch plan: {part id: [arm-frame points]}, the first point setting the part's height."""
    plan = {}
    for p in parts:
        n, x = p.normal, p.x
        y = np.cross(n, x)
        m = p.meta
        if p.kind in ("button", "door", "slider"):
            at = [p.pos]
        elif p.kind == "knob":
            r = m["knob_radius"]
            at = [p.pos, p.pos + r * x, p.pos + r * y] if 2 * r > ROUND3_D else [p.pos]
        elif p.kind == "dial":
            at = [p.pos + (m["fin_width"] / 2 + PAD_R + FIN_CLEAR) * y]
        elif p.kind == "toggle":
            at = [p.pos - (m["lever_radius"] + PAD_R + LEVER_CLEAR) * x]
        else:
            continue
        plan[p.id] = at
    return plan


def _step(heights, sigma):
    """Whether touches spread enough to have landed on two levels: more than SUB_STEP, or 4 sigma at noisier
    touch (3 touches spread past 4 sigma about 1% of the time)."""
    return max(heights) - min(heights) > max(perceive.SUB_STEP, 4 * sigma)


def touch_kind(kind, heights, sigma=TOUCH_SIGMA):
    """What the touched heights (m above the panel) say a round part is, or None if they agree with kind: a step
    between them means an upper part under one touch, a dial; else the height tells a door pad (under PAD_TOP),
    a button and a knob (over KNOB_TOP) apart."""
    if _step(heights, sigma):
        return None if kind == "dial" else "dial"
    if kind not in ("button", "knob"):
        return None
    h = float(np.median(heights))
    new = "pad" if h < PAD_TOP else "knob" if h > KNOB_TOP else "button"
    return None if new == kind else new


def _top(p):
    """The scan's height above the panel of the surface a touch on p reads: a dial's or knob's body, a toggle's
    base, else the part's top."""
    if p.kind in ("dial", "knob"):
        return p.meta["knob_height"]
    return p.meta["base_size"][2] if p.kind == "toggle" else p.size[2]


def _footprint(p):
    """on(points) -> bool, whether arm-frame points are over the surface a touch on p reads (a round top, a
    toggle's base), as scanned; None for a slider's knob, which is wider than the pad."""
    uv = np.c_[p.x, np.cross(p.normal, p.x)]
    if p.kind == "toggle":
        return lambda X: np.all(np.abs((X - p.pos) @ uv) <= p.meta["base_size"][:2] / 2, axis=1)
    shape = _round(p)
    return None if shape is None else lambda X: np.linalg.norm((X - p.pos) @ uv, axis=1) <= shape[0]


def touch_parts(arm, scene, parts, plane, sigma=TOUCH_SIGMA):
    """parts with their heights read by touch where plan_touches(parts) puts the pad, placed on the touched plane:
    every part it places, or only those scene.rgb["touch_hints"] names when present (rgbperceive's own spots for
    a dial and a toggle put the 12 mm pad on the fin and on the lever's root). Each touched part gets meta touched
    (heights, m above the plane), touch_kind if those disagree with its kind (touch_kind()), or touch_why if no
    touch reached it or what it read is more than TRUST_M from the scan's height. Its origin moves along the
    plane's normal to the height read (the lowest of several touches with a step between them, else their
    median), or to the scan's height when the touch isn't believed. It keeps its own normal: turned to the
    touched plane's (2.4 deg off on a miscalibrated arm), a slider's slide back hit 58 N. Parks the arm at home."""
    n, P0 = plane[:3, 2], plane[:3, 3]
    plan, hints = plan_touches(parts), (getattr(scene, "rgb", None) or {}).get("touch_hints")
    out = list(parts)
    for i, p in enumerate(parts):
        if p.id not in plan or (hints is not None and p.id not in hints):
            continue
        if p.kind in ("button", "door") and _contact_n(arm) > SPRING_N:
            out[i] = replace(p, meta={**p.meta, "touched": [], "touch_why": "a touch would press it before it reads"})
            continue
        hs, whys = [], []
        for at in plan[p.id]:
            at = np.asarray(at, float)
            s, why = touch(arm, at - ((at - P0) @ n) * n, n, p.size[2] + CREEP_M, label=f"touch {p.id}",
                           on=_footprint(p))
            h = None if s is None else float((s - P0) @ n)
            if h is not None and len(plan[p.id]) > 1 and h < BESIDE_M:
                h, why = None, "a touch on its rim landed on the panel beside it"
            if h is None:
                whys.append(why)
            else:
                hs.append(h)
        out[i] = _heighten(p, hs, plane, sigma) if hs else \
            replace(p, meta={**p.meta, "touched": [], "touch_why": "; ".join(whys)})
    skills.go_home(arm)
    return out


def _heighten(p, hs, plane, sigma):
    """p on the touched plane at the height its touches read, or at the scan's if they read something else."""
    n, P0 = plane[:3, 2], plane[:3, 3]
    h = min(hs) if _step(hs, sigma) else float(np.median(hs))
    size, meta = p.size.copy(), {**p.meta, "touched": hs}
    if abs(h - _top(p)) > TRUST_M:
        meta["touch_why"] = f"touched {h * 1000:.1f} mm up, the scan says {_top(p) * 1000:.1f}: kept the scan's"
        h = _top(p)
    elif touch_kind(p.kind, hs, sigma):
        meta["touch_kind"] = touch_kind(p.kind, hs, sigma)
    if p.kind == "dial":
        meta["knob_height"] = h
        size[2] = h + meta["fin_height"]
    elif p.kind == "toggle":
        size[2] += h - meta["base_size"][2]
        meta["base_size"] = np.r_[meta["base_size"][:2], h]
    else:
        if p.kind == "slider":
            meta["side_height"] += (h - size[2]) / 2  # halfway between the rails and the knob's top
        if p.kind == "knob":
            meta["knob_height"] = h
        size[2] = h
    o = p.pos - ((p.pos - P0) @ n) * n + h * n
    return _moved(replace(p, size=size, meta=meta), features.frame(o, p.normal, p.x))


def _moved(p, Tp):
    """p with its frame set to Tp, its points, axis and point-valued meta carried along."""
    D = Tp @ np.linalg.inv(p.T)

    def move(X):
        return None if X is None else np.asarray(X) @ D[:3, :3].T + D[:3, 3]

    meta = {k: move(v) if k in ("slot_ends", "tip", "corners", "hinge") else v for k, v in p.meta.items()}
    return replace(p, T=Tp, axis=None if p.axis is None else D[:3, :3] @ p.axis, origin=move(p.origin),
                   points=move(p.points), meta=meta)


# --- refine ---

def _project(K, T, X):
    """Pixels (Nx2) of arm-frame points X in a camera at pose T (OpenCV axes)."""
    c = (np.asarray(X) - T[:3, 3]) @ T[:3, :3]
    return c[:, :2] / c[:, 2:] * [K[0, 0], K[1, 1]] + K[:2, 2]


def _round(p):
    """(radius, top height above the panel) of a round part's top: a button's cap, a door's push pad, a dial's or
    knob's body. None for other kinds."""
    m = p.meta
    if p.kind in ("button", "door"):
        return m.get("radius", m.get("pad_radius")), p.size[2]
    if p.kind in ("dial", "knob"):
        return m["knob_radius"], m["knob_height"]
    return None


def _fit(q, toward, r, c=None):
    """(centre (in-plane, m), radius, None) of the circle that best fits outline points q (cast at the top's
    height), or (None, None, why). Only the rim facing away from the camera counts: on the near side the outline
    is the foot of the part's side and the shadow it casts. The radius is fitted too, since a radius off by d
    would move a centre fitted to a far arc alone by d; one under SHRINK r or over r + RADIUS_TOL (r: the
    scan's) means SAM outlined something else. Points far from the circle (a neighbour, the probe's shadow) are
    dropped in steps down to FIT_TRIM. c: where to start the fit (default the believed centre, 0)."""
    c, rr = (np.zeros(2) if c is None else c), r
    for trim in (np.inf, np.inf, 3 * FIT_TRIM, 2 * FIT_TRIM, FIT_TRIM, FIT_TRIM, FIT_TRIM):
        d = q - c
        dist = np.linalg.norm(d, axis=1)
        nrm = d / np.maximum(dist[:, None], 1e-9)
        keep = (nrm @ toward > FAR) & (np.abs(dist - rr) < trim)
        if keep.sum() < MIN_EDGE:
            return None, None, f"only {keep.sum()} outline points on its far rim"
        J = np.c_[nrm[keep], np.ones(keep.sum())]  # d(distance - radius) / d(centre, radius), negated
        step = np.linalg.lstsq(J, dist[keep] - rr, rcond=None)[0]
        c, rr = c + step[:2], rr + step[2]
    if not SHRINK * r < rr < r + RADIUS_TOL:
        return None, None, f"its outline is a circle {rr * 2000:.1f} mm across, not {r * 2000:.1f}"
    return c, rr, None


def locate(f, p, plane, sam, seen=None):
    """Where part p's origin is, seen in RGB frame f: (point, None), or (None, why). The part's round outline as believed, at its top and at the panel, is
    projected into the frame; their bounding box is SAM's prompt. The mask's outline is cast onto the plane at
    the part's top height and a circle fitted to it (_fit); the point is its centre at that height. A mask whose
    area is far from the fitted circle's silhouette is another object, or cut by the box: then the box grows
    SEARCH_M all round for one more try. Only kinds in REFINED. seen, a dict, gets the last try's box, mask,
    believed silhouette and fitted circle (pixels), to draw."""
    seen = {} if seen is None else seen
    if p.kind not in REFINED:
        return None, f"a {p.kind} isn't refined from RGB (see touch.REFINED)"
    r, top = _round(p)
    n, P0 = plane[:3, 2], plane[:3, 3]
    u = p.x - (p.x @ n) * n
    uv = np.c_[u, np.cross(n, u)] / np.linalg.norm(u)
    c0 = p.pos - ((p.pos - P0) @ n) * n  # the believed centre, on the plane
    th = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    ring = np.c_[np.cos(th), np.sin(th)] @ uv.T
    H, W = f.rgb.shape[:2]
    T = f.T_base_cam
    for grow in (0.0, SEARCH_M):

        def silhouette(c, rad):  # pixels of a circle round c at the part's top and at the panel
            return _project(f.K, T, np.vstack([c + rad * ring + h * n for h in (top, 0.0)]))

        px = silhouette(c0, r + grow)
        box = np.r_[px.min(0), px.max(0)].clip(0, [W - 1, H - 1, W - 1, H - 1])
        mask = sam(f.rgb, box[None])[0][0].astype(np.uint8)
        edge = mask.astype(bool) & ~cv2.erode(mask, np.ones((3, 3), np.uint8)).astype(bool)
        x0, y0, x1, y1 = np.round(box).astype(int)
        edge[:, :x0 + 2] = edge[:, x1 - 1:] = edge[:y0 + 2] = edge[y1 - 1:] = False  # SAM's cut at the box
        vy, ux = np.nonzero(edge)
        ray = np.c_[(ux - f.K[0, 2]) / f.K[0, 0], (vy - f.K[1, 2]) / f.K[1, 1], np.ones(len(ux))] @ T[:3, :3].T
        X = T[:3, 3] + ray * (((c0 + top * n - T[:3, 3]) @ n) / (ray @ n))[:, None]  # on the plane at the top
        away = (c0 - T[:3, 3]) @ uv
        q = (X - c0) @ uv
        # the far rim is picked relative to the fit's start: from a belief 8 mm off, it was a few stray points beside STOP
        c, rr, why = _fit(q, away / max(np.linalg.norm(away), 1e-9), r, np.median(q, axis=0) if FIT_FROM_OUTLINE else None)
        seen.update(box=box, mask=mask, believed=silhouette(c0, r)[:48], circle=None)
        if c is None:
            continue
        seen.update(circle=_project(f.K, T, c0 + uv @ c + top * n + rr * ring), fitted_mm=rr * 2000, scanned_mm=r * 2000)
        area = mask.sum() / cv2.contourArea(cv2.convexHull(silhouette(c0 + uv @ c, rr).astype(np.float32)))
        if AREA[0] < area < AREA[1]:
            return c0 + uv @ c + top * n, None
        why = f"SAM's outline is {area:.1f} times the area of the circle fitted to it"
    return None, f"{p.id}: {why}"


def _triangulate(o1, X1, o2, X2):
    """(midpoint, gap) of the closest points on the rays from o1 through X1 and from o2 through X2."""
    d1, d2 = X1 - o1, X2 - o2
    s, t = np.linalg.lstsq(np.c_[d1, -d2], o2 - o1, rcond=None)[0]
    P1, P2 = o1 + s * d1, o2 + t * d2
    return (P1 + P2) / 2, float(np.linalg.norm(P1 - P2))


def _second_look(arm, wrist, p, plane, sam, f, pos, seen1):
    """(point, None): p's top centre triangulated from frame f, where locate() put it at pos, and a second frame taken
    TWO_VIEW across the panel; or (None, why), and f's answer stands. locate() casts the outline onto a plane at the
    scan's top height, so a wrong height scales the fitted circle about the camera but leaves its centre on the
    camera's ray through the real one: two such rays meet at the real centre. Leaves the arm at the second view."""
    tip, a = arm.tip_pose()
    bias = arm.cmd - arm.read_q()  # what holds the arm here holds it 2 cm away too (affordances._approach)
    at = next((tip + s * TWO_VIEW * plane[:3, 1] for s in (1, -1)
               if arm.ik.solve(tip + s * TWO_VIEW * plane[:3, 1], a, arm.cmd)[1]), None)
    if at is None:
        return None, "no second view in reach"
    affordances._approach(arm, at, a, f"look at {p.id}", bias=bias)
    f2, seen = wrist.capture(), {}
    pos2, why = locate(f2, p, plane, sam, seen)
    if pos2 is not None:
        o1, o2 = f.T_base_cam[:3, 3], f2.T_base_cam[:3, 3]
        X, gap = _triangulate(o1, pos, o2, pos2)
        h, top = (X - plane[:3, 3]) @ plane[:3, 2], _round(p)[1]
        # each fitted radius scaled from the scan's height to the triangulated one: a fit that took another arc differs
        r1, r2 = (s["fitted_mm"] / 2000 * np.linalg.norm(X - o) / np.linalg.norm(Y - o)
                  for s, o, Y in ((seen1, o1, pos), (seen, o2, pos2)))
        if gap > RAY_GAP:
            why = f"the two views' rays pass {gap * 1000:.1f} mm apart"
        elif abs(r1 - r2) > RADIUS_GAP:
            why = f"the two views fit circles {r1 * 2000:.1f} and {r2 * 2000:.1f} mm across"
        elif abs(h - top) > HEIGHT_MAX:
            why = f"its top triangulates {h * 1000:.1f} mm up, the scan says {top * 1000:.1f}"
    if LOOK_DIR:
        try:  # evidence must never stop a look
            _save_look(f2, p, plane, seen, f"second view: {why or f'top {h * 1000:.1f} mm up'}", "_b")
        except Exception as e:  # noqa: BLE001
            print(f"couldn't save the look: {type(e).__name__}: {e}")
    return (None, f"second view: {why}") if why else (X, None)


def _save_look(f, p, plane, seen, said, tag=""):
    """The look's frame in LOOK_DIR with SAM's prompt box (blue), the part as believed (white), SAM's outline (yellow)
    and the fitted circle (green), and what came of it. The folder ignores itself in git."""
    os.makedirs(LOOK_DIR, exist_ok=True)
    if not os.path.exists(os.path.join(LOOK_DIR, ".gitignore")):
        with open(os.path.join(LOOK_DIR, ".gitignore"), "w") as fh:
            fh.write("*\n")
    img = f.rgb.copy()
    if seen.get("mask") is not None:
        x0, y0, x1, y1 = np.round(seen["box"]).astype(int)
        cv2.rectangle(img, (x0, y0), (x1, y1), (255, 120, 0), 2)
        cv2.polylines(img, [seen["believed"].astype(np.int32)], True, (255, 255, 255), 2)
        contours, _ = cv2.findContours(seen["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(img, contours, -1, (0, 255, 255), 2)
    if seen.get("circle") is not None:
        cv2.polylines(img, [seen["circle"].astype(np.int32)], True, (0, 255, 0), 2)
        said += f" (fitted {seen['fitted_mm']:.1f} mm across, scanned {seen['scanned_mm']:.1f})"
    for color, width in (((0, 0, 0), 6), ((255, 255, 255), 2)):
        cv2.putText(img, (said if said.startswith(p.id) else f"{p.id}: {said}")[:110], (12, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, color, width)
    name = os.path.join(LOOK_DIR, f"{time.strftime('%H%M%S')}_{p.id}{tag}")
    cv2.imwrite(name + ".jpg", img)
    with open(name + ".pkl", "wb") as fh:  # the frame as taken (pose and K too), the part and plane: to replay locate()
        pickle.dump((f, p, plane), fh)


def make_refine(wrist, plane, sam=None):
    """refine(arm, p) -> part for affordances.run_plan, with perceive.refine's contract (meta refined,
    refine_shift and, on failure, refine_why with the part unchanged; never moves the arm), from
    one frame of an RGB wrist camera (sensors.WristCamera(arm, usb=True)) and the touched plane (touch_plane).
    The part moves to where locate() sees it, at its height over the plane, keeping its normal. Only kinds in
    REFINED. sam(bgr, boxes) -> (masks, scores) defaults to segmodels.sam_boxes(), imported here so that
    touch_plane and touch_parts don't load torch."""
    if sam is None:
        import segmodels
        sam = segmodels.sam_boxes()

    def refine(arm, p):
        f, seen = wrist.capture(), {}
        pos, why = locate(f, p, plane, sam, seen)
        X, single = None, None
        if pos is not None and TWO_VIEW:
            X, single = _second_look(arm, wrist, p, plane, sam, f, pos, seen)
        d = np.zeros(3) if pos is None else pos - p.pos
        if X is not None:  # the triangulated top moves along the normal too: the shift checked is along the panel
            pos, d = X, X - p.pos
            d -= (d @ plane[:3, 2]) * plane[:3, 2]
        shift = float(np.linalg.norm(d))
        if shift > (SHIFT_MAX or SEARCH_M):
            why = f"the outline SAM found is {shift * 1000:.1f} mm from where {p.id} should be: a neighbour"
        if LOOK_DIR:
            try:  # evidence must never stop a look
                _save_look(f, p, plane, seen, why or f"refined: moved {shift * 1000:.1f} mm")
            except Exception as e:  # noqa: BLE001
                print(f"couldn't save the look: {type(e).__name__}: {e}")
        if why:
            return replace(p, meta={**p.meta, "refined": False, "refine_shift": 0.0, "refine_why": why})
        if X is not None:  # the press's depth then counts from the top seen, not the scan's
            p = replace(p, size=np.r_[p.size[:2], (X - plane[:3, 3]) @ plane[:3, 2]])
        q = _moved(p, features.frame(pos, p.normal, p.x))
        q.meta.update(refined=True, refine_shift=shift, triangulated=X is not None)
        if single:
            q.meta["triangulate_why"] = single
        q.meta.pop("refine_why", None)
        return q

    return refine
