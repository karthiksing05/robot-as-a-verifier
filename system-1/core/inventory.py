"""A registered inventory: the controls a device file lists, placed where touches say the device really is, for the
parts a scan can't see. Robot-side: it reads only a device file's controls, roots, bodies, placement and registration
sections, never its faults, revisions' fault choices as such, firmware or answer key.

    inv = Inventory("appliances/centrifuge/device.yaml", rev="B")
    Ts, report = inv.register(arm)              # touch each root's registration faces; again after any move
    parts = inv.parts(Ts, carried=old_parts)    # features.Part, source "cad"; joint states carried over by id
    merged, notes = merge(scanned, parts)       # a scanned part wins wherever it is

A device on a bench moves in x, y and yaw only, so each root's pose is fitted from three or more touches on faces whose
normals between them pin those three: residual along each face's normal, linearised about the believed pose, solved by
least squares and iterated. The first guess is the device file's placement, or the last registered pose.

A touch here is not touch.touch, which points the probe along the face's normal: the SO-101's five joints keep the
tool in the vertical plane through the pan axis, which a side face's normal can't lie in. So the tool points as near
-normal as that plane and the arm's reach allow, the tip moves along -normal, contact is the force back along the
normal, and the contact point is the pad's rim furthest along -normal (affordances._lowest).
"""
import math
import pathlib
from dataclasses import replace

import numpy as np
import yaml

from features import Part
from rig import CONTROL_HZ, TABLE_Z, SafetyStop

