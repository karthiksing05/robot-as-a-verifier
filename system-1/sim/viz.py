"""Drawing toolkit for the demo: 3D overlays, ghost arms, camera panels, a dashboard and video.

3D glyphs live in the arm frame (metres). Collect them in an Overlay, then write it into any
MjvScene after that scene is updated: renderer.scene after update_scene, or viewer.user_scn.

    ov = viz.Overlay()
    for p in parts:
        ov.part(p)                          # standard glyph per kind, colours in viz.KIND_RGB
    ov.points(xyz, rgb)                     # point cloud, thinned to about ov.max_points
    ov.frustum(frame.T_base_cam, frame.K, (848, 480))
    r = viz.renderer(arm.m, 1408, 792)
    img = viz.render(r, arm.d, viz.camera(lookat, 0.8, 140, -25), ov, ghosts=[(q, viz.GHOST)])

2D images are BGR uint8 (OpenCV order, like sensors.Frame.rgb). T_base_cam is the camera pose
in the arm frame, OpenCV convention (x right, y down, z forward).

    panel = viz.draw_parts(frame.rgb, parts, frame.K, frame.T_base_cam, width=viz.Dashboard.PANEL_W)
    dash = viz.Dashboard("Unknown device", "CAD-free, tag-free")
    dash.log("scan 3/9", t=arm.d.time)
    dash.plan = [("press button_1", "PASS"), ("slide slider_1", "run"), ("turn dial_1", "")]
    with viz.Video("runs/demo.mp4") as video:
        video.write(dash.frame(img, [("iPhone RGB", panel)], t=arm.d.time))
"""
import functools
import math
from collections import deque

import cv2
import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import robot

G = mujoco.mjtGeom
DECOR = mujoco.mjtCatBit.mjCAT_DECOR  # decor geoms cast no shadows
EMISSION, SPECULAR = 0.2, 0.3  # overlay material: a little glow, little shine
LABEL_LIFT = np.array([0, 0, 0.012])  # 3D labels float above their anchor
_Z3, _I9 = np.zeros(3), np.eye(3).ravel()


def _hex(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def bgr(rgb):
    """0..1 RGB(A) to an OpenCV BGR tuple."""
    return tuple(int(round(255 * c)) for c in rgb[2::-1])


# One colour per part kind, in 3D and 2D: the dataviz reference palette without yellow (the arm
# is yellow). Seven hues can't all be told apart by colour alone, so every glyph also has a label.
KIND_RGB = {"button": _hex("#3987e5"), "slider": _hex("#eb6834"), "dial": _hex("#6250d6"),
            "toggle": _hex("#1baf7a"), "door": _hex("#e87ba4"), "knob": _hex("#008300"),
            "display": _hex("#c3c2b7")}
UNKNOWN_RGB = _hex("#898781")
VERDICT_RGB = {"PASS": _hex("#0ca30c"), "FAIL": _hex("#d03b3b"), "MISSED": _hex("#ec835a"),
               "ABORTED": _hex("#fab219"), "REFUSED": _hex("#898781")}
GHOST = (0.35, 0.8, 1.0, 0.3)
INK, INK2, MUTED = _hex("#f0efec"), _hex("#c3c2b7"), _hex("#898781")
SURFACE, PAGE, HAIRLINE = _hex("#1a1a19"), _hex("#0d0d0d"), _hex("#2c2c2a")


def _ramp(stops, n=256):
    """n x 3 BGR lookup table through hex colour stops."""
    c = np.array([_hex(s) for s in stops])
    t = np.linspace(0, 1, n)
    rgb = np.stack([np.interp(t, np.linspace(0, 1, len(c)), c[:, i]) for i in range(3)], 1)
    return (rgb[:, ::-1] * 255).round().astype(np.uint8)


# Sequential one-hue ramp (dataviz reference blue, 700 to 100): low is dark, high is light.
HEIGHT_LUT = _ramp(["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"])


def kind_rgb(kind):
    return KIND_RGB.get(kind, UNKNOWN_RGB)


def part_label(p):
    s = p.id + (" (pinch only)" if p.grip == "pinch" else "")
    return s + (f" {p.score:.0%}" if p.score < 0.995 else "")


# --- part glyph geometry, shared by the 3D overlay and the 2D drawing ---

def _rot(k, v, th):
    """v rotated about unit axis k by each angle in th (Rodrigues), one row per angle."""
    c, s = np.cos(th)[:, None], np.sin(th)[:, None]
    return v * c + np.cross(k, v) * s + k * (k @ v) * (1 - c)


def _arc(center, axis, start, lo, hi):
    """The circle about `axis` through `center` that passes `start`, from angle lo to hi (rad)."""
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    n = max(8, int(abs(hi - lo) / math.radians(6)))
    return center + _rot(k, start - center, np.linspace(lo, hi, n))


def _ring(c, x, y, r, n=28):
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)[:, None]
    return c + r * (np.cos(th) * x + np.sin(th) * y)


def _rect(c, x, y, hx, hy):
    return np.array([c + a * hx * x + b * hy * y for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def _perp(d):
    p = np.cross(d, [1.0, 0, 0] if abs(d[0]) < 0.9 else [0, 1.0, 0])
    return p / np.linalg.norm(p)


_CON = mujoco.MjvGeom()


def _connector(type_, width, a, b):
    """mjv_initGeom's (size, pos, mat) for a capsule, arrow or line from a to b."""
    mujoco.mjv_connector(_CON, type_, width, np.asarray(a, float), np.asarray(b, float))
    size = np.array(_CON.size, float)  # x, y, z scales
    if type_ == G.mjGEOM_CAPSULE:  # mjv_initGeom takes a capsule's radius and half length
        size = size[[0, 2, 1]]
    return size, np.array(_CON.pos, float), np.array(_CON.mat, float).ravel()


def glyph(p):
    """Glyph geometry for a features.Part, in the arm frame.

    Returns (solids, outline, path, heads, anchor): translucent shapes hugging the part, as
    (type, size, pos, mat); a closed outline just above the surface; the motion path (press
    arrow, slide range, arc) or None, with arrowheads at (start, end); and the label anchor.
    Reads the meta keys device.truth() writes, which perception writes too (knob_radius,
    knob_height, fin_length, fin_width, fin_height, lever_len, lever_radius, angle, base_size,
    travel, corners), and falls back on p.size without them.
    """
    o, x, y, z, R = p.pos, p.x, p.T[:3, 1], p.normal, p.T[:3, :3]
    sx, sy, sz = p.size
    m = p.meta
    axis = p.axis if p.axis is not None else {"button": -z, "slider": x}.get(p.kind, z)
    lo, hi = p.range
    lift = z * 4e-4
    solids, path, heads, anchor = [], None, (False, True), o
    if p.kind in ("button", "dial", "knob"):
        r, h = m.get("knob_radius", max(sx, sy) / 2), m.get("knob_height", sz)
        solids.append((G.mjGEOM_CYLINDER, (r + 5e-4, h / 2 + 2e-4, 0), o - z * h / 2, R))
        outline = _ring(o + lift, x, y, r + 0.0015)
        if p.kind == "button":
            path = np.array([o - axis * 0.026, o - axis * 0.01])  # press arrow; its head ends 3 mm above the cap
        else:
            fh, fl = m.get("fin_height", 0.0), m.get("fin_length")
            if fl:
                solids.append((G.mjGEOM_BOX, (fl / 2 + 5e-4, m["fin_width"] / 2 + 5e-4, fh / 2 + 2e-4), o + z * fh / 2, R))
            if lo == hi == 0:
                lo, hi = -math.pi / 2, math.pi / 2
            # The Part doesn't say where the pointer is (a knob's x doesn't turn with it). Assume the
            # gap between the stops points down the panel, as on module W's devices and most real ones,
            # and work the pointer back from the range.
            k, g = axis / np.linalg.norm(axis), np.array([0, 0, -1.0])
            down = g - (g @ k) * k
            down = down / np.linalg.norm(down) if np.linalg.norm(down) > 1e-6 else x
            e = _rot(k, down, np.array([-((lo + hi) / 2 + math.pi)]))[0]
            c = o + z * 0.002
            path, heads = _arc(c, axis, c + e * (r + 0.005), lo, hi), (lo < 0, hi > 0)
            anchor = path[len(path) // 2]  # top of the arc, so the chip stays off the fin
    elif p.kind == "slider":
        solids.append((G.mjGEOM_BOX, (sx / 2 + 5e-4, sy / 2 + 5e-4, sz / 2 + 2e-4), o - z * sz / 2, R))
        outline = _rect(o + lift, x, y, sx / 2 + 0.0015, sy / 2 + 0.0015)
        if lo == hi == 0:
            lo, hi = -m.get("travel", 0.04) / 2, m.get("travel", 0.04) / 2
        c = o + z * 0.004
        path, heads = np.array([c + axis * lo, c + axis * hi]), (lo < -1e-4, hi > 1e-4)
    elif p.kind == "toggle":
        bh = m["base_size"][2] if "base_size" in m else 0.004
        tilt = abs(m.get("angle", math.radians(25)))  # angle is the signed lever angle
        L, lr = m.get("lever_len", max(sz, 0.012)), m.get("lever_radius", 0.0025)  # L runs to the tip's outer end
        lever = math.cos(tilt) * z + math.sin(tilt) * x
        solids += [(G.mjGEOM_BOX, (sx / 2, sy / 2, bh / 2), o - z * bh / 2, R),
                   (G.mjGEOM_CAPSULE, *_connector(G.mjGEOM_CAPSULE, lr + 5e-4, o, o + lever * (L - lr)))]
        outline = _rect(o + lift, x, y, sx / 2 + 0.0015, sy / 2 + 0.0015)
        th = np.linspace(tilt, -tilt, 10)[:, None]
        path, anchor = o + L * (np.cos(th) * z + np.sin(th) * x), o + lever * L  # the tip flips over
    elif p.kind == "door":
        outline = (np.asarray(m["corners"], float) if "corners" in m else _rect(o, x, y, sx / 2, sy / 2)) + lift
        solids.append((G.mjGEOM_CYLINDER, (0.009, max(sz, 0.001) / 2 + 2e-4, 0), o - z * sz / 2, R))
        path = np.array([o + z * 0.026, o + z * 0.01])  # press arrow onto the pad, which unlatches the door
    elif p.kind == "display":
        outline = _rect(o + lift, x, y, sx / 2, sy / 2)
        anchor = o + (y if y[2] > 0 else -y) * sy / 2  # top edge, so the chip stays off the readout
    else:
        solids.append((G.mjGEOM_BOX, (sx / 2, sy / 2, sz / 2), o - z * sz / 2, R))
        outline = _rect(o + lift, x, y, sx / 2, sy / 2)
    return solids, outline, path, heads, anchor


# --- 3D ---

class Overlay:
    """Glyphs in the arm frame. Build them, then write(scn) after every update_scene (the
    renderer rebuilds its scene each time). clear() starts over."""

    def __init__(self, max_points=3000):
        self.max_points = max_points
        self.clear()

    def clear(self):
        self.items = []   # (type, size, pos, mat, rgba): mjv_initGeom's arguments
        self.labels = []  # (pos, text, rgb)
        self.clouds = []  # (Nx3 points, Nx4 rgba, half size)

    def write(self, scn, labels=True, eye=None):
        """Append everything to scn, never past scn.maxgeom: glyphs first, then mjGEOM_LABEL
        labels (white in MuJoCo, whatever the colour), then points. Returns how many didn't fit.

        Points move one point size toward `eye` (default: the scene's camera) so they don't
        z-fight the surface they were measured on."""
        geoms, start, texts = scn.geoms, scn.ngeom, self.labels if labels else []
        if eye is None and scn.camera[0].frustum_near > 0:
            eye = np.array(mujoco.mjv_averageCamera(scn.camera[0], scn.camera[1]).pos, float)
        for args in self.items[:scn.maxgeom - scn.ngeom]:
            g = geoms[scn.ngeom]
            mujoco.mjv_initGeom(g, *args)
            g.category, g.emission, g.specular = DECOR, EMISSION, SPECULAR
            scn.ngeom += 1
        for pos, text, _ in texts[:scn.maxgeom - scn.ngeom]:
            g = geoms[scn.ngeom]
            mujoco.mjv_initGeom(g, G.mjGEOM_LABEL, _Z3, pos + LABEL_LIFT, _I9, np.ones(4, np.float32))
            g.label, g.category = text[:99], DECOR
            scn.ngeom += 1
        for xyz, rgba, half in self.clouds:
            if eye is not None:
                ray = eye - xyz
                xyz = xyz + ray * (2 * half / np.linalg.norm(ray, axis=1))[:, None]
            size = np.full(3, half)
            n = min(len(xyz), scn.maxgeom - scn.ngeom)
            for i in range(n):
                g = geoms[scn.ngeom + i]
                mujoco.mjv_initGeom(g, G.mjGEOM_BOX, size, xyz[i], _I9, rgba[i])
                g.category, g.emission, g.specular = DECOR, EMISSION, SPECULAR
            scn.ngeom += n
        return len(self.items) + len(texts) + sum(len(c[0]) for c in self.clouds) - (scn.ngeom - start)

    def _add(self, type_, size, pos, mat, rgba):
        self.items.append((type_, np.resize(np.asarray(size, float), 3), np.asarray(pos, float),
                           np.asarray(mat, float).ravel(), np.asarray(rgba, np.float32)))

    def _link(self, type_, width, a, b, rgba):
        self._add(type_, *_connector(type_, width, a, b), rgba)

    def points(self, xyz, rgb=None, size=0.0012, alpha=1.0):
        """Point cloud as small cubes (edge `size`, m), randomly thinned to about max_points (with
        a fixed seed, so redrawing the same cloud doesn't flicker). rgb: one colour, Nx3 colours
        (RGB order, 0..1 or 0..255), or None to colour by height."""
        xyz = np.asarray(xyz, float).reshape(-1, 3)
        if not len(xyz):
            return
        keep = np.random.default_rng(0).random(len(xyz)) < self.max_points / len(xyz)
        if rgb is None:
            z = xyz[keep, 2]
            c = HEIGHT_LUT[((z - z.min()) / max(np.ptp(z), 1e-9) * 255).astype(int), ::-1] / 255
        else:
            c = np.asarray(rgb)
            c = c / 255 if c.dtype == np.uint8 or c.max() > 1 else c.astype(float)
            c = np.broadcast_to(c[keep] if c.ndim == 2 else c, (keep.sum(), 3))
        self.clouds.append((xyz[keep], np.c_[c, np.full(len(c), alpha)].astype(np.float32), size / 2))

    def label(self, pos, text, rgb=INK):
        self.labels.append((np.asarray(pos, float), text, tuple(rgb[:3])))

    def line(self, a, b, rgba, width=2):
        """Line `width` pixels wide. MuJoCo multiplies its colour by the scene's lights (2x in the
        Rev B scene), so only white or saturated colours survive; tube() keeps the hue."""
        self._link(G.mjGEOM_LINE, width, a, b, rgba)

    def polyline(self, pts, rgba, width=2, closed=False):
        pts = np.asarray(pts, float)
        for a, b in zip(pts, np.roll(pts, -1, 0) if closed else pts[1:]):
            self.line(a, b, rgba, width)

    def tube(self, pts, rgba, radius=0.0012):
        """Shaded polyline made of capsules."""
        for a, b in zip(pts[:-1], pts[1:]):
            self._link(G.mjGEOM_CAPSULE, radius, a, b, rgba)

    def arrow(self, a, b, rgba, width=0.002):
        """3D arrow from a to b; width is the shaft radius (m)."""
        self._link(G.mjGEOM_ARROW, width, a, b, rgba)

    def arc(self, center, axis, start, angle, rgba, radius=0.0012, heads=(False, True)):
        """Tube along the circle about `axis` through `center` from point `start`, turning
        `angle` rad (right-hand rule), with arrowheads at (start, end)."""
        self._path(_arc(np.asarray(center, float), axis, np.asarray(start, float), 0, angle), rgba, heads, radius, axis)

    def _path(self, pts, rgba, heads, radius=0.0012, n=None):
        self.tube(pts, rgba, radius)
        for on, (i, j) in zip(heads, ((1, 0), (-2, -1))):
            if on:
                self.head(pts[j], pts[j] - pts[i], rgba, n=n)

    def head(self, base, d, rgba, length=0.007, width=0.0028, n=None):
        """Arrowhead from `base` pointing along d: two crossed triangles, one of them in the plane
        normal to n when given (MuJoCo's own arrow heads flatten into discs on short arrows)."""
        d = np.asarray(d, float) / np.linalg.norm(d)
        s = np.cross(n, d) if n is not None else np.zeros(3)
        s = s / np.linalg.norm(s) if np.linalg.norm(s) > 0.3 else _perp(d)
        for side in (s, np.cross(d, s)):
            for sgn in (1, -1):  # a mirrored half keeps the same normal, so both halves light alike
                self._add(G.mjGEOM_TRIANGLE, (length, width, 0), base, np.c_[d, sgn * side, np.cross(d, side)], rgba)

    def box(self, pos, half, rgba, mat=None):
        self._add(G.mjGEOM_BOX, half, pos, _I9 if mat is None else mat, rgba)

    def cylinder(self, pos, radius, half_height, rgba, mat=None):
        """Cylinder along mat's z axis (world z without mat)."""
        self._add(G.mjGEOM_CYLINDER, (radius, half_height, 0), pos, _I9 if mat is None else mat, rgba)

    def sphere(self, pos, radius, rgba):
        self._add(G.mjGEOM_SPHERE, (radius, 0, 0), pos, _I9, rgba)

    def frame(self, T, length=0.03, width=0.0012):
        """Red, green, blue arrows along a 4x4 pose's x, y, z."""
        for i, c in enumerate(((0.9, 0.25, 0.2), (0.3, 0.8, 0.2), (0.25, 0.45, 0.95))):
            self.arrow(T[:3, 3], T[:3, 3] + length * T[:3, i], (*c, 1), width)

    def frustum(self, T_base_cam, K, size, depth=0.08, rgba=(*INK, 1), width=2):
        """Camera pyramid out to `depth` (m); the small triangle marks image up."""
        w, h = size
        px = np.array([[0, 0], [w, 0], [w, h], [0, h], [0.4 * w, 0], [0.6 * w, 0], [0.5 * w, -0.15 * h]])
        ray = (np.linalg.inv(K) @ np.c_[px, np.ones(len(px))].T).T * depth
        c = ray @ T_base_cam[:3, :3].T + T_base_cam[:3, 3]
        for corner in c[:4]:
            self.line(T_base_cam[:3, 3], corner, rgba, width)
        self.polyline(c[:4], rgba, width, closed=True)
        self.polyline(c[4:], rgba, width, closed=True)

    def part(self, p, label=None, alpha=0.3):
        """Standard glyph for a features.Part: translucent shape, outline, motion arrow (for
        translations) or arc (for rotations), and a label, all in the kind's colour."""
        solids, outline, path, heads, anchor = glyph(p)
        rgb = kind_rgb(p.kind)
        for s in solids:
            self._add(*s, (*rgb, alpha))
        self.tube(np.vstack([outline, outline[:1]]), (*rgb, 1), 0.0005)
        if path is not None:
            self._path(path, (*rgb, 1), heads, n=p.normal)
        self.label(anchor, label or part_label(p), rgb)


_ghosts = {}  # id(model) -> (model, private MjData, arm body ids); holding the model keeps the id unique
_GEOM_FIELDS = ("type", "dataid", "objtype", "objid", "category", "matid", "texid", "texuniform", "texcoord",
                "segid", "size", "pos", "mat", "rgba", "emission", "specular", "shininess", "reflectance",
                "texrepeat", "label", "modelrbound")


def ghost(scn, model, qpos, rgba=GHOST):
    """Add a translucent copy of the arm at qpos to scn: robot.ARM_JOINTS angles (as IK returns
    them) or a full qpos. Uses a private MjData and keeps only the arm's geoms."""
    if id(model) not in _ghosts:
        root, arm = model.body("base").id, set()
        for b in range(model.nbody):
            a = b
            while a > 0 and a != root:
                a = model.body_parentid[a]
            if a == root:
                arm.add(b)
        _ghosts[id(model)] = (model, mujoco.MjData(model), arm)
    _, d, arm = _ghosts[id(model)]
    q = np.asarray(qpos, float)
    if len(q) == model.nq:
        d.qpos[:] = q
    else:
        d.qpos[[model.joint(j).qposadr[0] for j in robot.ARM_JOINTS]] = q
    mujoco.mj_kinematics(model, d)
    start = scn.ngeom
    mujoco.mjv_addGeoms(model, d, mujoco.MjvOption(), mujoco.MjvPerturb(), mujoco.mjtCatBit.mjCAT_DYNAMIC, scn)
    # That added every moving geom. Pack the arm's to the front of what was added and drop the
    # rest; the bindings can't assign a whole MjvGeom, so a kept one moves field by field.
    geoms, keep = scn.geoms, start
    for i in range(start, scn.ngeom):
        if geoms[i].objtype != mujoco.mjtObj.mjOBJ_GEOM or model.geom_bodyid[geoms[i].objid] not in arm:
            continue
        g = geoms[keep]
        if i != keep:
            for f in _GEOM_FIELDS:
                setattr(g, f, getattr(geoms[i], f))
        g.rgba, g.emission, g.category = rgba, 0.5, DECOR
        keep += 1
    scn.ngeom = keep


def renderer(model, width=1280, height=720, max_geom=15000):
    """Offscreen mujoco.Renderer; grows the model's offscreen buffer if it is too small."""
    v = model.vis.global_
    v.offwidth, v.offheight = max(v.offwidth, width), max(v.offheight, height)
    return mujoco.Renderer(model, height, width, max_geom)


def camera(lookat, distance, azimuth, elevation):
    """Free camera (degrees). For an orbit, step the azimuth each frame."""
    cam = mujoco.MjvCamera()
    cam.lookat[:] = lookat
    cam.distance, cam.azimuth, cam.elevation = distance, azimuth, elevation
    return cam


def scene_camera(scn, size):
    """K and T_base_cam (OpenCV convention: pixel centres at integers) of the view scn was last
    updated from, for an image of size (w, h). Lets 2D drawing line up with a 3D render."""
    # camera[0] and [1] are stereo eyes, ipd apart; a mono render uses their average
    c, (w, h) = mujoco.mjv_averageCamera(scn.camera[0], scn.camera[1]), size
    f = h * c.frustum_near / (c.frustum_top - c.frustum_bottom)
    K = np.array([[f, 0, (w - 1) / 2 - f * c.frustum_center / c.frustum_near],
                  [0, f, (h - 1) / 2 + f * (c.frustum_top + c.frustum_bottom) / 2 / c.frustum_near], [0, 0, 1]])
    fwd, up = np.array(c.forward, float), np.array(c.up, float)
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = np.c_[np.cross(fwd, up), -up, fwd], c.pos
    return K, T


_SHOWN = np.array([1, 1, 1, 0, 0, 0], np.uint8)  # the geom groups a default view draws


def _hidden(m, d, eye, p, see_through=(), tol=0.015):
    """True when the front face of a model geom (other than see_through ids) is more than tol (m)
    in front of p, seen from eye. The tolerance keeps the label of a part under the probe's 12 mm
    pad. Back faces don't count, as the renderer culls them (a camera inside the arm sees out)."""
    v, gid, n, t = p - eye, np.zeros(1, np.int32), np.zeros(3), 0.0
    stop = 1 - tol / np.linalg.norm(v)  # p is at eye + 1 * v
    while True:
        x = mujoco.mj_ray(m, d, eye + t * v, v, _SHOWN, 1, -1, gid, n)
        if x < 0 or t + x > stop:
            return False
        if n @ v < 0 and gid[0] not in see_through:
            return True
        t += x + 1e-4  # carry on past a back face or a see-through geom


def _helper_geoms(m):
    """The IK follow-mode sphere: a sim helper, not on the rig, so renders leave it out."""
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "target")
    return set() if b < 0 else {int(m.body_geomadr[b])}


def render(r, data, cam, overlay=None, ghosts=(), labels2d=True, fade=(), fade_alpha=0.2):
    """One BGR frame from renderer r: update, add the overlay and ghost arms ((qpos, rgba)
    pairs), render. With labels2d the overlay's labels are drawn as 2D chips instead of
    MuJoCo's plain white labels, leaving out those hidden behind a model geom (the arm, say).
    Model geoms whose ids are in `fade` (e.g. world.device_geom_ids) are drawn see-through
    and cast no shadow, so a point cloud of them shows."""
    r.update_scene(data, cam)
    fade = set(np.ravel(fade).tolist())
    hide = _helper_geoms(r.model)
    for g in r.scene.geoms[:r.scene.ngeom]:
        if g.objtype == mujoco.mjtObj.mjOBJ_GEOM and g.objid in fade | hide:
            g.rgba[3] *= 0 if g.objid in hide else fade_alpha
            g.category = DECOR
    fade |= hide
    if overlay is not None:
        overlay.write(r.scene, labels=not labels2d)
    for q, rgba in ghosts:
        ghost(r.scene, r.model, q, rgba)
    img = cv2.cvtColor(r.render(), cv2.COLOR_RGB2BGR)
    if overlay is not None and labels2d:
        K, T = scene_camera(r.scene, (r.width, r.height))
        draw_labels(img, [l for l in overlay.labels if not _hidden(r.model, data, T[:3, 3], l[0], fade)], K, T)
    return img


def show_in_viewer(viewer, overlay=None, ghosts=(), images=(), width=360):
    """Picture-in-picture for a passive mujoco.viewer handle (3.17 API), then call viewer.sync().

    The overlay and ghost arms go into viewer.user_scn (100000 geoms). BGR images are pinned
    down the right edge with set_images, which wants RGB arrays exactly the size of an MjrRect
    (left, bottom, width, height; origin bottom left). Text: viewer.set_texts((font, gridpos,
    left, right)); plots: viewer.set_figures((rect, MjvFigure)), as demo.Overlay does.
    """
    with viewer.lock():
        viewer.user_scn.ngeom = 0
        if overlay is not None:
            frame = np.zeros((4, 3))  # camera position, forward, up, right
            mujoco.mjv_cameraFrame(*frame, viewer.d, viewer.cam)
            overlay.write(viewer.user_scn, eye=frame[0])
        for q, rgba in ghosts:
            ghost(viewer.user_scn, viewer.m, q, rgba)
    vp = viewer.viewport
    if vp is None or not images:
        return
    rects, top = [], vp.height - 10
    for img in images:
        h = round(img.shape[0] * width / img.shape[1])
        top -= h
        rects.append((mujoco.MjrRect(vp.width - width - 10, top, width, h),
                      cv2.cvtColor(cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)))
        top -= 10
    viewer.set_images(rects)


# --- 2D ---

_FONTS = {"regular": ("segoeui.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "arial.ttf"),
          "bold": ("seguisb.ttf", "segoeuib.ttf", "HelveticaNeue.ttc", "DejaVuSans-Bold.ttf", "arialbd.ttf"),
          "mono": ("consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf", "cour.ttf")}


@functools.lru_cache(None)
def _font(size, kind="regular"):
    for name in _FONTS[kind]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _text(img, items):
    """Draw (xy, text, rgb, size, font kind, PIL anchor) items onto a BGR image in one PIL pass."""
    if items:
        pil = Image.fromarray(img)
        d = ImageDraw.Draw(pil)
        for xy, s, rgb, size, kind, anchor in items:
            d.text(xy, s, fill=bgr(rgb), font=_font(size, kind), anchor=anchor)
        img[:] = np.asarray(pil)


def _px(uv):
    return np.round(np.asarray(uv) * 16).astype(np.int32)  # with shift=4: sub-pixel, anti-aliased


def _head2d(img, a, b, col, size=9):
    d = (b - a) / max(np.linalg.norm(b - a), 1e-9)
    n = np.array([-d[1], d[0]])
    cv2.fillPoly(img, [_px([b + d * 2, b - d * size + n * size * 0.55, b - d * size - n * size * 0.55])],
                 col, cv2.LINE_AA, 4)


def project(pts, K, T_base_cam):
    """Arm-frame points to pixels (Nx2) and their depth along the optical axis (N)."""
    T = np.linalg.inv(T_base_cam)
    c = np.asarray(pts, float) @ T[:3, :3].T + T[:3, 3]
    with np.errstate(divide="ignore", invalid="ignore"):
        return c[:, :2] / c[:, 2:] * [K[0, 0], K[1, 1]] + K[:2, 2], c[:, 2]


def draw_labels(img, labels, K, T_base_cam, size=16):
    """Chips with leader lines for (pos, text, rgb) labels, placed so they don't overlap each
    other or any anchor (in place)."""
    if not labels:
        return img
    font, H, W = _font(size, "bold"), *img.shape[:2]
    uv, depth = project([l[0] for l in labels], K, T_base_cam)
    seen = [(l, a) for l, a, z in zip(labels, uv, depth) if z > 0 and 0 <= a[0] < W and 0 <= a[1] < H]
    placed = [(a[0] - 5, a[1] - 5, 10, 10) for _, a in seen]  # keep chips off the anchor dots

    def free(x, y, w, h):
        return 0 <= x <= W - w and 0 <= y <= H - h and not any(
            x < px + pw + 4 and px < x + w + 4 and y < py + ph + 4 and py < y + h + 4 for px, py, pw, ph in placed)

    items, chips = [], []
    pad, off = round(size * 0.7), round(size * 0.8)
    for (_, text, rgb), a in sorted(seen, key=lambda t: t[1][0]):
        w, h = int(font.getlength(text)) + 2 * pad, round(size * 1.5)
        u, v = int(a[0]), int(a[1])
        # the four corners around the anchor, then the same further out
        spots = [(u + dx, v + dy + s * k * (h + 4)) for k in range(10)
                 for dx, dy, s in ((off, -off - h, -1), (-off - w, -off - h, -1), (off, off, 1), (-off - w, off, 1))]
        x0, y0 = next((p for p in spots if free(*p, w, h)), (min(max(u + off, 0), W - w), min(max(v - off - h, 0), H - h)))
        placed.append((x0, y0, w, h))
        chips.append((a, x0, y0, w, h, rgb))
        items.append(((x0 + pad, y0 + h // 2), text, INK, size, "bold", "lm"))
    bg = img.copy()
    for a, x0, y0, w, h, rgb in chips:
        cv2.rectangle(bg, (x0, y0), (x0 + w, y0 + h), bgr(SURFACE), -1)
    cv2.addWeighted(bg, 0.85, img, 0.15, 0, img)
    for a, x0, y0, w, h, rgb in chips:
        corner = np.array([x0 if x0 > a[0] else x0 + w, y0 + h if y0 < a[1] else y0])  # nearest chip corner
        cv2.line(img, tuple(_px(a)), tuple(_px(corner)), bgr(rgb), 1, cv2.LINE_AA, 4)
        cv2.circle(img, tuple(_px(a)), 4 * 16, bgr(SURFACE), -1, cv2.LINE_AA, 4)
        cv2.circle(img, tuple(_px(a)), 3 * 16, bgr(rgb), -1, cv2.LINE_AA, 4)
        cv2.rectangle(img, (x0, y0), (x0 + max(2, size // 4), y0 + h), bgr(rgb), -1)
    _text(img, items)
    return img


def draw_parts(img, parts, K, T_base_cam, width=None, labels=True, alpha=0.3):
    """Parts drawn onto a copy of a BGR camera image: shaded outline, motion path, label chip.
    width: resize first (scaling K) so lines and text stay crisp at the size it is shown."""
    if width:
        s = width / img.shape[1]
        img = cv2.resize(img, (width, round(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        K = np.diag([s, s, 1.0]) @ K
    else:
        img = img.copy()
    fill, strokes, labs = img.copy(), [], []
    for p in parts:
        _, outline, path, heads, anchor = glyph(p)
        col = bgr(kind_rgb(p.kind))
        uv, z = project(outline, K, T_base_cam)
        if (z <= 0).any():
            continue
        cv2.fillPoly(fill, [_px(uv)], col, cv2.LINE_AA, 4)
        strokes.append((uv, True, col, (False, False)))
        if path is not None:
            puv, pz = project(path, K, T_base_cam)
            if (pz > 0).all():
                strokes.append((puv, False, col, heads))
        labs.append((anchor, part_label(p), kind_rgb(p.kind)))
    cv2.addWeighted(fill, alpha, img, 1 - alpha, 0, img)
    for uv, closed, col, heads in strokes:
        cv2.polylines(img, [_px(uv)], closed, col, 2, cv2.LINE_AA, 4)
        if heads[0]:
            _head2d(img, uv[1], uv[0], col)
        if heads[1]:
            _head2d(img, uv[-2], uv[-1], col)
    if labels:
        draw_labels(img, labs, K, T_base_cam, size=int(np.clip(img.shape[1] / 42, 11, 16)))
    return img


def colorize_height(h, lo=None, hi=None, cell=None):
    """Height map (2D, NaN where empty) to BGR, dark (low) to light (high). With `cell` (grid
    spacing, m) it is also hill-shaded, lit from the top left, so mm-scale edges stand out.
    For a depth image pass -depth with NaN where invalid, so near is light."""
    ok = np.isfinite(h)
    vals = h[ok] if ok.any() else np.zeros(1)  # an empty map comes out all background
    lo = np.percentile(vals, 1) if lo is None else lo
    hi = np.percentile(vals, 99) if hi is None else hi
    filled = np.where(ok, h, lo)
    img = HEIGHT_LUT[(np.clip((filled - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(int)].astype(np.float32)
    if cell:
        gy, gx = np.gradient(filled, cell)
        img *= np.clip((1 + gx + gy) / np.sqrt(1 + gx ** 2 + gy ** 2), 0.4, 1.4)[..., None]
    img[~ok] = bgr(SURFACE)
    return np.clip(img, 0, 255).astype(np.uint8)


def _fit(img, w, h):
    """img letterboxed into w x h on the surface colour."""
    s = min(w / img.shape[1], h / img.shape[0])
    small = cv2.resize(img, (max(1, round(img.shape[1] * s)), max(1, round(img.shape[0] * s))),
                       interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    out = np.full((h, w, 3), bgr(SURFACE), np.uint8)
    y, x = (h - small.shape[0]) // 2, (w - small.shape[1]) // 2
    out[y:y + small.shape[0], x:x + small.shape[1]] = small
    return out


def _clip(s, font, width):
    """s, cut short with an ellipsis if it is wider than width px."""
    full = font.getlength(s)
    if full <= width:
        return s
    n = int(len(s) * width / full)  # first guess, then back off until the ellipsis fits too
    while n > 0 and font.getlength(s[:n] + "…") > width:
        n -= 1
    return s[:n] + "…"


class Dashboard:
    """1920x1080 video frames: a title bar, the main 3D view, a column of labelled camera panels
    with the part-kind legend, and a strip with the scrolling log and the test plan."""

    W, H = 1920, 1080
    MAIN = (16, 80, 1408, 792)       # x, y, w, h: render the main view at 1408x792 to skip a resize
    PANEL_X, PANEL_W, PANEL_H = 1440, 464, 261

    def __init__(self, title, subtitle=""):
        # status: title-bar chip, with a verdict-coloured dot when it starts with one ("PASS 7/7")
        self.title, self.subtitle, self.status = title, subtitle, ""
        self.lines = deque(maxlen=200)
        self.plan = []  # (text, state): state "" (to do), "run", or a verdict (PASS, FAIL, ...)

    def log(self, text, t=None):
        self.lines.append(text if t is None else f"{t:6.1f}  {text}")

    def frame(self, main, panels=(), t=None):
        """Compose one frame. main: BGR 3D view; panels: up to 3 (title, BGR image) pairs."""
        img = np.full((self.H, self.W, 3), bgr(PAGE), np.uint8)
        txt = []
        # title bar
        cv2.rectangle(img, (0, 0), (self.W, 63), bgr(SURFACE), -1)
        cv2.line(img, (0, 64), (self.W, 64), bgr(HAIRLINE), 1)
        txt.append(((24, 32), self.title, INK, 28, "bold", "lm"))
        txt.append(((36 + _font(28, "bold").getlength(self.title), 34), self.subtitle, INK2, 18, "regular", "lm"))
        right = self.W - 24
        if t is not None:
            txt.append(((right, 32), f"t = {t:.1f} s", MUTED, 18, "mono", "rm"))
            right -= 150
        if self.status:
            w = int(_font(16, "bold").getlength(self.status)) + 36
            cv2.rectangle(img, (right - w, 18), (right, 46), bgr(HAIRLINE), -1)
            dot = VERDICT_RGB.get(self.status.split()[0], INK)
            cv2.circle(img, (right - w + 14, 32), 5, bgr(dot), -1, cv2.LINE_AA)
            txt.append(((right - w + 26, 32), self.status, INK, 16, "bold", "lm"))
            right -= w
        self.title_right = right  # where the title bar's right-hand items start, for anything drawn beside them
        # main view
        x, y, w, h = self.MAIN
        img[y:y + h, x:x + w] = main if main.shape[:2] == (h, w) else _fit(main, w, h)
        cv2.rectangle(img, (x - 1, y - 1), (x + w, y + h), bgr(HAIRLINE), 1)
        # camera panels
        py = y
        for title, pimg in panels[:3]:
            txt.append(((self.PANEL_X, py + 12), title, INK2, 15, "bold", "lm"))
            py += 28
            img[py:py + self.PANEL_H, self.PANEL_X:self.PANEL_X + self.PANEL_W] = _fit(pimg, self.PANEL_W, self.PANEL_H)
            cv2.rectangle(img, (self.PANEL_X - 1, py - 1), (self.PANEL_X + self.PANEL_W, py + self.PANEL_H), bgr(HAIRLINE), 1)
            py += self.PANEL_H + 12
        # part-kind legend
        ly = self.H - 16 - 70
        txt.append(((self.PANEL_X, ly + 8), "PART KINDS", INK2, 14, "bold", "lm"))
        for i, (kind, rgb) in enumerate(KIND_RGB.items()):
            lx, lyy = self.PANEL_X + (i % 4) * 116, ly + 32 + (i // 4) * 26
            cv2.rectangle(img, (lx, lyy - 6), (lx + 12, lyy + 6), bgr(rgb), -1)
            txt.append(((lx + 20, lyy), kind, INK, 15, "regular", "lm"))
        # log and plan strip
        sy, sh = y + h + 16, self.H - 16 - (y + h + 16)
        cv2.rectangle(img, (x, sy), (x + w, sy + sh), bgr(SURFACE), -1)
        cv2.rectangle(img, (x - 1, sy - 1), (x + w, sy + sh), bgr(HAIRLINE), 1)
        split = x + 820
        cv2.line(img, (split, sy + 12), (split, sy + sh - 12), bgr(HAIRLINE), 1)
        txt.append(((x + 16, sy + 18), "LOG", INK2, 14, "bold", "lm"))
        rows = (sh - 44) // 22
        lines = list(self.lines)[-rows:]
        for i, line in enumerate(lines):
            fade = (len(lines) - 1 - i) / max(rows - 1, 1)
            col = tuple(a + (b - a) * fade for a, b in zip(INK, MUTED))
            txt.append(((x + 16, sy + 44 + i * 22), _clip(line, _font(15, "mono"), split - x - 32), col, 15, "mono", "lm"))
        self._plan(img, txt, split + 16, sy, x + w - 16, rows)
        _text(img, txt)
        return img

    def _plan(self, img, txt, x0, y0, x1, rows):
        done = sum(1 for _, s in self.plan if s not in ("", "run"))
        txt.append(((x0, y0 + 18), f"TEST PLAN  {done}/{len(self.plan)}", INK2, 14, "bold", "lm"))
        first = next((i for i, (_, s) in enumerate(self.plan) if s in ("", "run")), len(self.plan))
        lo = max(0, min(first - 1, len(self.plan) - rows))
        for i, (text, state) in enumerate(self.plan[lo:lo + rows], lo):
            yy = y0 + 44 + (i - lo) * 22
            label = "RUNNING" if state == "run" else state
            w = int(_font(12, "bold").getlength(label)) + 16 if state else 0
            txt.append(((x0, yy), f"{i + 1:2d}", MUTED, 15, "mono", "lm"))
            txt.append(((x0 + 34, yy), _clip(text, _font(15), x1 - w - 12 - x0 - 34), INK if state == "run" else INK2,
                        15, "regular", "lm"))
            if not state:
                continue
            if state == "run":
                cv2.rectangle(img, (x1 - w, yy - 9), (x1, yy + 9), bgr(INK), 1)
            else:
                cv2.rectangle(img, (x1 - w, yy - 9), (x1, yy + 9), bgr(VERDICT_RGB.get(state, MUTED)), -1)
            ink = (0.04, 0.04, 0.04) if state == "ABORTED" else INK if state == "run" else (1, 1, 1)
            txt.append(((x1 - w / 2, yy), label, ink, 12, "bold", "mm"))


class Video:
    """MP4 writer for BGR frames of one size: H.264 through imageio-ffmpeg, else OpenCV's mp4v."""

    def __init__(self, path, fps=30):
        self.path, self.fps, self.frames = path, fps, 0
        self._ff = self._cv = None

    def write(self, img):
        if self._ff is None and self._cv is None:
            h, w = img.shape[:2]
            try:
                import imageio_ffmpeg
                self._ff = imageio_ffmpeg.write_frames(self.path, (w, h), pix_fmt_in="bgr24", fps=self.fps,
                                                       quality=7, macro_block_size=2)
                self._ff.send(None)
            except (ImportError, RuntimeError, OSError):
                self._cv = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
        if self._ff is not None:
            self._ff.send(np.ascontiguousarray(img))
        else:
            self._cv.write(img)
        self.frames += 1

    def close(self):
        if self._ff is not None:
            self._ff.close()
        if self._cv is not None:
            self._cv.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