M = 1e-3
SOURCE = "cad"
CONF = 0.8                  # a registered part's confidence: its place is touched, its existence is from CAD
MERGE_M = 0.010             # a scanned part this near a CAD part of the same kind is the same part
START_M = 0.035             # touches start this far out from where the face should be,
PAST_M = 0.035              # and give up this far past it
FAST_SPEED = 0.02           # m/s to TOP_M out from the face
TOP_M = 0.012
CREEP_SPEED = 0.003         # m/s from there
RAMP_S = 0.5                # up to speed over this long
NOISE_X = 2.0               # contact: the force back along the normal over this many times the arm's force noise,
HOLD_TICKS = 3              # for this many ticks running; the point is where it first crossed
PUSH_SPEED = 0.005          # m/s, pushing a device across the bench
PUSH_LIMIT_N = 12.0         # stop pushing at this: a device that won't slide under it is stuck, or clamped after all
PUSH_PERP_M = 0.003         # a reposition this far off the push face's normal is a direction the arm can't push
PUSH_TOL_M = 0.003          # a push that went this near what was asked went as asked
RETREAT_SPEED = 0.03
CLEAR_M = 0.06              # touches come down to their start from this far above it, and go back up
FIT_ITERS = 4
SCAN_W = 0.3                # a scanned part's offset counts this much against a touch's (2 mm against 0.3)
PRIOR_W = 0.01              # pull toward the starting guess, so what nothing measures stays put
YAW_SCALE = 0.1             # m per rad, to compare yaw's column with x's and y's when saying what was measured
MATCH_M = 0.05              # the most a device is believed to have moved since its guess, per scanned part
INLIER_M = 0.008            # a scanned part this near where a proposed shift puts a CAD part of its kind agrees
MATCH_KINDS = ("button", "dial", "toggle", "slider", "knob", "door", "display")
PAN_XY = np.array([0.0388, 0.0])
TILTS = range(-10, 91, 5)   # tool tilts below level to choose from, for each touch
RIM_LEAD = 0.08             # a.n up to this: the 20 mm rod leans under 2 mm toward the face, inside the pad's 6 mm rim


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _yaw(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _T(R, p):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, p
    return T


def _frame(origin, z, x):
    z = _unit(z)
    x = np.asarray(x, float) - (np.asarray(x, float) @ z) * z
    x = _unit(x)
    return _T(np.c_[x, np.cross(z, x), z], origin)


def _rotate(v, k, th):
    k = _unit(k)
    return v * math.cos(th) + np.cross(k, v) * math.sin(th) + k * (k @ v) * (1 - math.cos(th))


def resolve(item, params):
    """$name in a device file: the current choices' value."""
    if isinstance(item, dict):
        return {k: resolve(v, params) for k, v in item.items()}
    if isinstance(item, list):
        return [resolve(v, params) for v in item]
    if isinstance(item, str) and item.startswith("$"):
        return params[item[1:]]
    return item


def root_for(world, c):
    """The root a control's points are on: its own `root`, its body's, or (the sim's loader has meshes) whichever root's
    bounding box holds it."""
    if c.get("root"):
        return c["root"]
    if c.get("body"):
        return next(b["root"] for b in world.bodies if b["name"] == c["body"])
    if c.get("object"):
        return next(o["root"] for o in world.cfg.get("objects", []) if o["name"] == c["object"])
    p = np.asarray(c.get("pos", c.get("top")), float)
    for root, box in getattr(world, "root_boxes", {}).items():
        if np.all(p >= np.subtract(box[0], 1)) and np.all(p <= np.add(box[1], 1)):
            return root
    return next(iter(world.cfg["roots"]))


def parts_from(world, point, vec, state):
    """features.Part per control in the device file, at whatever pose point(body, p) and vec(body, v) give, product
    frame mm in, arm frame m out. state(c) -> {"q": joint value} for a control on a moving body."""
    parts = []
    for c in world.cfg["controls"]:
        c = resolve(c, world.params)
        kind, body = c["kind"], c.get("body") or c.get("root_of")
        pt = (lambda p, b=body: point(b, p)) if body else None
        if kind == "object":
            pt = vc = None
        elif body is None:
            root = root_for(world, c)
            pt = lambda p, r=root: point(r, p)
            vc = lambda v, r=root: vec(r, v)
        else:
            vc = lambda v, b=body: vec(b, v)
        st = state(c)
        size = np.asarray(c.get("size", (0, 0, 0)), float) * M
        if kind == "button":
            top, n = pt(c["top"]), vc(c["normal"])
            parts.append(Part(c["id"], kind, _frame(top, n, vc(c["x"])), size, "translation", -n, top, st["q"] / (c["travel"] * M),
                              (-st["q"], c["travel"] * M - st["q"]), meta=dict(radius=c["radius"] * M, travel=c["travel"] * M, switch_at=c["switch_at"])))
        elif kind == "dial":
            top, n = pt(c["top"]), vc(c["normal"])
            lo, hi = np.radians(c["range_deg"])
            parts.append(Part(c["id"], kind, _frame(top, n, vc(c["x"])), size, "rotation", n, top, 0.0, (lo - st["q"], hi - st["q"]),
                              meta=dict(knob_radius=c["knob_radius"] * M, knob_height=c["knob_height"] * M, angle=st["q"], fin_length=c["fin_length"] * M,
                                        fin_width=c["fin_width"] * M, fin_height=c["fin_height"] * M, one_sided=bool(c.get("one_sided")), floor_gap=c.get("floor_gap", 0.0) * M)))
        elif kind == "toggle":
            # the panel's normal, not the lever's: taken off the lever, it tilted 30 deg with it, the lean looked unchanged, and
            # a second flip pushed the lever into its own stop (5 N, "no reading changed") instead of back
            hinge, tip = pt(c["hinge"]), pt(c["tip"])
            n = vec(root_for(world, c), c["normal"]) if c.get("body") else vc(c["normal"])
            lean = tip - hinge - ((tip - hinge) @ n) * n
            x = _unit(lean)
            parts.append(Part(c["id"], kind, _frame(hinge, n, x), size, "rotation", np.cross(x, n), hinge, 1.0, (0.0, math.radians(30)),
                              meta=dict(lever_len=c["lever_len"] * M, lever_radius=c["lever_radius"] * M, tip=tip, base_size=np.asarray(c["base_size"]) * M,
                                        angle=st["q"], on=bool(st["q"] > math.radians(15)))))
        elif kind == "handle":
            p0, n = pt(c["pos"]), vc(c["normal"])
            axis = vec(root_for(world, c), c["axis"])  # a hinge line stays put on its root
            hinge = point(root_for(world, c), c["hinge"])
            parts.append(Part(c["id"], kind, _frame(p0, n, axis), size, "rotation", axis, hinge, st["q"],
                              (-st["q"], math.radians(c["open_deg"]) - st["q"]),
                              meta=dict(pull=vc(c["pull"]), under=vc(c["under"]), clear=c["clear"] * M, hinge=hinge, hinge_axis=axis, open_deg=c["open_deg"], angle=st["q"],
                                        latched=False, grip=c.get("grip", "tip"), reads=bool(c.get("reads")), pad_offset=tuple(np.asarray(c.get("pad_offset", (2.5, 7.0))) * M))))
        elif kind == "object":
            o = next(o for o in world.cfg["objects"] if o["name"] == c["object"])
            top = point(c["object"], o["collar"])
            parts.append(Part(c["id"], kind, _frame(top, vec(c["object"], (0, 0, 1)), vec(c["object"], c["jaw_axis"])), np.array([0.022, 0.018, 0.069]),
                              meta=dict(flats=c["flats"] * M, collar=top, body=c["object"],
                                        # how far the body's top (collar_top) stands above the collar point: a grip above it
                                        # (a lifting loop) has to keep the jaws' tips off it
                                        top_above=float((point(c["object"], o.get("collar_top", o["collar"])) - top)[2]),
                                        # pairs of parallel faces the jaws can close on, best first: direction across them, width, where
                                        # the grip is from the collar point, and how far past it the jaws' tips go
                                        grips=[dict(axis=vec(c["object"], g["axis"]), width=g["width"] * M, depth=g.get("depth", 2.5) * M,
                                                    at=point(c["object"], g["at"]) - top if "at" in g else np.zeros(3))
                                               for g in c.get("grips", [{"axis": c["jaw_axis"], "width": c["flats"]}])])))
        else:  # display, well
            p0, n = pt(c["pos"]), vc(c["normal"])
            meta = dict(screen=tuple(size[:2])) if kind == "display" else dict(collar=pt(c["collar"]), reads=bool(c.get("reads")))
            parts.append(Part(c["id"], kind, _frame(p0, n, vc(c["x"])), size, meta=meta))
    return parts


def visible_params(cfg, rev):
    """The device file's $values for a revision: the parts it is built from, which its CAD shows (a handle's shape)."""
    choices = dict(item.split("=") for item in rev.split(",")) if "=" in rev else cfg["revs"][rev]
    params = {}
    for fault, opts in cfg.get("faults", {}).items():
        chosen = opts[choices[fault]]
        params.update(chosen.get("params", {}))
        params.update(chosen.get("parts", {}))
    return params


class Inventory:
    """What a device file says is on the device, for the robot. Joint states it can't know are taken as rest (shut,
    off) unless carried over from what the robot last believed."""

    def __init__(self, path, rev="B"):
        self.path = pathlib.Path(path).resolve()
        self.cfg = yaml.safe_load(self.path.read_text())
        self.params = visible_params(self.cfg, rev)
        self.bodies = [resolve({k: v for k, v in b.items() if k != "parts"}, self.params) for b in self.cfg["bodies"]]
        self.objects = {o["name"]: o for o in self.cfg.get("objects", [])}
        self.Ts = self.nominal()
        self.residuals = {}

    def nominal(self):
        """Each root's 4x4 in the arm frame where the device file places it."""
        p = self.cfg["placement"]
        z = TABLE_Z + self.cfg.get("stand_mm", 0) * M
        T = _T(_yaw(p["yaw"]), [p["x"] * M, p["y"] * M, z])
        return {r: T.copy() for r in self.cfg["roots"]}

    def _root_or_none(self, c):
        try:
            return root_for(self, resolve(c, self.params))
        except (StopIteration, KeyError):
            return None

    def root_of(self, name):
        if name in self.cfg["roots"]:
            return name
        if name in self.objects:
            return self.objects[name]["root"]
        return next(b["root"] for b in self.bodies if b["name"] == name)

    def parts(self, Ts=None, carried=None, lost=()):
        """features.Part list, source "cad", at root poses Ts. carried: Parts the robot believed before (a move, a
        repeat explore): a moving part's angle or position, and an object the jaws moved, keep what was believed. lost:
        roots registration couldn't find, whose parts are left out: where they are isn't known."""
        Ts = Ts or self.Ts
        old = {p.id: p for p in (carried or [])}
        state_of = {}
        for c in self.cfg["controls"]:
            c = resolve(c, self.params)
            p = old.get(c["id"])
            if p is not None and c.get("body") and "angle" in p.meta:
                state_of[c["body"]] = float(p.meta["angle"])
        bodies = {b["name"]: b for b in self.bodies}

        def point(name, p):
            p = np.asarray(p, float) * M
            b = bodies.get(name)
            if b is not None and name in state_of:
                j = b["joint"]
                anchor, axis = np.asarray(j["anchor"], float) * M, _unit(j["axis"])
                p = anchor + _rotate(p - anchor, axis, state_of[name]) if j["type"] == "hinge" else p + axis * state_of[name]
            T = Ts[self.root_of(name)]
            return T[:3, :3] @ p + T[:3, 3]

        def vec(name, v):
            v = np.asarray(v, float)
            b = bodies.get(name)
            if b is not None and name in state_of and b["joint"]["type"] == "hinge":
                v = _rotate(v, _unit(b["joint"]["axis"]), state_of[name])
            return Ts[self.root_of(name)][:3, :3] @ v

        def state(c):
            return {"q": state_of.get(c.get("body"), 0.0)}

        out = []
        gone = {c["id"] for c in self.cfg["controls"] if lost and self._root_or_none(c) in lost}
        for p in parts_from(self, point, vec, state):
            if p.id in gone:
                continue
            prev = old.get(p.id)
            if p.kind == "object" and prev is not None and prev.meta.get("in"):
                continue  # the jaws moved it: where it was put is kept below, not where the CAD has it
            out.append(replace(p, score=CONF, meta={**p.meta, "source": SOURCE}))
        for p in old.values():
            if p.kind == "object" and p.meta.get("in"):
                out.append(p)
        return out

    # --- registration ---

    def touches(self, root, Ts=None):
        """A root's registration faces, arm frame: (point, outward normal) each, at root poses Ts."""
        T = (Ts or self.Ts)[root]
        return [(T[:3, :3] @ (np.asarray(t["at"], float) * M) + T[:3, 3], T[:3, :3] @ _unit(t["normal"]))
                for t in self.cfg.get("registration", {}).get(root, {}).get("touches", [])]

    def matches(self, scanned, Ts=None):
        """Scanned parts paired with this inventory's, per root. Nearest-neighbour pairing goes wrong once the guess is
        off by half a part's spacing (three buttons 23 mm apart, a guess 25 mm off), so: each pairing of a scanned part
        with a believed part of its kind proposes a shift; the shift the most other scanned parts agree with, within
        INLIER_M, wins (the smallest, on a tie), and its agreeing pairs are the matches. Shifts over MATCH_M aren't
        proposed. Returns {root: [(scanned arm-frame point, CAD product-frame point mm)]}."""
        Ts = Ts or self.Ts
        mine = {p.id: p for p in self.parts(Ts)}
        # resolved: a revision can name a part's body or points through $params (the kettle-base's $knob_body)
        cad = [resolve(c, self.params) for c in self.cfg["controls"] if c["kind"] in MATCH_KINDS and c["id"] in mine]
        scanned = [p for p in scanned or [] if p.kind in MATCH_KINDS]
        best = None
        for s0 in scanned:
            for c0 in cad:
                if c0["kind"] != s0.kind:
                    continue
                shift = np.asarray(s0.pos)[:2] - mine[c0["id"]].pos[:2]
                if np.linalg.norm(shift) > MATCH_M:
                    continue
                pairs, used = [], set()
                for s_ in scanned:
                    near = [(float(np.linalg.norm(np.asarray(s_.pos)[:2] - mine[c["id"]].pos[:2] - shift)), c) for c in cad
                            if c["kind"] == s_.kind and c["id"] not in used]
                    if near:
                        dist, c = min(near, key=lambda t: t[0])
                        if dist < INLIER_M:
                            used.add(c["id"])
                            pairs.append((s_, c))
                key = (len(pairs), -float(np.linalg.norm(shift)))
                if best is None or key > best[0]:
                    best = (key, pairs)
        out = {}
        for s_, c in (best[1] if best else []):
            root = self.root_of(c["body"]) if c.get("body") else c.get("root") or next(iter(self.cfg["roots"]))
            out.setdefault(root, []).append((np.asarray(s_.pos, float), self._cad_point(c)))
        return out

    def _cad_point(self, c):
        """A control's reference point, product frame mm, where parts_from puts Part.pos (joints at rest)."""
        return np.asarray(c.get("top", c.get("pos", c.get("hinge"))), float)

    def register(self, arm=None, scanned=None, Ts=None, roots=None, touch=True):
        """Fit each root's x, y and yaw from what measures it, in two passes: scanned parts matched to its CAD parts,
        then, from there, touches on its registration faces (arm given and touch; a touch started from a guess 3 cm off
        can start inside something). A weak pull toward the guess keeps what nothing measures where it was. A root nothing
        measures at all is `lost`: it stays at the guess and the report says it wasn't found, since moving it as another
        root did was a guess (a rack bumped on its own was left 57-69 mm off). Returns (Ts, report): per root the shift
        from the guess (mm, deg), which of x, y, yaw were measured, residuals (mm), any touch that failed, and `lost`."""
        T_start = {r: T.copy() for r, T in (Ts or self.Ts).items()}
        Ts = {r: T.copy() for r, T in T_start.items()}
        roots = roots or list(self.cfg["roots"])
        reg = self.cfg.get("registration", {})
        report = {r: {"touches": 0, "scan_matches": 0, "measured": [], "residual_mm": [], "failed": []} for r in roots}
        pairs = self.matches(scanned, Ts) if scanned else {}
        for root in roots:  # 1: the scan
            if pairs.get(root):
                Ts[root], res, seen = fit(self, root, Ts[root], [], pairs[root])
                report[root].update(scan_matches=len(pairs[root]), measured=seen, residual_mm=[round(r * 1000, 2) for r in res])
        if touch and arm is not None:  # 2: touches, from there
            pairs = self.matches(scanned, Ts) if scanned else {}
            for root in roots:
                got = []
                for k, (at, n) in enumerate(self.touches(root, Ts)):
                    s_, err = touch_face(arm, at, n, f"register {root} {k + 1}")
                    if s_ is None:
                        report[root]["failed"].append(f"touch {k + 1}: {err}")
                    else:
                        got.append((k, s_))
                if got:
                    Ts[root], res, seen = fit(self, root, Ts[root], got, pairs.get(root, []))
                    report[root].update(touches=len(got), measured=sorted(set(seen) | set(report[root]["measured"]), key="x y yaw".split().index),
                                        residual_mm=[round(r * 1000, 2) for r in res])
        for root in roots:
            if not report[root]["measured"]:
                Ts[root] = T_start[root]
                report[root]["lost"] = ("not found: nothing measured it (no scanned part matched, no touch landed), so "
                                        "where it is now isn't known")
            d = Ts[root][:3, 3] - T_start[root][:3, 3]
            dyaw = math.degrees(math.atan2(Ts[root][1, 0], Ts[root][0, 0]) - math.atan2(T_start[root][1, 0], T_start[root][0, 0]))
            report[root].update(dx_mm=round(float(d[0]) * 1000, 2), dy_mm=round(float(d[1]) * 1000, 2), dyaw_deg=round((dyaw + 180) % 360 - 180, 2))
        self.Ts = Ts
        return Ts, report


def fit(inv, root, T0, got, pairs=()):
    """Least-squares x, y, yaw of a root: each touched point's distance off its face along the face's normal, and each
    scanned part's offset from its CAD point (weighted down by SCAN_W, a scan being a few mm off), linearised about the
    current pose and iterated, with PRIOR_W pulling toward the start. Returns (T, residuals, which of x, y, yaw the
    measurements pin)."""
    T = T0.copy()
    faces = inv.cfg.get("registration", {}).get(root, {}).get("touches", [])
    seen = []
    for _ in range(FIT_ITERS):
        A, b = [], []
        c = T[:3, 3]
        for k, s in got:
            p = T[:3, :3] @ (np.asarray(faces[k]["at"], float) * M) + c
            n = T[:3, :3] @ _unit(faces[k]["normal"])
            # the face moved by t and turned by w about the root's origin: s sits on it when n.(s - p) = n.t + w n.(z x (p - c))
            A.append([n[0], n[1], n @ np.cross([0, 0, 1.0], p - c)])
            b.append(n @ (s - p))
        for s, pp in pairs:
            p = T[:3, :3] @ (pp * M) + c
            lever = np.cross([0, 0, 1.0], p - c)
            A += [[SCAN_W, 0, SCAN_W * lever[0]], [0, SCAN_W, SCAN_W * lever[1]]]
            b += [SCAN_W * (s - p)[0], SCAN_W * (s - p)[1]]
        if not A:
            return T, [], []
        _, sv, Vt = np.linalg.svd(np.array(A) * [1, 1, YAW_SCALE])
        seen = [name for name, i in (("x", 0), ("y", 1), ("yaw", 2))
                if any(sv[j] > 0.2 * sv[0] and abs(Vt[j, i]) > 0.5 for j in range(len(sv)))]
        x, *_ = np.linalg.lstsq(np.vstack([A, PRIOR_W * np.eye(3)]), np.r_[b, np.zeros(3)], rcond=None)
        T = _T(_yaw(math.degrees(x[2])) @ T[:3, :3], c + [x[0], x[1], 0.0])
    res = []
    for k, s in got:
        p = T[:3, :3] @ (np.asarray(faces[k]["at"], float) * M) + T[:3, 3]
        n = T[:3, :3] @ _unit(faces[k]["normal"])
        res.append(float(n @ (s - p)))
    for s, pp in pairs:
        res.append(float(np.linalg.norm((s - (T[:3, :3] @ (pp * M) + T[:3, 3]))[:2])))
    return T, res, seen


def tool_axis(arm, at, n, q0=None):
    """The reachable tool direction nearest -n at `at`: in the vertical plane through the pan axis. None if none
    reaches, with the start pose too."""
    r = _unit(np.r_[at[:2] - PAN_XY, 0.0])[:2]
    best = None
    for deg in TILTS:
        t = math.radians(deg)
        a = np.array([*(math.cos(t) * r), -math.sin(t)])
        score = float(a @ -n)
        # pointing a little away from the face is still a touch with the pad's rim, as long as the rod behind the pad
        # doesn't lean out past the rim toward the face: a side face's normal can lean away from the pan plane
        if score < -RIM_LEAD or (best is not None and score <= best[0]):
            continue
        q0 = arm.cmd if q0 is None else q0
        ok = all(arm.ik.solve(at + d * n, a, q0)[1] for d in (START_M, 0.0, -PAST_M / 2)) and \
            arm.ik.solve(at + START_M * n + [0, 0, CLEAR_M], a, q0)[1]
        if ok:
            best = (score, a)
    return None if best is None else best[1]


def _clear(arm):
    """After a stop, straight up from wherever the arm is, then home: a joint move from low down can sweep through the device."""
    import affordances
    import skills

    try:
        arm.tare(False)
        tip, a = arm.tip_pose()
        affordances._line(arm, tip + np.array([0, 0, CLEAR_M]), a, RETREAT_SPEED, np.zeros(5))
        skills.go_home(arm)
    except SafetyStop:
        pass


def touch_face(arm, at, n, label="register"):
    """Guarded touch onto a face at `at` facing n, the tool as near -n as it can point. Returns (point on the face,
    from the joint readings, "") or (None, why)."""
    import affordances
    import touch as touch_mod

    a = tool_axis(arm, at, n)
    if a is None:
        return None, f"no tool direction reaches {np.round(at * 1000, 1).tolist()} mm from outside its face"
    start = at + START_M * n
    # along a face's normal the force is mostly the servo estimate's, not the pad's: keep clear of its noise, and
    # believe it only when it holds
    limit = max(touch_mod._contact_n(arm), NOISE_X * arm.noise_n)
    try:
        # in and out from above: a joint move straight to or from a pose this low can sweep through the device
        above = start + np.array([0, 0, CLEAR_M])
        _, bias = affordances._approach(arm, above, a, label)
        affordances._line(arm, start, a, RETREAT_SPEED, bias)
        arm.status = f"{label}: touch"
        arm.tare()
        q, s, met = arm.cmd - bias, 0.0, None
        total = START_M + PAST_M
        ticks, held = 0, 0
        while s < total:
            v = FAST_SPEED if s < START_M - TOP_M else CREEP_SPEED
            v *= min(1.0, (ticks + 1) / (RAMP_S * CONTROL_HZ))  # the servo estimate reads a sudden start as a push
            s += v / CONTROL_HZ
            q = arm.ik.solve(start - s * n, a, q, iters=30)[0]
            arm.send(q + bias)
            arm.tick()
            ticks += 1
            if arm.sensing and ticks == int(0.3 * CONTROL_HZ):
                arm.tare()  # the servo estimate's zero, once moving
            held = held + 1 if ticks > 0.3 * CONTROL_HZ and float(arm.tip_force_vec() @ n) > limit else 0
            if held == 1:
                first = arm.tip_pose()
            if held >= HOLD_TICKS:
                met = first
                break
        affordances._line(arm, start, a, RETREAT_SPEED, bias)
        affordances._line(arm, above, a, RETREAT_SPEED, bias)
        arm.tare(False)
        import skills

        skills.go_home(arm)
    except SafetyStop as e:
        _clear(arm)
        return None, f"safety stop: {e}"
    if met is None:
        return None, f"no contact {PAST_M * 1000:.0f} mm past where the face should be"
    tip, axis = met
    return tip - affordances._lowest(axis, n) * n, ""


def push(arm, inv, root, dx_mm, dy_mm, yaw_deg, mount):
    """reposition: push a root across the bench with the probe, from its push face in the device file. Refuses when
    the root is clamped, past the device file's bounds, for a turn, or for a direction other than away along the push
    face's normal (the only way the arm can push it). How far it went comes from the joint readings between first
    contact and the end of the push; the root's believed pose moves by that, for registration to start from.
    Returns {"ok", "reason", "moved_mm", "peak_n"}."""
    import affordances
    import skills
    import touch as touch_mod

    out = {"ok": False, "moved_mm": 0.0, "peak_n": 0.0}
    r = inv.cfg.get("reposition", {})
    faces = r.get("push", {}).get(root, [])
    if mount != "free":
        return {**out, "reason": f"{root} is clamped to the bench"}
    if abs(dx_mm) > r.get("dx_mm", 0) or abs(dy_mm) > r.get("dy_mm", 0) or abs(yaw_deg) > r.get("yaw_deg", 0):
        return {**out, "reason": f"outside reposition's bounds: dx and dy within {r.get('dx_mm', 0)} mm, yaw within {r.get('yaw_deg', 0)} deg"}
    if yaw_deg:
        return {**out, "reason": "turning it needs a push off its centre, which this arm doesn't do"}
    if not faces:
        return {**out, "reason": f"the device file gives no face to push {root} from"}
    T = inv.Ts[root]
    at = T[:3, :3] @ (np.asarray(faces[0]["at"], float) * M) + T[:3, 3]
    n = T[:3, :3] @ _unit(faces[0]["normal"])
    d = np.array([dx_mm, dy_mm, 0.0]) * M
    along = float(d @ -n)
    if along <= 0 or np.linalg.norm(d - along * -n) > PUSH_PERP_M:
        away = -n[:2] / np.linalg.norm(n[:2])
        return {**out, "reason": f"the arm can only push {root} away from itself, along ({away[0]:.2f}, {away[1]:.2f}) in x and y: "
                                 f"dx_mm = {away[0]:.2f} k, dy_mm = {away[1]:.2f} k for k up to {r.get('dx_mm', 0)}"}
    a = tool_axis(arm, at, n)
    if a is None or not arm.ik.solve(at - (along + 0.005) * n, a, arm.cmd)[1]:
        return {**out, "reason": f"the arm can't reach {root}'s push face through the whole push"}
    start = at + START_M * n
    above = start + np.array([0, 0, CLEAR_M])
    limit = max(touch_mod._contact_n(arm), NOISE_X * arm.noise_n)
    peak, met, moved = 0.0, None, 0.0
    try:
        _, bias = affordances._approach(arm, above, a, f"reposition {root}")
        affordances._line(arm, start, a, RETREAT_SPEED, bias)
        arm.status = f"reposition {root}: push"
        arm.tare()
        q, s, ticks, held = arm.cmd - bias, 0.0, 0, 0
        while s < START_M + PAST_M + along:
            v = (FAST_SPEED if s < START_M - TOP_M and met is None else PUSH_SPEED) * min(1.0, (ticks + 1) / (RAMP_S * CONTROL_HZ))
            s += v / CONTROL_HZ
            q = arm.ik.solve(start - s * n, a, q, iters=30)[0]
            arm.send(q + bias)
            arm.tick()
            ticks += 1
            if arm.sensing and ticks == int(0.3 * CONTROL_HZ):
                arm.tare()
            f = float(arm.tip_force_vec() @ n)
            peak = max(peak, f)
            peak = max(peak, arm.tip_force())
            if met is None:
                held = held + 1 if ticks > 0.3 * CONTROL_HZ and f > limit else 0
                if held >= HOLD_TICKS:
                    met, s_met = arm.tip_pose()[0], s
            elif s - s_met >= along:
                break
            if max(f, arm.tip_force()) > PUSH_LIMIT_N:  # along the probe too: that's what the hard cap reads
                break
        end = arm.tip_pose()[0]
        back = start + float((end - at) @ -n) * -n   # the push's start, carried along with the device
        affordances._line(arm, back, a, RETREAT_SPEED, bias)
        affordances._line(arm, back + [0, 0, CLEAR_M], a, RETREAT_SPEED, bias)
        arm.tare(False)
        skills.go_home(arm)
    except SafetyStop as e:
        _clear(arm)
        return {**out, "reason": f"safety stop: {e}", "peak_n": round(peak, 2)}
    if met is None:
        return {**out, "reason": f"never met {root}'s push face", "peak_n": round(peak, 2)}
    moved = float((end - met) @ -n)
    shift = moved * -n
    inv.Ts[root] = _T(inv.Ts[root][:3, :3], inv.Ts[root][:3, 3] + [shift[0], shift[1], 0.0])
    ok = abs(moved - along) < PUSH_TOL_M
    return {"ok": ok, "moved_mm": round(moved * 1000, 1), "peak_n": round(peak, 2), "asked_mm": round(along * 1000, 1),
            "tool_below_level_deg": round(math.degrees(math.asin(-a[2])), 1),
            "reason": f"pushed {root} {moved * 1000:.1f} mm of {along * 1000:.1f}, by the joints after first contact" +
                      ("" if ok else f": it stopped at {PUSH_LIMIT_N:g} N. The tool reaches this face {math.degrees(math.asin(-a[2])):.0f} deg "
                                     "below level, so a push also presses the device into the bench")}


def merge(scanned, registered):
    """Scanned parts, plus each registered part with no scanned part of its kind within MERGE_M: a scan sees where a
    part is, so it wins where it found one. Returns (parts, {id: "scan" | "cad"})."""
    out, source = list(scanned), {p.id: "scan" for p in scanned}
    taken = {p.id for p in scanned}
    for c in registered:
        near = [p for p in scanned if p.kind == c.kind and np.linalg.norm(np.asarray(p.pos) - np.asarray(c.pos)) < MERGE_M]
        if near:
            continue
        pid = c.id
        while pid in taken:
            pid += "_cad"
        out.append(replace(c, id=pid))
        taken.add(pid)
        source[pid] = SOURCE
    return out, source
