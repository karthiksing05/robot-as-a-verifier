"""The showcase: an unknown device found, scanned, understood and tested, with no CAD and no tags.

    python explore.py                                   preset C, live viewer
    python explore.py --seed 7 --placement random       a random device, moved on the desk
    python explore.py --headless --record runs/explore.mp4   1920x1080 at 30 fps, no window
    python explore.py --ideal                           no sensor noise, no joint offsets
    python explore.py --slop --offsets 2                soft servos with gear play, +-2 deg joint offsets
    python explore.py --slop --stiffness 18             softer servos (robot.SERVO_NM_PER_RAD)
    python explore.py --slop --sensing current          no force sensor: contact estimated from the servos
    python explore.py --slop --sensing tactile          a SensX 25 pressure pad on the probe's face, servos across it
    python explore.py --slop --sensing loadcell         a load cell behind the probe (HX711, 80 Hz), servos across it
    python explore.py --no-refine                       act on the scanned parts without a last look
    python explore.py --depth [--stereo]                the earlier pipeline, with a D405 depth camera on the wrist
    python explore.py --slop --sensing tactile --real-driver   driven through real_arm.RealArm on a simulated motor bus

By default the robot has what the team's rig has: an iPhone on a tripod, a cheap USB RGB camera on the
wrist (no depth) and the probe's sense of contact. STAGES runs the story: intro; survey (the phone) and
scan (a USB frame at each wrist view and a partner 15 mm aside), by rgbperceive.perceive_rgb; segment (the
camera poses, the orthophoto assembling on the panel, OWLv2's boxes and SAM's outlines); map (plane-sweep
heights, then each part's kind and why); touch (touch.touch_plane taps bare panel for the plane in the
probe's frame, touch.touch_parts taps part tops); plan (ghost arms preview each part's first step); test
(affordances.run_plan with touch.make_refine's last look at each approach pose, shown as that USB frame
with SAM's outline and the part moving onto it) and report. With --depth it is the earlier story:
perceive.perceive's scan with the cloud growing live, the reveal (cloud, plane, height map, segments,
parts), and perceive.refine in the test. This file only directs the camera, draws and narrates. Frames
come from arm.on_tick at the video rate, so they follow sim time (the USB scan plays at SCAN_SPEED, touch
at TOUCH_SPEED and the test at TEST_SPEED, each SLOP_PACE times faster with soft servos), Show.hold()
ticks the arm in place for pauses, and Show.still() draws with the sim paused (each last look, which the
robot spends in SAM).

The film uses sim truth the robot never sees. The camera frames shots on the device's true extent.
And with joint calibration error, everything the wrist camera measured sits in the arm's believed
frame, up to 2 cm from the real device under +-2 deg offsets, so the overlay is drawn moved to
where it really is: scanned geometry by the camera's error at the first wrist view (for the USB scan,
at its bundle-adjusted pose), and a part that refine() has measured by the fingertip's error at that
step's approach pose, which is where the probe really goes for it. Without refine, a step's part is
drawn by the fingertip's error at the step's contact pose, so its glyph shows where the pad will land.
Ghost arms are posed at the true joint angles their commands reach. Wrist capture frustums, touch
markers and the touch-offs' triangle sit where the camera and probe really were, and the orthophoto
laid on the panel is cut to the panel's true outline.
"""
import argparse
import math
import os
import re
import sys
import time
import traceback
from collections import deque

import cv2
import mujoco
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))  # the pipeline, rig.py
import affordances  # noqa: E402
import pipeline  # noqa: E402
import rgbperceive  # noqa: E402
import robot  # noqa: E402
import sim_rig  # noqa: E402
import skills  # noqa: E402
import viz  # noqa: E402

FPS = 30
MAIN_W, MAIN_H = viz.Dashboard.MAIN[2:]
PANEL_W, PANEL_H = viz.Dashboard.PANEL_W, viz.Dashboard.PANEL_H
STAGE_NAMES = ("SURVEY", "SCAN", "SEGMENT", "MAP", "TOUCH", "PLAN", "TEST", "REPORT")
DEPTH_STAGE_NAMES = ("SURVEY", "SCAN", "MAP", "PLAN", "TEST", "REPORT")
PARK_TIP, PARK_AXIS = (0.05, -0.20, 0.05), (0.3, -0.5, -0.8)  # the arm off to its right, clear of the panel
MAX_POINTS = 7000
H_RANGE = (-0.001, 0.012)  # height colour scale above the panel (m)
SCAN_SPEED = 2   # the USB scan settles twice per view
TOUCH_SPEED = 8  # each touch creeps the last few mm at 2 mm/s
TEST_SPEED = 3   # the guarded pushes are slow: the test plays at 3x, keeping the film near two minutes
SLOP_PACE = 2    # soft servos take about twice as long to settle on each pose: the scan, touch and test play
                 # this much faster again
LOOK_S = 1.0     # video seconds on each last look whose part refine moved (half that when it didn't)
GHOST = (*viz.GHOST[:3], 0.2)  # one preview arm per step, lighter than viz's default


def fit(pts, azimuth, elevation, fill=0.8, shift=0.0, fovy=45.0):
    """Look-at point and distance of a free camera that frames pts from (azimuth, elevation),
    filling `fill` of the view; shift > 0 moves them right by that fraction of the half width
    (keep fill + |shift| under 1 or they leave the frame)."""
    a, e = math.radians(azimuth), math.radians(elevation)
    fwd = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    up = np.array([-math.sin(e) * math.cos(a), -math.sin(e) * math.sin(a), math.cos(e)])
    right = np.cross(fwd, up)
    pts = np.asarray(pts, float).reshape(-1, 3)
    c = (pts.min(0) + pts.max(0)) / 2
    x, y = (pts - c) @ right, (pts - c) @ up
    c = c + right * (x.max() + x.min()) / 2 + up * (y.max() + y.min()) / 2  # centred on screen
    rel = pts - c
    tan_v = math.tan(math.radians(fovy) / 2)
    tan_h = tan_v * MAIN_W / MAIN_H
    dist = float(np.max(np.maximum(np.abs(rel @ right) / tan_h, np.abs(rel @ up) / tan_v) / fill - rel @ fwd))
    return c - right * shift * dist * tan_h, dist


class Director:
    """A free camera that glides to each new shot on a critically damped spring, and can orbit."""

    def __init__(self, fovy):
        self.fovy, self.x, self.v = fovy, None, np.zeros(6)

    def shot(self, pts, azimuth, elevation, t, fill=0.8, orbit=0.0, shift=0.0):
        """Frame pts from (azimuth, elevation) in degrees, then orbit at `orbit` deg/s."""
        lookat, dist = fit(pts, azimuth, elevation, fill, shift, self.fovy)
        self.goal, self.orbit, self.t0 = np.r_[lookat, dist, azimuth, elevation], orbit, t
        if self.x is None:
            self.x = self.goal.copy()
        self.goal[4] = self.x[4] + (self.goal[4] - self.x[4] + 180) % 360 - 180  # the short way round

    def camera(self, t, dt, w=2.2):
        goal = self.goal + [0, 0, 0, 0, self.orbit * (t - self.t0), 0]
        self.v += (w * w * (goal - self.x) - 2 * w * self.v) * dt
        self.x = self.x + self.v * dt
        return viz.camera(self.x[:3], *self.x[3:])


def height_rgb(h):
    """RGB uint8 colours (viz.HEIGHT_LUT, dark low to light high) for heights above the panel."""
    lo, hi = H_RANGE
    return viz.HEIGHT_LUT[(np.clip((h - lo) / (hi - lo), 0, 1) * 255).astype(int), ::-1]


def relief(frame):
    """A wrist depth image as height above the panel, hill-shaded. 1/z is linear in pixel
    coordinates for any plane. The fit starts on the nearest 40% of pixels (the panel is nearer
    than the desk around it) and is redone twice on the 60% that fit it best."""
    ok = frame.depth > 0
    v, u = np.nonzero(ok)
    A, b = np.c_[u, v, np.ones(len(u))], 1 / frame.depth[ok]
    keep = (b > np.percentile(b, 60)) & (np.arange(len(b)) % 4 == 0)
    for _ in range(2):
        coef = np.linalg.lstsq(A[keep], b[keep], rcond=None)[0]
        r = np.abs(A @ coef - b)
        keep &= r < np.percentile(r[keep], 60)
    h = np.full(ok.shape, np.nan, np.float32)
    h[ok] = 1 / (A @ coef) - frame.depth[ok]
    return viz.colorize_height(h, *H_RANGE, cell=np.median(frame.depth[ok]) / frame.K[0, 0])


def parallax(a, b, survey):
    """Wrist frames a and b as a red-cyan pair, b warped onto a through the survey's panel plane: the panel's
    print lines up, and whatever stands off the panel shows double, the more the taller it is."""
    T, (u0, u1, v0, v1) = survey["panel"], survey["extent"]
    X = T[:3, 3] + np.array([(u, v, 0.0) for u in (u0, u1) for v in (v0, v1)]) @ T[:3, :3].T
    H = cv2.getPerspectiveTransform(*(np.float32(viz.project(X, f.K, f.T_base_cam)[0]) for f in (b, a)))
    gb = cv2.cvtColor(cv2.warpPerspective(b.rgb, H, a.rgb.shape[1::-1]), cv2.COLOR_BGR2GRAY)
    return cv2.merge([gb, gb, cv2.cvtColor(a.rgb, cv2.COLOR_BGR2GRAY)])


def crop(img, frame, pts, margin=1.3):
    """img (frame's size) cut around pts (arm frame) to a panel's shape and size, and the K to
    draw on it with: the device is small in the iPhone's wide view."""
    uv, _ = viz.project(pts, frame.K, frame.T_base_cam)
    H, W = img.shape[:2]
    h = min(max(np.ptp(uv[:, 1]), np.ptp(uv[:, 0]) * PANEL_H / PANEL_W) * margin, H)
    w = h * PANEL_W / PANEL_H
    x0 = int(np.clip((uv[:, 0].min() + uv[:, 0].max() - w) / 2, 0, W - w))
    y0 = int(np.clip((uv[:, 1].min() + uv[:, 1].max() - h) / 2, 0, H - h))
    s = PANEL_W / w
    K = np.diag([s, s, 1.0]) @ (frame.K - [[0, 0, x0], [0, 0, y0], [0, 0, 0]])
    return cv2.resize(img[y0:y0 + round(h), x0:x0 + round(w)], (PANEL_W, PANEL_H), interpolation=cv2.INTER_LINEAR), K


def site_pose(d, site):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = d.site_xmat[site].reshape(3, 3), d.site_xpos[site]
    return T


def add_moved(ov, src, T):
    """Append overlay src's glyphs, labels and points to ov, moved by the rigid transform T."""
    R, t = T[:3, :3], T[:3, 3]
    ov.items += [(kind, size, R @ p + t, (R @ m.reshape(3, 3)).ravel(), rgba) for kind, size, p, m, rgba in src.items]
    ov.labels += [(R @ p + t, text, rgb) for p, text, rgb in src.labels]
    ov.clouds += [(xyz @ R.T + t, rgba, half) for xyz, rgba, half in src.clouds]


def label_parts(img, parts, K, T, named=None, hidden=None, size=16):
    """Name (part, M) pairs, each part moved by the rigid 4x4 M, in camera (K, T)'s image, in place.
    viz.draw_labels' chips and spots (clear of each other and of the anchor dots), plus one rule
    where there is room: clear of the other parts' glyphs, so no chip covers a control or the LCD.
    named: the part ids to name (default all); hidden(pos) True leaves that anchor's chip out."""
    H, W = img.shape[:2]
    font, pad, off, h = viz._font(size, "bold"), round(size * 0.7), round(size * 0.8), round(size * 1.5)
    cover, labels = np.zeros((H, W), np.uint8), []  # cover: how many glyphs lie on each pixel
    for p, M in parts:
        _, outline, _, _, anchor = viz.glyph(p)
        pts = np.vstack([anchor, outline]) @ M[:3, :3].T + M[:3, 3]
        uv, z = viz.project(pts, K, T)
        if (z <= 0).any():
            continue
        own = cv2.fillPoly(np.zeros((H, W), np.uint8), [np.round(uv[1:]).astype(np.int32)], 1)
        cover += own
        if (named is None or p.id in named) and 0 <= uv[0, 0] < W and 0 <= uv[0, 1] < H and not (hidden and hidden(pts[0])):
            labels.append((uv[0], viz.part_label(p), viz.kind_rgb(p.kind), own))
    if not labels:
        return img
    placed = [(a[0] - 5, a[1] - 5, 10, 10) for a, *_ in labels]

    def free(x, y, w, own):
        if not (0 <= x <= W - w and 0 <= y <= H - h) or any(
                x < px + pw + 4 and px < x + w + 4 and y < py + ph + 4 and py < y + h + 4 for px, py, pw, ph in placed):
            return False
        box = np.s_[max(y - 3, 0):y + h + 3, max(x - 3, 0):x + w + 3]
        return own is None or not (cover[box] > own[box]).any()  # own None: glyphs don't count

    items, chips = [], []
    for a, text, rgb, own in sorted(labels, key=lambda l: l[0][0]):
        w, u, v = int(font.getlength(text)) + 2 * pad, int(a[0]), int(a[1])
        # viz's spots: the four corners around the anchor, then the same further out
        spots = [(u + dx, v + dy + s * k * (h + 4)) for k in range(10)
                 for dx, dy, s in ((off, -off - h, -1), (-off - w, -off - h, -1), (off, off, 1), (-off - w, off, 1))]
        x0, y0 = next((p for o in (own, None) for p in spots if free(*p, w, o)),
                      (min(max(u + off, 0), W - w), min(max(v - off - h, 0), H - h)))
        placed.append((x0, y0, w, h))
        chips.append((a, x0, y0, w, rgb))
        items.append(((x0 + pad, y0 + h // 2), text, viz.INK, size, "bold", "lm"))
    bg = img.copy()  # drawn as viz.draw_labels draws them
    for a, x0, y0, w, rgb in chips:
        cv2.rectangle(bg, (x0, y0), (x0 + w, y0 + h), viz.bgr(viz.SURFACE), -1)
    cv2.addWeighted(bg, 0.85, img, 0.15, 0, img)
    for a, x0, y0, w, rgb in chips:
        corner = np.array([x0 if x0 > a[0] else x0 + w, y0 + h if y0 < a[1] else y0])  # nearest chip corner
        cv2.line(img, tuple(viz._px(a)), tuple(viz._px(corner)), viz.bgr(rgb), 1, cv2.LINE_AA, 4)
        cv2.circle(img, tuple(viz._px(a)), 4 * 16, viz.bgr(viz.SURFACE), -1, cv2.LINE_AA, 4)
        cv2.circle(img, tuple(viz._px(a)), 3 * 16, viz.bgr(rgb), -1, cv2.LINE_AA, 4)
        cv2.rectangle(img, (x0, y0), (x0 + max(2, size // 4), y0 + h), viz.bgr(rgb), -1)
    viz._text(img, items)
    return img


def draw_parts(img, parts, K, T, width=None):
    """viz.draw_parts for (part, M) pairs, each part moved by the rigid 4x4 M, named by label_parts."""
    if width:
        s = width / img.shape[1]
        img, K = cv2.resize(img, (width, round(img.shape[0] * s)), interpolation=cv2.INTER_AREA), np.diag([s, s, 1.0]) @ K
    for p, M in parts:
        img = viz.draw_parts(img, [p], K, np.linalg.inv(M) @ T, labels=False)
    return label_parts(img, parts, K, T, size=int(np.clip(img.shape[1] / 42, 11, 16)))


def box_edges(c):
    """The 12 edges of a box given as 8 corners in any order, with a flat top and bottom."""
    low, edges = c[:, 2] < c[:, 2].mean(), set()
    for i in range(8):
        level = sorted((j for j in range(8) if j != i and low[j] == low[i]), key=lambda j: np.linalg.norm(c[j] - c[i]))
        up = min((j for j in range(8) if low[j] != low[i]), key=lambda j: np.linalg.norm(c[j, :2] - c[i, :2]))
        edges |= {tuple(sorted((i, j))) for j in level[:2] + [up]}
    return sorted(edges)


def map_view(scene):
    """The height map and the colour map, and K, T of a far camera that sees them that way (for
    viz.draw_parts and viz.project). Cell [i, j] sits at plane coordinates (u0 + i * cell,
    v0 + j * cell) and the plane frame's x points down the slope, so image down is x, image right
    is y, and the maps are seen face-on with up the slope at the top. Maps over 500 cells across
    (the USB scan's 0.25 mm cells) are shrunk to that, for crisp lines in a 230 px panel."""
    h, colour, cell, (u0, v0) = scene.heightmap
    P = scene.plane[0]
    ok = np.isfinite(h).astype(np.float32)  # fill pinholes between cells, for display only
    num, den = cv2.blur(np.where(ok > 0, h, 0).astype(np.float32), (5, 5)), cv2.blur(ok, (5, 5))
    filled = np.where(ok > 0, h, np.where(den > 0.15, num / np.maximum(den, 1e-6), np.nan))
    views = [viz.colorize_height(filled, *H_RANGE, cell=cell), cv2.dilate(colour, np.ones((3, 3), np.uint8))]
    H, W, far = *h.shape, 100.0
    T = np.eye(4)
    T[:3, :3] = np.c_[P[:3, 1], P[:3, 0], -P[:3, 2]]  # camera right, down, forward
    T[:3, 3] = P[:3, :3] @ [u0 + (H - 1) / 2 * cell, v0 + (W - 1) / 2 * cell, far] + P[:3, 3]
    K = np.array([[far / cell, 0, (W - 1) / 2], [0, far / cell, (H - 1) / 2], [0, 0, 1]])
    s = min(1.0, 500 / max(H, W))
    return [cv2.resize(v, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) for v in views], np.diag([s, s, 1.0]) @ K, T


def grid_map(T, cell, K, Tc):
    """3x3 map from (col, row) on a scan grid (cell [0, 0] at plane frame T's origin, rows along its x) to the
    pixels of a camera (K, Tc)."""
    return K @ Tc[:3, :3].T @ np.c_[cell * T[:3, 1], cell * T[:3, 0], T[:3, 3] - Tc[:3, 3]]


def lay(base, ortho, M, clip=None):
    """An orthophoto (image, mask (uint8), lines on its grid) drawn onto base in place, through M, the 3x3 map
    from grid (col, row) to base's pixels; clip (uint8, base's size) limits where. Lines, (polyline (col, row),
    rgb, px wide), are drawn after the warp, so they stay crisp."""
    img, mask, lines = ortho
    u = cv2.perspectiveTransform(np.float32([[[0, 0], [1, 0], [0, 1]]]) + [img.shape[1] / 2, img.shape[0] / 2], M)[0]
    (ux, uy), (vx, vy) = u[1:] - u[0]
    s = math.sqrt(abs(ux * vy - uy * vx))  # how much the warp shrinks the grid
    Mi = M
    if s < 1:  # area-average down first: the warp alone would alias the print
        img, mask = (cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) for a in (img, mask))
        Mi = M @ np.diag([1 / s, 1 / s, 1])
    size = base.shape[1::-1]
    a = cv2.warpPerspective(mask, Mi, size).astype(np.float32) / 255
    if clip is not None:
        a *= clip / 255
    base[:] = base * (1 - a[..., None]) + cv2.warpPerspective(img, Mi, size) * a[..., None]
    for pts, rgb, width in lines:
        uv = cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), M).reshape(-1, 2)
        cv2.polylines(base, [viz._px(uv)], True, viz.bgr(rgb), width, cv2.LINE_AA, 4)
    return base


def haloed(lines):
    """(polyline, rgb) pairs as lay()'s lines, 2 px on a dark 4 px edge, so they show on light and dark panels."""
    return [(c, viz.PAGE, 4) for c, _ in lines] + [(c, rgb, 2) for c, rgb in lines]


def outlines(mask):
    """A mask's outer outlines, as (col, row) polylines."""
    return [c[:, 0] for c in cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]


def height_cloud(scene, n=MAX_POINTS):
    """The cells of the USB scan's height map that stand off the panel, as points (arm frame, as believed) in
    the orthophoto's colours."""
    hm, img, cell, _ = scene.heightmap
    T, rc = scene.plane[0], np.argwhere(hm > 0.0004)  # NaN compares False
    rc = rc[np.random.default_rng(0).permutation(len(rc))[:n]]
    h = hm[rc[:, 0], rc[:, 1]]
    return T[:3, 3] + (rc * cell) @ T[:3, :2].T + h[:, None] * T[:3, 2], img[rc[:, 0], rc[:, 1], ::-1]


def touch_height(p):
    """A part's height above the panel where a touch reads it, as touch.py measures it: a dial's or knob's body,
    a toggle's base, else the part's top."""
    if p.kind in ("dial", "knob"):
        return p.meta["knob_height"]
    return p.meta["base_size"][2] if p.kind == "toggle" else p.size[2]


PERCEIVE_STAGES = {"survey": "iPhone survey", "views": "plan wrist views", "scan": "wrist scan", "fuse": "fuse the cloud",
                   "plane": "panel plane", "heightmap": "height map", "segment": "segment", "classify": "classify parts"}
RGB_STAGES = {"survey": "iPhone survey", "views": "plan wrist views", "scan": "USB wrist scan", "poses": "camera poses",
              "orthophoto": "orthophoto", "segment": "OWLv2 + SAM", "heights": "plane-sweep heights",
              "classify": "classify parts", "touch plane": "touch the panel", "touch parts": "touch part tops"}


class Dashboard(viz.Dashboard):
    """viz.Dashboard whose plan box lists the perception stages until there is a test plan."""
    stages = PERCEIVE_STAGES
    perceiving = None  # None: viz's plan box; "": perception not started; else the stage running, or "done"

    def __init__(self, *a):
        super().__init__(*a)
        self.failed = set()  # the stages that raised

    def _plan(self, img, txt, x0, y0, x1, rows):
        if self.plan or self.perceiving is None:
            return super()._plan(img, txt, x0, y0, x1, rows)
        names, half = list(self.stages), (x1 - x0) // 2
        per = (len(names) + 1) // 2
        now = names.index(self.perceiving) if self.perceiving in names else len(names) if self.perceiving == "done" else -1
        txt.append(((x0, y0 + 18), "PERCEPTION", viz.INK2, 14, "bold", "lm"))
        for i, name in enumerate(names):  # two columns, styled like the plan's rows
            x, y = x0 + i // per * half, y0 + 44 + i % per * 22
            txt += [((x, y), f"{i + 1:2d}", viz.MUTED, 15, "mono", "lm"),
                    ((x + 34, y), self.stages[name], viz.INK if i == now else viz.INK2 if i < now else viz.MUTED,
                     15, "regular", "lm")]
            if i <= now:
                fail = name in self.failed
                run = i == now and not fail
                label = "FAILED" if fail else "RUNNING" if run else "DONE"
                r = x + half - 24
                w = int(viz._font(12, "bold").getlength(label)) + 16
                rgb = viz.VERDICT_RGB["FAIL"] if fail else viz.INK if run else viz.HAIRLINE
                cv2.rectangle(img, (r - w, y - 9), (r, y + 9), viz.bgr(rgb), 1 if run else -1)
                txt.append(((r - w / 2, y), label, viz.INK if fail or run else viz.INK2, 12, "bold", "mm"))


RULE_WORDS = {"diam": "size", "circ": "roundness", "h_max": "height", "plateau": "body height", "length": "length",
              "width": "width", "area": "area", "fill": "squareness", "green": "colour", "sub_area": "top part",
              "sub_len": "fin length", "sub_width": "fin width", "sub_off": "fin offset", "sub_h": "knob height"}


def plain(why):
    """Another module's reason in words for the screen: no code names, no raw rule features (perceive.RULES)."""
    why = re.sub(r" \(see [\w.]+\)", "", why)
    return re.sub(r"closest is (\w+) \([\d.]+\), but (\w+) = \S+",
                  lambda m: f"closest to a {m[1]}, but its {RULE_WORDS.get(m[2], m[2])} doesn't fit", why)


def step_text(step):
    """'turn dial_1  angle +60'; the default force limit is left out."""
    params = "  ".join(f"{k} {v:+g}" if k == "angle" else f"{k} {v:g}" for k, v in step.get("params", {}).items()
                       if k != "force_limit")
    return f"{step['skill']} {step['target']}" + (f"  {params}" if params else "")


class LastLook:
    """The USB wrist camera and SAM as touch.make_refine uses them, keeping each look's frame and SAM's box and
    outline (the last of its tries, the one locate() goes by) for the film."""

    def __init__(self, wrist):
        import segmodels  # torch is loaded already: perceive_rgb used it
        self.wrist, self.segment, self.frame, self.outline = wrist, segmodels.sam_boxes(), None, None

    def __getattr__(self, name):  # anything else is the camera's
        return getattr(self.wrist, name)

    def capture(self):
        self.frame, self.outline = self.wrist.capture(), None
        return self.frame

    def sam(self, bgr, boxes):
        masks, scores = self.segment(bgr, boxes)
        self.outline = (boxes[0], masks[0])
        return masks, scores


class Show:
    """Draws the story from arm.on_tick: camera, 3D overlay, panels and dashboard, at FPS."""

    def __init__(self, arm, w, phone, wrist, video=None, viewer=None, condition="", refine=True, rgb=True, pace=1,
                 driver=None):
        self.arm, self.w, self.phone, self.wrist = arm, w, phone, wrist
        self.driver = driver or arm  # the arm the pipeline drives: the SimArm, or RealArm on a simulated bus over it
        self.video, self.viewer, self.condition, self.refine, self.rgb = video, viewer, condition, refine, rgb
        self.pace = pace  # the scan, touch and test play this much faster (SLOP_PACE with soft servos)
        self.dash = Dashboard("Unknown device", f"no CAD, no tags   device {w.name}")
        self.dash.stages, self.stage_names = (RGB_STAGES, STAGE_NAMES) if rgb else (PERCEIVE_STAGES, DEPTH_STAGE_NAMES)
        self.director = Director(arm.m.vis.global_.fovy)
        self.r = viz.renderer(arm.m, MAIN_W, MAIN_H) if video else None
        self.small = viz.renderer(arm.m, PANEL_W, PANEL_H) if (video or viewer) else None
        self.fade_ids = w.device_geom_ids(arm.m)
        self._frame_device()
        self.stage, self.scene, self.steps, self.results = "", None, [], []
        # what is drawn; the stages set these
        self.lidar = self.cloud = self.cloud_rgb = self.box = self.panel_T = self.plane = self.map = None
        self.fade = self.live_frustum = False
        self.blobs, self.parts, self.ghosts, self.path = [], [], [], None
        self.active, self.only_active, self.report, self.views = None, False, None, 0
        self.fix = None  # (part as scanned, part as refine() found it) during a step
        self.shifts = []  # each refine's move (m), None where it kept the part as scanned
        # the USB pipeline's: each wrist capture as (true camera pose, partner), and the one being cast onto the
        # panel; the orthophoto (image, mask, lines on the scan's grid) laid on it; where the probe really touched,
        # and the touch-offs
        self.cams, self.cast, self.main_frame, self.ortho = [], None, None, None
        self.marks, self.contact, self.tri = [], False, None
        self.plane_T, self.touch_rows, self.looks, self.aborted = None, {}, None, False  # touch_rows: name -> (value, rgb)
        # sim truth, believed arm frame -> real: the wrist scan's, and each refined part's
        self.reg0, self.reg, self.fk = np.eye(4), {}, mujoco.MjData(arm.m)
        self.panels, self.phone_img, self.phone_parts, self.viewer_lcd = [], None, None, None
        self.forces = deque(maxlen=400)  # (t, |F| as the robot senses it, true |F|) on the probe, for the force plot
        self.t_next, self.n_frames, self.render_s, self.speed = arm.d.time, 0, 0.0, 1
        arm.on_tick = self.tick

    def _frame_device(self):
        """What the film camera frames: the device's true bounding box and panel corners."""
        m, d = self.arm.m, self.arm.d
        mujoco.mj_forward(m, d)
        sgn = np.array([[a, b, c] for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)])
        # geom boxes; the housing mesh's box sits in its inertia frame and overshoots, and the
        # plate, feet and controls already span the device to within 1 cm
        pts = np.vstack([(sgn * m.geom_aabb[g, 3:] + m.geom_aabb[g, :3]) @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]
                         for g in self.fade_ids if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH])
        lo, hi = pts.min(0), pts.max(0)
        self.device = sgn * (hi - lo) / 2 + (hi + lo) / 2
        pb = m.body("panel").id
        R, c = d.xmat[pb].reshape(3, 3), d.xpos[pb]
        hl, hw = self.w.spec.panel_l / 2, self.w.spec.panel_w / 2
        self.panel = np.array([c + a * hl * R[:, 0] + b * hw * R[:, 1] for a in (-1, 1) for b in (-1, 1)])
        self.normal = R[:, 2].copy()
        # shots are set relative to looking straight at the panel, and stay on its +y side: the key
        # light, the phone and the board are there, and the arm parks on the other side
        self.az0 = math.degrees(math.atan2(-self.normal[1], -self.normal[0]))

    # --- narration ---

    def log(self, text):
        self.dash.log(text, t=self.arm.d.time)
        print(f"{self.arm.d.time:6.1f}  {text}", flush=True)

    def set_stage(self, name, status=None):
        self.stage, self.dash.status = name, status or name
        print(f"--- {name} at video {self.n_frames / FPS:.1f} s", flush=True)

    def failed(self, what, e, end=False):
        """An exception in perception or touch: logged, shown in the status chip and on the checklist's row; with
        end, the story stops, else it goes on with what the camera found."""
        traceback.print_exception(e)
        self.dash.status = f"ABORTED  {what} failed" if end else f"{self.stage}  {what} failed"
        self.dash.failed.add(self.dash.perceiving)
        self.log(f"{what} failed: {type(e).__name__}: {e}" + ("" if end else "; going on with what the camera found"))
        self.aborted = end
        self.still(5.0 if end else 2.0)

    def shot(self, pts, azimuth, elevation, fill=0.8, orbit=0.0, shift=0.0):
        """Frame pts from `azimuth` degrees off looking straight at the panel (negative: from +y)."""
        self.director.shot(pts, self.az0 + azimuth, elevation, self.n_frames / FPS, fill, orbit, shift)

    def hold(self, seconds):
        """Keep the arm where it is and let the video run."""
        for _ in range(round(seconds * robot.CONTROL_HZ)):
            self.driver.send(self.driver.cmd)
            self.driver.tick()

    def still(self, seconds, each=None):
        """Draw `seconds` of video with the sim paused, calling each(fraction done) before every frame."""
        n = round(seconds * FPS)
        for i in range(n if self.video or self.viewer else 0):
            if each:
                each(i / max(n - 1, 1))
            self.draw()

    def part(self, pid):
        return next((p for p in self.scene.parts if p.id == pid), None) if self.scene else None

    def fk_tip(self, q):
        self.fk.qpos[self.arm.qadr] = q
        mujoco.mj_kinematics(self.arm.m, self.fk)
        return site_pose(self.fk, self.arm.tip)

    def tip_error(self, q=None):
        """Sim truth: the rigid map from where the arm believes its fingertip is to where it is, now
        or once the joint readings are q."""
        true = site_pose(self.arm.d, self.arm.tip) if q is None else self.fk_tip(q - self.arm.q_off)
        return true @ np.linalg.inv(self.fk_tip(self.arm.read_q() if q is None else q))

    def refined(self, before, after):
        """refine()'s answer at a step's approach pose: logged, and drawn until the step ends. The
        part is now placed relative to the fingertip, so it is drawn by the fingertip's error."""
        self.reg[after.id] = self.tip_error()
        self.shifts.append(after.meta["refine_shift"] if after.meta["refined"] else None)
        if after.meta["refined"]:
            self.fix = (before, after)
            self.log(f"refine {after.id}: the wrist camera moved it {after.meta['refine_shift'] * 1000:.1f} mm")
        else:
            self.log(f"refine {after.id}: kept as scanned ({plain(after.meta['refine_why'])})")
        if self.looks and self.looks.frame is not None:
            self.last_look(before, after)
        return after

    def last_look(self, before, after):
        """The USB frame refine just took, as the arm believes it was taken: SAM's box and outline, the part as
        scanned (white) and the part moving to where refine put it, while the sim waits."""
        f, sam, col = self.looks.frame, self.looks.outline, viz.bgr(viz.kind_rgb(before.kind))
        ring = viz.glyph(before)[1]
        img, K = crop(f.rgb, f, ring, margin=2.2)
        s = K[0, 0] / f.K[0, 0]
        px = lambda uv: viz._px((np.asarray(uv) - f.K[:2, 2] + K[:2, 2] / s) * s)  # frame pixels to the crop's
        if sam is not None:
            box, mask = sam
            cv2.polylines(img, [px(box[[0, 1, 2, 1, 2, 3, 0, 3]].reshape(4, 2))], True, viz.bgr(viz.MUTED), 1, cv2.LINE_AA, 4)
            fill = img.copy()
            cv2.fillPoly(fill, [px(c) for c in outlines(mask)], col, cv2.LINE_AA, 4)
            cv2.addWeighted(fill, 0.35, img, 0.65, 0, img)
            cv2.polylines(img, [px(c) for c in outlines(mask)], True, col, 1, cv2.LINE_AA, 4)
        cv2.polylines(img, [viz._px(viz.project(ring, K, f.T_base_cam)[0])], True, viz.bgr(viz.INK), 1, cv2.LINE_AA, 4)
        note = (f"SAM's outline: {after.id} moved {after.meta['refine_shift'] * 1000:.1f} mm" if after.meta["refined"]
                else f"kept as scanned: {plain(after.meta['refine_why'])}")
        title = f"USB wrist camera  last look at {before.id}"

        def frame(t):
            look, u = img.copy(), min(1, 1.6 * t)  # the move eases in and out over the first 60% of the look
            uv = viz.project(ring + u * u * (3 - 2 * u) * (after.pos - before.pos), K, f.T_base_cam)[0]
            cv2.polylines(look, [viz._px(uv)], True, col, 2, cv2.LINE_AA, 4)
            cv2.rectangle(look, (0, PANEL_H - 30), (PANEL_W, PANEL_H), viz.bgr(viz.SURFACE), -1)
            viz._text(look, [((12, PANEL_H - 15), viz._clip(note, viz._font(14, "bold"), PANEL_W - 24), viz.INK, 14,
                              "bold", "lm")])
            self.panels[0] = (title, look)
        self.still(LOOK_S if after.meta["refined"] else LOOK_S / 2, frame)

    def aimed(self, p, q):
        """Without refine: part p is drawn shifted sideways by the fingertip's error at the step's contact
        pose q, so its glyph shows where the pad will land, beside where the wrist camera saw it."""
        gap, n = (self.tip_error(q) - self.reg0)[:3] @ np.r_[p.pos, 1], self.reg0[:3, :3] @ p.normal
        side = gap - gap @ n * n  # a guarded push stops at first contact, so only the sideways error shows
        self.reg[p.id] = self.reg0.copy()
        self.reg[p.id][:3, 3] += side
        self.log(f"no refine: aiming {np.linalg.norm(side) * 1000:.1f} mm beside {p.id} (sim truth)")

    def drawn(self):
        """(part, believed -> real map) for each part on show, the refined part while a step uses it."""
        out = []
        for p in self.parts:
            if self.only_active and p.id != self.active:
                continue
            if self.fix and self.fix[0].id == p.id:
                p = self.fix[1]
            out.append((p, self.reg.get(p.id, self.reg0)))
        return out

    # --- frames ---

    def tick(self, arm):
        f = float(np.linalg.norm(arm.contact_force_vec()))
        r = self.driver
        sensed = r.tip_force() if r.axial_sensor else float(np.linalg.norm(r.tip_force_vec()))
        self.forces.append((arm.d.time, sensed, f))
        if self.stage == "TOUCH":
            self.mark(arm, f)
        while arm.d.time + 1e-9 >= self.t_next:
            self.t_next += self.speed / FPS
            if self.video or self.viewer:
                self.draw()

    def mark(self, arm, f):
        """While touching: the status chip names what the probe is touching, and at each contact a marker goes
        where it really meets it (sim truth, the true force f) and the touch table gets that row, which
        touching() fills in once the touches are read."""
        status = self.driver.status
        what = status.split(":")[0].removeprefix("touch ") if status.startswith("touch ") else None
        if what:
            self.dash.status = "TOUCH  " + what
        if f > robot.CONTACT_N and not self.contact:
            self.marks.append(arm.d.site_xpos[arm.tip].copy())
            if what == "panel":
                self.touch_rows["plane"] = (f"touch-off {len(self.marks)}", viz.INK)
            elif p := self.part(what):
                self.touch_rows.setdefault(what, ("touched", viz.kind_rgb(p.kind)))
        self.contact = f > robot.CONTACT_N / 3 if self.contact else f > robot.CONTACT_N

    def draw(self):
        t0 = time.perf_counter()
        arm = self.arm
        cam = self.director.camera(self.n_frames / FPS, 1 / FPS)  # on video time, whatever the playback speed
        ov = self.overlay()
        panels = [(title, src() if callable(src) else src) for title, src in self.panels]
        if self.video:
            arm.app.refresh_lcd(self.r)
            fade = self.fade_ids if self.fade else ()
            labels, ov.labels = ov.labels, []  # named after the render instead, clear of the other glyphs
            main = viz.render(self.r, arm.d, cam, ov, self.ghosts, fade=fade)
            ov.labels = labels
            K, T = viz.scene_camera(self.r.scene, (MAIN_W, MAIN_H))
            if self.ortho is not None:
                self.lay_on_panel(main, K, T)
            label_parts(main, self.drawn(), K, T, named={text.split()[0] for _, text, _ in labels},
                        hidden=lambda pos: viz._hidden(arm.m, arm.d, T[:3, 3], pos, fade))
            if self.report:
                self.draw_report(main)
            frame = self.dash.frame(main, panels, t=arm.d.time)
            self.draw_stages(frame)
            self.video.write(frame)
        if self.viewer:
            self.to_viewer(cam, ov, panels)
        self.n_frames += 1
        self.render_s += time.perf_counter() - t0

    def overlay(self):
        """The 3D overlay, drawn where things really are (see the module docstring)."""
        ov, seen = viz.Overlay(MAX_POINTS), viz.Overlay(MAX_POINTS)  # seen: the wrist scan, in the believed frame
        # the board places the phone in the arm's base frame, which joint errors don't move
        if self.lidar is not None:
            ov.points(self.lidar, None, size=0.0025)
        if self.box is not None:
            for i, j in box_edges(self.box):
                ov.line(self.box[i], self.box[j], (*viz.INK, 1))
        if self.panel_T is not None:
            ov.frame(self.panel_T, 0.04, 0.0015)
        size = (self.wrist.r.width, self.wrist.r.height)
        T = self.wrist.true_pose() if self.live_frustum else self.cast
        if T is not None:  # out to the panel plane, so its base outlines what the camera sees there
            P = self.scene.survey["panel"]
            depth = (P[:3, 3] - T[:3, 3]) @ P[:3, 2] / (T[:3, 2] @ P[:3, 2])
            ov.frustum(T, self.wrist.K, size, depth=float(np.clip(depth, 0.03, 0.3)))
        for T, partner in self.cams:
            ov.frustum(T, self.wrist.K, size, 0.02, (*(viz.GHOST[:3] if partner else viz.INK), 1), 1)
        for x in self.marks:
            ov.sphere(x, 0.002, (*viz.INK, 1))
        if self.tri is not None:  # the touched plane: its normal from the touch-offs' middle
            ov.tube(np.vstack([self.tri, self.tri[:1]]), (*viz.INK, 1), 0.0005)
            ov.arrow(self.tri.mean(0), self.tri.mean(0) + 0.04 * self.plane_T[:3, 2], (*viz.INK, 1), 0.0012)
        if self.cloud is not None:
            seen.points(self.cloud[0], self.cloud[1] if self.cloud_rgb is None else self.cloud_rgb, size=0.0015)
        if self.plane is not None:
            P, (u0, u1, v0, v1) = self.plane
            rect = [P[:3, :3] @ [u, v, 0.0005] + P[:3, 3] for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0))]
            seen.tube(np.array(rect), (*viz.INK, 1), 0.0007)
            c = P[:3, :3] @ [(u0 + u1) / 2, (v0 + v1) / 2, 0] + P[:3, 3]
            seen.arrow(c, c + 0.05 * P[:3, 2], (*viz.INK, 1), 0.0015)
        for b in self.blobs:
            line = np.asarray(b["outline"], float)
            seen.tube(np.vstack([line, line[:1]]), (*(viz.kind_rgb(b["kind"]) if b["kind"] else viz.INK), 1), 0.0005)
        add_moved(ov, seen, self.reg0)
        for p, M in self.drawn():
            one = viz.Overlay()
            if self.fix and self.fix[1] is p:  # refine moved it: a white outline where the scan had it
                ring = viz.glyph(self.fix[0])[1]
                one.tube(np.vstack([ring, ring[:1]]), (*viz.INK, 1), 0.0004)
            one.part(p)
            add_moved(ov, one, M)
        if self.path is not None:
            ov.tube(self.path, (*viz.GHOST[:3], 1), 0.001)
            ov.head(self.path[-1], self.path[-1] - self.path[-2], (*viz.GHOST[:3], 1))
        if self.active is not None:
            ov.labels = [l for l in ov.labels if l[1].split()[0] == self.active]
        if self.stage == "REPORT":  # the card names the parts; labels would land on the LCD
            ov.labels = []
        return ov

    def lay_on_panel(self, img, K, T):
        """The orthophoto on the panel in the main view: its grid moved to where it really is and cut to the
        panel's true outline (sim truth), as the grid reaches 3 cm past the panel."""
        s = self.scene
        clip = cv2.fillConvexPoly(np.zeros(img.shape[:2], np.uint8),
                                  np.round(viz.project(self.panel[[0, 1, 3, 2]], K, T)[0]).astype(np.int32), 255)
        lay(img, self.ortho, grid_map(self.reg0 @ s.plane[0], s.heightmap[2], K, T), clip)

    # --- panels ---

    def live_phone(self):
        self.arm.app.refresh_lcd(self.small)
        return viz.render(self.small, self.arm.d, "scene_cam", labels2d=False)

    def live_wrist(self):
        """The wrist camera's view now, with the parts drawn as in the main view."""
        self.arm.app.refresh_lcd(self.small)
        img = viz.render(self.small, self.arm.d, "wrist_cam", labels2d=False)
        f = PANEL_H / 2 / math.tan(math.radians(self.arm.m.cam_fovy[self.arm.m.camera("wrist_cam").id]) / 2)
        K = np.array([[f, 0, (PANEL_W - 1) / 2], [0, f, (PANEL_H - 1) / 2], [0, 0, 1]])
        parts = [(p, M) for p, M in self.drawn() if self.active in (None, p.id)]
        return draw_parts(img, parts, K, self.wrist.true_pose())

    def force_plot(self, span=6.0):
        """The force on the probe as the robot senses it; with servo sensing the true force too, in grey."""
        img = np.full((PANEL_H, PANEL_W, 3), viz.bgr(viz.SURFACE), np.uint8)
        t1 = self.arm.d.time
        data = np.array([f for f in self.forces if f[0] > t1 - span] or [(t1, 0.0, 0.0)])
        top = max(1.5, data[:, 1:].max() * 1.2)  # a touch peaks under 1 N, a push at 5 or 6
        x0, x1, y0, y1 = 40, PANEL_W - 14, 14, PANEL_H - 34
        px = lambda t, f: (x0 + (x1 - x0) * (t - t1 + span) / span, y1 - (y1 - y0) * f / top)
        items = []
        for f in np.arange(0, top, next(s for s in (0.5, 1, 2, 4, 8) if top / s <= 6)):
            y = int(px(t1, f)[1])
            cv2.line(img, (x0, y), (x1, y), viz.bgr(viz.HAIRLINE), 1)
            items.append(((x0 - 8, y), f"{f:g}", viz.MUTED, 12, "mono", "rm"))
        for i, rgb in ((2, viz.MUTED), (1, viz.KIND_RGB["button"]))[0 if self.arm.sensing else 1:]:
            pts = np.array([px(t, f) for t, f in data[:, [0, i]]])
            cv2.polylines(img, [np.round(pts * 16).astype(np.int32)], False, viz.bgr(rgb), 2, cv2.LINE_AA, 4)
        items += [((x0, PANEL_H - 16), f"{data[-1, 1]:.1f} N now    {data[:, 1].max():.1f} N peak", viz.INK, 14,
                   "bold", "lm"), ((x1, PANEL_H - 16), {"current": "servo estimate, true in grey", "tactile": "pad, true in grey", "loadcell": "load cell, true in grey"}.get(self.arm.sensing) or
                                   "N, last 6 s", viz.MUTED, 12, "regular", "rm")]
        viz._text(img, items)  # viz's PIL text pass, so the fonts match the dashboard
        return img

    def map_panel(self, which="parts"):
        """Height and colour maps side by side, with blob outlines ('blobs') or the parts."""
        (hmap, cmap), K, T = self.map
        out = []
        for img in (hmap, cmap):
            if which == "blobs":
                img = img.copy()
                for b in self.blobs:
                    uv, _ = viz.project(np.asarray(b["outline"], float), K, T)
                    col = viz.bgr(viz.kind_rgb(b["kind"]) if b["kind"] else viz.INK)
                    cv2.polylines(img, [np.round(uv * 16).astype(np.int32)], True, col, 1, cv2.LINE_AA, 4)
            else:
                img = viz.draw_parts(img, [p for p in self.parts if self.active in (None, p.id)], K, T, labels=False)
            out.append(img)
        gap = np.full((out[0].shape[0], 6, 3), viz.bgr(viz.SURFACE), np.uint8)
        return np.hstack([out[0], gap, out[1]])

    def ortho_panel(self):
        img = self.ortho[0]
        s = min(PANEL_W / img.shape[1], PANEL_H / img.shape[0])
        M = np.array([[s, 0, (PANEL_W - s * img.shape[1]) / 2], [0, s, (PANEL_H - s * img.shape[0]) / 2], [0, 0, 1]])
        return lay(np.full((PANEL_H, PANEL_W, 3), viz.bgr(viz.SURFACE), np.uint8), self.ortho, M)

    def touch_table(self):
        """What the probe's touches measured, a row each: the plane, then each part touched."""
        img = np.full((PANEL_H, PANEL_W, 3), viz.bgr(viz.SURFACE), np.uint8)
        items = []
        for i, (name, (value, rgb)) in enumerate(list(self.touch_rows.items())[-10:]):
            y = 18 + i * 25
            cv2.rectangle(img, (12, y - 6), (22, y + 6), viz.bgr(rgb), -1)
            items += [((32, y), name, viz.INK, 15, "bold", "lm"),
                      ((128, y), viz._clip(value, viz._font(15), PANEL_W - 140), viz.INK2, 15, "regular", "lm")]
        viz._text(img, items)
        return img

    # --- 2D extras on the frame ---

    def draw_stages(self, frame):
        """The stage strip in the title bar (done, current, still to come), then the test condition."""
        names = self.stage_names
        cur, x, items = names.index(self.stage) if self.stage in names else -1, 520, []
        for i, name in enumerate(names):
            col = viz.INK if i == cur else viz.INK2 if i < cur else viz.MUTED
            items.append(((x, 32), name, col, 15, "bold", "lm"))
            w = viz._font(15, "bold").getlength(name)
            if i == cur:
                cv2.rectangle(frame, (x, 46), (int(x + w), 48), viz.bgr(viz.INK), -1)
            x += int(w) + 18
            if i < len(names) - 1:
                items.append(((x - 9, 32), "›", viz.MUTED, 15, "regular", "mm"))
                x += 8
        speed = f"   |   {self.speed:g}x speed" if self.speed != 1 else ""  # clipped clear of the status chip
        items.append(((x + 32, 32), viz._clip(self.condition + speed, viz._font(15), self.dash.title_right - 24 - x - 32),
                      viz.MUTED, 15, "regular", "lm"))
        viz._text(frame, items)

    def draw_report(self, img):
        """The report card over the main view: each part, the channel it drives, its verdicts."""
        x0, y0, rh = 28, 28, 34
        w, h = 500, 96 + rh * len(self.report)
        bg = img.copy()
        cv2.rectangle(bg, (x0, y0), (x0 + w, y0 + h), viz.bgr(viz.SURFACE), -1)
        cv2.addWeighted(bg, 0.88, img, 0.12, 0, img)
        cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), viz.bgr(viz.HAIRLINE), 1)
        cols = (x0 + 20, x0 + 150, x0 + 250, x0 + 360)
        items = [((cols[0], y0 + 26), "WHAT THE ROBOT FOUND", viz.INK2, 15, "bold", "lm")]
        for c, head in zip(cols, ("PART", "KIND", "DRIVES", "VERDICTS")):
            items.append(((c, y0 + 58), head, viz.MUTED, 13, "bold", "lm"))
        for i, (pid, kind, drives, verdicts) in enumerate(self.report):
            y = y0 + 90 + i * rh
            cv2.rectangle(img, (cols[0], y - 7), (cols[0] + 10, y + 7), viz.bgr(viz.kind_rgb(kind)), -1)
            items += [((cols[0] + 20, y), pid, viz.INK, 17, "regular", "lm"),
                      ((cols[1], y), kind, viz.INK2, 17, "regular", "lm"), ((cols[2], y), drives, viz.INK, 17, "bold", "lm")]
            x = cols[3]
            for v in verdicts:
                vw = int(viz._font(12, "bold").getlength(v)) + 16
                cv2.rectangle(img, (x, y - 10), (x + vw, y + 10), viz.bgr(viz.VERDICT_RGB.get(v, viz.MUTED)), -1)
                items.append(((x + vw / 2, y), v, (0.04, 0.04, 0.04) if v == "ABORTED" else (1, 1, 1), 12, "bold", "mm"))
                x += vw + 6
        viz._text(img, items)

    # --- live viewer (untested: the ground rules forbid opening a window here) ---

    def to_viewer(self, cam, ov, panels):
        v = self.viewer
        if not v.is_running():
            return
        v.cam.lookat[:], v.cam.distance, v.cam.azimuth, v.cam.elevation = cam.lookat, cam.distance, cam.azimuth, cam.elevation
        if self.viewer_lcd != self.arm.app.lcd:  # update_texture blocks until the viewer has it
            self.viewer_lcd = self.arm.app.lcd
            self.arm.app.refresh_lcd(v)
        viz.show_in_viewer(v, ov, self.ghosts, [img for _, img in panels])
        log = "\n".join(list(self.dash.lines)[-6:])
        v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT, self.dash.status, log))
        v.sync()


# --- the story ---

def intro(show):
    show.set_stage("INTRO", "UNKNOWN DEVICE")
    show.dash.perceiving = ""
    show.log("an unknown device on the desk: no CAD model, no tags")
    if show.rgb:
        show.log("sensors: a USB RGB camera on the wrist, no depth, and no other camera")
        show.log("touch: " + {"current": "no force sensor, contact estimated from the servos",
                              "tactile": "a pressure pad on the probe's face",
                              "loadcell": "a load cell behind the probe"}.get(show.arm.sensing,
                                                                                    "a force sensor behind the probe's pad"))
    else:
        show.log("sensors: iPhone (RGB + LiDAR) on a tripod, D405 depth camera on the wrist")
    show.panels = [("Desk view (film camera)" if show.rgb else "iPhone  live", show.live_phone),
                   ("Wrist camera  live", show.live_wrist)]
    arm_pts = np.array([[0, 0, -0.14], [0, 0, 0.25], [0.2, 0, 0.14]])
    show.shot(np.vstack([show.device, arm_pts]), -80, -16, fill=0.85, orbit=3)
    show.hold(2.5)
    show.shot(show.device, -55, -22, fill=0.7, orbit=2)
    show.hold(3.0)


def on_stage(show, name, scene):
    """Perception's progress: narrate each stage, and show the survey before the scan starts. The USB
    pipeline plans views and scans again for any part fewer than two views see."""
    show.scene, show.dash.perceiving = scene, name
    first = show.views == 0
    if name == "survey" and show.wrist_survey:
        show.set_stage("SURVEY")
        show.log("wrist camera: overview frames near home, features matched and triangulated")
    elif name == "survey":
        show.set_stage("SURVEY")
        show.log("iPhone: camera pose from the desk board, then LiDAR depth")
        f = show.phone.true_pose()[:3, 2]  # the film camera swings round to the tripod's view
        show.shot(show.device, math.degrees(math.atan2(f[1], f[0])) - show.az0, math.degrees(math.asin(f[2])), fill=0.6)
    elif name == "views" and first and not scene.frames:  # the wrist camera surveyed: no phone frame to show
        tilt = math.degrees(math.acos(np.clip(scene.survey["panel"][2, 2], -1, 1)))
        show.log(f"wrist survey: {len(scene.survey['points'])} features, panel tilted {tilt:.0f} deg")
        show.panels = [show.panels[1], show.panels[1], ("Wrist survey  overview", scene.survey["captures"][0].frame.rgb)]
    elif name == "views" and first:
        f, s = scene.frames[0], scene.survey
        show.lidar, show.box, show.panel_T, show.fade = s["points"], s["box"], s["panel"], True
        e = np.array([s["box"][j] - s["box"][i] for i, j in box_edges(s["box"]) if 0 in (i, j)]) * 1000
        up = np.argmax(np.abs(e[:, 2]))
        foot = np.linalg.norm(np.delete(e, up, 0), axis=1)
        tilt = math.degrees(math.acos(np.clip(s["panel"][2, 2], -1, 1)))
        show.log(f"LiDAR: device {foot[0]:.0f} x {foot[1]:.0f} mm, {abs(e[up, 2]):.0f} mm tall, panel tilted {tilt:.0f} deg")
        show.phone_img, K = crop(f.rgb, f, s["box"])
        uv, zs = viz.project(s["box"], K, f.T_base_cam)
        for i, j in box_edges(s["box"]):
            cv2.line(show.phone_img, tuple(np.round(uv[i]).astype(int)), tuple(np.round(uv[j]).astype(int)),
                     viz.bgr(viz.INK), 2, cv2.LINE_AA)
        depth = viz.colorize_height(np.where(f.depth > 0, -f.depth, np.nan), -zs.max() - 0.05, -zs.min() + 0.02)
        show.panels = [("iPhone  RGB", show.phone_img), ("iPhone  LiDAR depth", crop(depth, f, s["box"])[0]),
                       show.panels[1]]
        show.hold(1.5)
        show.shot(show.device, -50, -28, fill=0.75, orbit=2)
        show.hold(2.5)
    elif name == "scan" and first:
        show.set_stage("SCAN")
        show.lidar, show.box, show.panel_T, show.live_frustum = None, None, None, True
        if show.rgb:  # no cloud to see through the device for
            show.speed, show.fade = SCAN_SPEED * show.pace, False
            show.log("wrist USB camera: a frame at each view, and a partner frame 15 mm aside")
        else:
            show.speed = show.pace
            show.log("wrist D405: scanning the panel from close up")
        show.shot(np.vstack([show.panel, show.panel.mean(0) + 0.13 * show.normal]), -85, -42, fill=0.72, orbit=1.5)
    elif name == "views":
        show.log("some outlines are seen by fewer than two views: one more view on each")
    elif name != "scan":
        show.dash.status = name.upper()


def on_frame(show, frame, cloud):
    """A wrist capture: the cloud grows and the panels show what the camera saw."""
    show.cloud, show.views = cloud, show.views + 1
    show.dash.status = f"SCAN  view {show.views}"
    show.log(f"wrist view {show.views}: cloud now {len(cloud[0]):,} points")
    if show.views == 1:  # the scan is in this view's believed camera frame: draw it moved by that error
        show.reg0, c = show.wrist.true_pose() @ np.linalg.inv(frame.T_base_cam), show.panel.mean(0)
        gap = np.linalg.norm(show.reg0[:3, :3] @ c + show.reg0[:3, 3] - c)
        show.log(f"sim truth: the arm's picture is {gap * 1000:.0f} mm off (calibration); drawn in place")
    show.panels = [("Wrist camera  D405 RGB", frame.rgb), ("Wrist camera  depth relief", relief(frame)),
                   ("iPhone  RGB", show.phone_img)]


def on_usb_frame(show, frame, _):
    """A USB wrist capture: at a view, or its partner 15 mm aside, whose parallax gives heights. A view's own
    capture sits within a few mm of the view's planned camera pose."""
    partner = min(np.linalg.norm(frame.T_base_cam[:3, 3] - v["T"][:3, 3]) for v in show.scene.views) > 0.007
    show.cams.append((show.wrist.true_pose(), partner))
    if partner:
        if show.views == 1:
            show.log("its partner, matched to it on the panel: whatever stands off the panel shows double")
        show.panels[1] = ("Partner 15 mm aside, matched on the panel", parallax(show.main_frame, frame, show.scene.survey))
    else:
        show.views, show.main_frame = show.views + 1, frame
        show.log(f"wrist view {show.views}: a {frame.rgb.shape[1]} x {frame.rgb.shape[0]} RGB frame, no depth")
        grey = cv2.cvtColor(cv2.cvtColor(frame.rgb, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)  # until its partner comes
        show.panels = [(f"USB wrist camera  view {show.views}", frame.rgb),
                       ("Partner 15 mm aside, matched on the panel", grey), show.panels[2]]
    show.dash.status = f"SCAN  view {show.views}" + ("  partner" if partner else "")


def perception(show):
    frame = on_usb_frame if show.rgb else on_frame
    try:
        show.scene = pipeline.scan_device(show.driver, show.phone, show.wrist, not show.rgb,
                                          on_stage=lambda n, s: on_stage(show, n, s),
                                          on_frame=lambda f, c: frame(show, f, c))
    except Exception as e:  # a device perception can't handle: the film says so instead of stopping short
        show.failed("perception", e, end=True)


def park(show):
    """The arm off to its right, clear of the panel."""
    q, *_ = show.driver.ik.solve(np.array(PARK_TIP), np.array(PARK_AXIS), show.driver.home_q)
    skills.go_home(show.driver)  # via home, which is clear of the device from anywhere the scan ends
    skills.move_joints(show.driver, q)


def reveal(show):
    """The depth pipeline's results one by one: fused cloud, plane, height map, segments, parts."""
    s, panel = show.scene, show.panel
    show.set_stage("MAP", "FUSE")
    show.live_frustum, show.cloud, show.cloud_rgb, show.speed = False, s.cloud, None, 1
    show.shot(panel, -45, -35, fill=0.8, orbit=-2)
    show.log(f"fused {len(s.cloud[0]):,} points from {len(s.frames) - 1} wrist views in {s.timings.get('fuse', 0):.1f} s")
    park(show)
    show.hold(1.0)

    show.dash.status = "PLANE"
    P, (u0, u1, v0, v1) = s.plane
    show.plane = s.plane
    tilt = math.degrees(math.acos(np.clip(P[2, 2], -1, 1)))
    show.log(f"panel plane: {abs(u1 - u0) * 1000:.0f} x {abs(v1 - v0) * 1000:.0f} mm, tilted {tilt:.0f} deg")
    show.shot(panel, -25, -48, fill=0.85, orbit=-1.5)
    show.hold(2.0)

    show.dash.status = "HEIGHT MAP"
    show.map = map_view(s)
    show.cloud_rgb = height_rgb((s.cloud[0] - P[:3, 3]) @ P[:3, 2])
    h = s.heightmap[0]
    show.log(f"height map: {h.shape[1]} x {h.shape[0]} cells of {s.heightmap[2] * 1000:.1f} mm, "
             f"tallest {np.nanmax(h) * 1000:.0f} mm")
    show.panels = [("Height map  |  colour map", show.map_panel()), show.panels[0], show.panels[1]]
    show.hold(2.5)

    show.dash.status = "SEGMENT"
    show.blobs, show.plane = [dict(b, kind=None) for b in s.blobs], None
    show.panels[0] = ("Height map  |  colour map   segments", show.map_panel("blobs"))
    show.log(f"segmented {len(s.blobs)} blobs above and below the plane")
    show.hold(2.0)
    classify(show, s.frames[1].T_base_cam)


def segment(show):
    """The USB pipeline's vision after the scan, one result at a time: the camera poses, the orthophoto
    assembling on the panel, OWLv2's boxes and SAM's outlines on it."""
    s, rgb, panel = show.scene, show.scene.rgb, show.panel
    show.set_stage("SEGMENT", "CAMERA POSES")
    show.speed, show.live_frustum, show.dash.perceiving = 1, False, "poses"
    # sim truth: the scan's frame, tied to the first capture's bundle-adjusted pose, to the real one
    show.reg0 = show.cams[0][0] @ np.linalg.inv(rgb["poses"][0])
    gap = np.linalg.norm(show.reg0[:3, :3] @ panel.mean(0) + show.reg0[:3, 3] - panel.mean(0))
    show.shot(np.vstack([panel] + [T[:3, 3] for T, _ in show.cams]), -45, -30, fill=0.8, orbit=-2)
    show.log(f"camera poses re-solved from the panel's print in {s.timings['poses']:.0f} s:")
    show.log(rgb["poses_from"])
    show.log(f"sim truth: the arm's picture is {gap * 1000:.0f} mm off (calibration); drawn in place")
    park(show)
    show.hold(0.5)

    show.dash.perceiving, show.dash.status = "orthophoto", "ORTHOPHOTO"
    hm, img, cell, _ = s.heightmap
    T, mains = s.plane[0], [k for k, (_, partner) in enumerate(rgb["captures"]) if not partner]
    cams, show.cams = show.cams, []
    # the panel veiled grey, then each frame cast onto it in turn, the newest on top
    mosaic, seen, full = np.full_like(img, 110), np.full(hm.shape, 200, np.uint8), np.full(hm.shape, 255, np.uint8)
    show.panels = [("Orthophoto  frames cast onto the panel plane", show.ortho_panel), *show.panels[:2]]
    show.shot(panel, -25, -48, fill=0.85, orbit=-1.5)
    free = cv2.fillPoly(np.full(s.frames[1].rgb.shape[:2], 255, np.uint8), [rgbperceive.GRIPPER_PX], 0)  # off the probe
    for k in mains:
        f, show.cast = s.frames[1 + k], cams[k][0]
        M = grid_map(T, cell, f.K, rgb["poses"][k])
        new = cv2.warpPerspective(free, M, hm.shape[::-1], flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0
        mosaic[new] = cv2.warpPerspective(f.rgb, M, hm.shape[::-1], flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)[new]
        seen[new] = 255
        show.ortho = (mosaic, seen, haloed([(c, viz.INK) for c in outlines(new)]))
        show.hold(0.25)
    show.ortho, show.cast = (img, full, []), None
    show.log(f"orthophoto: {len(mains)} frames blended on the plane, {hm.shape[1]} x {hm.shape[0]} cells of "
             f"{cell * 1000:.2f} mm ({s.timings['orthophoto']:.0f} s)")
    show.hold(1.0)

    show.dash.perceiving, show.dash.status = "segment", "SEGMENT"
    import segmodels  # torch is loaded already: perceive_rgb used it
    boxes = segmodels.owl()(img)[0]
    show.ortho = (img, full, haloed([(b[[0, 1, 2, 1, 2, 3, 0, 3]].reshape(4, 2), viz.INK) for b in boxes]))
    show.log(f"OWLv2: {len(boxes)} boxes round things that look like controls (rerun for the film)")
    show.hold(1.5)
    grid = lambda X: ((np.asarray(X) - T[:3, 3]) @ T[:3, :2] / cell)[:, ::-1]  # arm frame to grid (col, row)
    subs = [c for m in rgb["masks"].values() for sub in m["subs"] for c in outlines(sub)]
    show.ortho = (img, full, haloed([(grid(b["outline"]), viz.INK) for b in s.blobs] + [(c, viz.GHOST[:3]) for c in subs]))
    show.log(f"SAM: {len(s.blobs)} outlines from the boxes, {len(subs)} sub-parts inside them "
             f"({s.timings['segment']:.0f} s)")
    show.hold(2.0)


def heights(show):
    """The plane sweep's heights as a relief over the panel, then each outline's kind from its shape and height."""
    s = show.scene
    P = s.plane[0]
    show.set_stage("MAP", "HEIGHTS")
    show.dash.perceiving = "heights"
    show.ortho, show.fade, show.plane = None, True, s.plane
    show.cloud, show.cloud_rgb = height_cloud(s), None
    show.blobs, show.map = [dict(b, kind=None) for b in s.blobs], map_view(s)
    show.panels = [("Height map  |  colour map   outlines", show.map_panel("blobs")), *show.panels[1:]]
    show.shot(show.panel, -45, -35, fill=0.8, orbit=-2)
    show.log(f"plane sweep: the frames over each outline, matched at heights from {rgbperceive.SWEEP_H[0] * 1000:.0f} to "
             f"{rgbperceive.SWEEP_H[-1] * 1000:.0f} mm ({s.timings['heights']:.0f} s)")
    show.hold(1.5)
    show.cloud_rgb = height_rgb((show.cloud[0] - P[:3, 3]) @ P[:3, 2])
    show.log(f"heights: tallest {np.nanmax(s.heightmap[0]) * 1000:.0f} mm over the panel")
    show.hold(2.0)
    show.dash.perceiving = "classify"
    classify(show, s.rgb["poses"][0])


def classify(show, T_wrist):
    """The parts appear one by one on the device, each logged with its kind and why. T_wrist: the first wrist
    frame's camera pose, for the panel of parts drawn on that frame."""
    s, panel = show.scene, show.panel
    P, (u0, u1, v0, v1) = s.plane
    show.dash.status = "CLASSIFY"
    show.cloud, show.plane, show.fade = None, None, False  # the parts appear on the device itself
    f = s.frames[0]
    img, K = crop(f.rgb, f, np.array([P[:3, :3] @ [u, v, 0] + P[:3, 3] for u in (u0, u1) for v in (v0, v1)]))
    show.phone_parts = draw_parts(img, [(p, show.reg0) for p in s.parts], K, f.T_base_cam)
    show.panels = [("Height map  |  colour map   parts", show.map_panel),
                   ("Wrist camera  parts", draw_parts(s.frames[1].rgb, [(p, np.eye(4)) for p in s.parts], s.frames[1].K,
                                                      T_wrist, width=PANEL_W)),
                   ("iPhone  parts", show.phone_parts)]
    for b in s.blobs:
        p = show.part(b["part"])
        show.blobs = [x for x in show.blobs if x["outline"] is not b["outline"]]
        if p is not None:
            show.parts = show.parts + [p]
            show.log(f"{p.id}: {p.kind} {p.score:.0%}, {plain(b.get('why', ''))}" +
                     (", pinch only: will not touch" if p.grip == "pinch" else ""))
        else:
            show.blobs.append(dict(b, kind=b["kind"] or "unknown"))
            show.log(f"blob: {b['kind'] or 'unknown'} ({plain(b.get('why', ''))})")
        show.hold(min(0.45, 4 / len(s.blobs)))  # about 4 s however many blobs there are
    show.parts = s.parts  # the list run_step updates as it moves parts, so the glyphs follow
    show.hold(1.0)
    show.shot(panel, -40, -40, fill=0.75, orbit=-2)
    show.hold(1.5)


def touching(show):
    """touch.touch_plane taps bare panel three times for the panel plane in the probe's own frame, then
    touch.touch_parts taps part tops for their heights. If either fails, the film logs it and goes on with
    what vision found."""
    s, arm = show.scene, show.driver
    V = s.plane[0]
    show.set_stage("TOUCH")
    show.speed, show.dash.perceiving = TOUCH_SPEED * show.pace, "touch plane"
    show.panels = [("Probe contact force", show.force_plot), ("Probe touches", show.touch_table),
                   ("Wrist camera  live", show.live_wrist)]
    # from the +y side, 15 deg in front of square to the arm's reach to the panel: further to the front the wrist hides
    # the probe's tip, further round the panel is seen edge on
    c, base = show.panel.mean(0), arm.d.xpos[arm.m.body("base").id]
    side = math.degrees(math.atan2(c[1] - base[1], c[0] - base[0])) - 75 - show.az0
    show.shot(np.vstack([show.panel, c + 0.08 * show.normal]), side, -30, fill=0.9)
    show.log("probe: three touch-offs on bare panel, for the plane in the probe's own frame")
    skills.go_home(arm)
    show.plane_T, got, err = pipeline.touch_plane(arm, s)
    if err:
        show.failed("touch-offs", err)
    n = show.plane_T[:3, 2]
    tilt = math.degrees(math.acos(np.clip(n @ V[:3, 2], -1, 1)))
    gap = (show.plane_T[:3, 3] - V[:3, 3]) @ V[:3, 2]
    row = f"{tilt:.1f}° and {gap * 1000:+.1f} mm off the camera's" if got else "no touch-offs: the camera's"
    show.log(f"touched plane from {len(got)} touch-offs: {row}")
    show.touch_rows["plane"] = (row, viz.INK)
    if len(got) == 3:  # where the touch-offs really were: the fingertip's error at each (sim truth)
        show.tri = np.array([(show.tip_error(arm.ik.solve(x, -n, arm.cmd)[0]) @ np.r_[x, 1])[:3] for x in got])

    show.dash.perceiving = "touch parts"
    show.log("probe: a touch on each part's top, where the pad fits")
    before = s.parts
    s.parts, err = pipeline.touch_parts(arm, s, show.plane_T)
    if err:
        show.failed("part touches", err)
    show.parts = s.parts
    for p, old in zip(s.parts, before):
        m = p.meta
        if "touched" not in m:
            continue
        if m.get("touch_why"):
            row, text = "not used: " + m["touch_why"], m["touch_why"]
        else:
            row = f"{' / '.join(f'{h * 1000:.1f}' for h in m['touched'])} mm  (scan {touch_height(old) * 1000:.1f})"
            text = f"touched {row}" + (f"; the touch says {m['touch_kind']}" if m.get("touch_kind") else "")
        show.touch_rows[p.id] = (row, viz.kind_rgb(p.kind))
        show.log(f"{p.id}: {text}")
    show.dash.perceiving, show.dash.status, show.speed = "done", "TOUCHED", 1
    show.hold(1.5)
    show.panels = [("Height map  |  colour map   parts", show.map_panel), ("Probe touches", show.touch_table),
                   ("iPhone  parts", show.phone_parts)]


def plan(show):
    """The test plan from the parts. Each part's first step is previewed: a ghost arm where the
    pad meets the part, and the pad's path. preview() plans from the part as it is now, so a
    step that follows another on the same part (flip back, slide back) can't be shown yet."""
    s = show.scene
    show.set_stage("PLAN")
    show.marks, show.tri = [], None
    show.steps = affordances.plan_tests(s.parts)
    show.dash.plan = [(step_text(st), "") for st in show.steps]
    show.log(f"plan: {len(show.steps)} steps for {len(s.parts)} parts")
    show.shot(np.vstack([show.panel, show.panel.mean(0) + 0.08 * show.normal]), -60, -35, fill=0.9, orbit=-1.0)
    firsts = [st for i, st in enumerate(show.steps) if st["target"] not in [o["target"] for o in show.steps[:i]]]
    for i, st in enumerate(firsts):
        p = show.part(st["target"])
        qs = affordances.preview(show.driver, p, st, s.parts) if p is not None else []
        qs = [q - show.arm.q_off for q in qs]  # where those commands really put the joints
        show.active, show.ghosts = st["target"], [(qs[1], GHOST)] if qs else []
        path = [show.arm.ik.fk(q)[0] for q in qs]
        if len(path) > 2 and np.linalg.norm(path[-1] - path[0]) < 0.002:
            path = path[:-1]  # it comes back out the way it went in: draw the way in
        show.path = np.array(path) if len(path) > 1 else None
        show.dash.status = f"PLAN  preview {i + 1}/{len(firsts)}"
        show.hold(min(1.2, 9 / len(firsts)) if qs else 0.4)  # about 9 s for the whole plan
    show.ghosts, show.path, show.active = [], None, None


def test(show):
    """Run the plan: each step's verdict and what it changed on the device. With the USB camera,
    each refine's last look replaces the first panel."""
    s = show.scene
    show.set_stage("TEST")
    show.only_active, show.speed = True, TEST_SPEED * show.pace
    live, maps = ("Wrist camera  live", show.live_wrist), ("Height map  |  colour map   parts", show.map_panel)
    show.panels = [maps, live] if show.rgb else [live, maps]
    show.panels.append(("Probe contact force", show.force_plot))
    skills.go_home(show.driver)
    k = [-1]

    def on_step(step, result):
        if result is None:
            k[0] += 1
            show.dash.plan[k[0]] = (show.dash.plan[k[0]][0], "run")
            show.dash.status = f"TEST {k[0] + 1}/{len(show.steps)}"
            show.active = step["target"]
            p = show.part(step["target"])
            show.log(step_text(step))
            if p is not None:  # the whole panel, close, from 60 deg to the side: the arm stays clear of the LCD
                show.shot(np.vstack([show.panel, p.pos + 0.08 * p.normal]), -60, -35, fill=0.9, orbit=-1.0)
                qs = [] if show.refine else affordances.preview(show.driver, p, step, s.parts)
                if qs:
                    show.aimed(p, qs[1])
            return
        show.fix = None
        if not show.refine:
            show.reg.pop(step["target"], None)  # back on its control once the step is over
        show.dash.plan[k[0]] = (show.dash.plan[k[0]][0], result["verdict"])
        show.log(f"{result['verdict']}  {result['reason']}")

    if not show.refine:
        refine = None
    elif show.rgb:
        show.looks = LastLook(show.wrist)
        found = pipeline.last_look(show.looks, show.plane_T, sam=show.looks.sam)

        def refine(arm, p):
            show.looks.frame = None  # a look that fails before its capture has nothing to show
            return show.refined(p, found(arm, p))  # one that fails leaves the part as it was, and the step goes on
    else:
        found = pipeline.last_look(show.wrist, None, depth=True)
        refine = lambda arm, p: show.refined(p, found(arm, p))
    show.results = affordances.run_plan(show.driver, s.parts, show.steps, on_step=on_step, refine=refine)
    show.active, show.only_active = None, False


def report(show):
    """Every part, what it drives, and its verdicts."""
    s = show.scene
    show.set_stage("REPORT")
    show.speed = 1
    counts = {v: sum(r["verdict"] == v for r in show.results) for v in viz.VERDICT_RGB}
    refused = counts["REFUSED"]  # by design, like a pinch-only knob: not a shortfall
    worst = [f"{v} {counts[v]}" for v in ("ABORTED", "FAIL", "MISSED") if counts[v]]  # viz colours the dot by the first word
    show.dash.status = ", ".join(worst + [f"PASS {counts['PASS']}/{len(show.results) - refused}"]) + (
        f", {refused} refused" if refused else "")
    show.log("  ".join(f"{n} {v}" for v, n in counts.items() if n))
    if show.shifts:
        moved = [m * 1000 for m in show.shifts if m is not None]
        show.log(f"refine found the part on {len(moved)} of {len(show.shifts)} steps" +
                 (f", moving it {np.median(moved):.1f} mm (median), {max(moved):.1f} mm at most" if moved else ""))
    rows = []
    for p in s.parts:
        mine = [r for st, r in zip(show.steps, show.results) if st["target"] == p.id]
        drives = sorted({r["channel"] for r in mine if r.get("channel")})
        rows.append((p.id, p.kind, ", ".join(drives) or ("readout" if p.kind == "display" else "-"),
                     [r["verdict"] for r in mine]))
    show.panels = [("Height map  |  colour map   parts", show.map_panel()), ("iPhone  parts", show.phone_parts),
                   ("Wrist camera  live", show.live_wrist)]
    show.shot(show.device, -35, -20, fill=0.85, orbit=-1, shift=0.38)
    skills.move_joints(show.driver, show.driver.home_q)
    show.hold(0.5)
    show.report = rows  # once the camera has pulled back, so the card doesn't cover the device
    show.hold(7.5)


STAGES = [intro, perception, segment, heights, touching, plan, test, report]
DEPTH_STAGES = [intro, perception, reveal, plan, test, report]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, help="random device layout (default: preset C)")
    ap.add_argument("--placement", choices=["nominal", "random"], default="nominal")
    ap.add_argument("--ideal", action="store_true", help="no sensor noise, no joint offsets")
    ap.add_argument("--offsets", type=float, metavar="DEG",
                    help="joint calibration error, uniform in +-DEG on all five joints (default: N(0, 0.5 deg) on four)")
    ap.add_argument("--slop", action="store_true", help="real servos: gear play, dead band, give under load")
    ap.add_argument("--stiffness", type=float, metavar="NM", help="with --slop, servo stiffness in N.m/rad "
                    f"(robot.SERVO_NM_PER_RAD, default {robot.SERVO_NM_PER_RAD:g})")
    ap.add_argument("--sensing", choices=["perfect", "current", "tactile", "loadcell"], default="perfect",
                    help="contact from a force sensor behind the pad; with --slop, estimated from the servos (current) "
                         "or from a pressure pad on the probe's face (tactile) or a load cell behind it (loadcell), plus the servos")
    ap.add_argument("--effector", choices=["stock", "probe"], default="stock",
                    help="the SO-101's own gripper, as the real arm has, or the fingertip probe, a sim-only reference")
    ap.add_argument("--no-refine", action="store_true", help="act on the scanned parts without refine()")
    ap.add_argument("--depth", action="store_true", help="the earlier pipeline: a D405 depth camera on the wrist, "
                    "perceive.perceive and perceive.refine")
    ap.add_argument("--stereo", action="store_true", help="with --depth, wrist depth matched from two renders, like a real D405")
    ap.add_argument("--record", metavar="OUT.mp4", help="write a 1920x1080, 30 fps video")
    ap.add_argument("--real-driver", action="store_true", help="with --slop --sensing current or tactile, drive the "
                    "sim through the real arm's driver, real_arm.RealArm, on a simulated bus (sim_rig.real_driver)")
    ap.add_argument("--headless", action="store_true", help="no viewer window")
    ap.add_argument("--live", action="store_true", help="passive viewer with panels (the default unless --headless)")
    args = ap.parse_args(argv)
    if args.live and args.headless:
        ap.error("--live and --headless exclude each other")
    if args.stereo and not args.depth:
        ap.error("--stereo needs --depth: the USB camera has no depth")
    if args.sensing != "perfect" and not args.slop:
        ap.error(f"--sensing {args.sensing} needs --slop: the estimate comes from the soft servos' readings")
    if args.real_driver and args.sensing not in ("current", "tactile"):
        ap.error("--real-driver needs --slop --sensing current or tactile: RealArm senses with the servos and the pad")
    live = not args.headless
    rig = sim_rig.make_rig(args.seed, args.placement, args.ideal, args.offsets, args.slop, args.stiffness, args.sensing,
                           args.depth, args.stereo, realtime=live and not args.record, effector=args.effector,
                           driver="real" if args.real_driver else "sim")
    arm, phone, wrist = rig.arm, rig.phone, rig.wrist
    sim = arm.bus.fake.sim if args.real_driver else arm  # the film draws the sim's truth, whichever arm it drives
    condition = (["D405 stereo depth" if args.stereo else "D405 depth"] if args.depth else []) + (
        ["ideal sensors"] if args.ideal else [])  # for the title bar
    if args.offsets is not None:
        condition.append(f"joint error ±{args.offsets:g}°")
    elif args.ideal:
        condition.append("no joint error")
    else:
        condition.append("joint error σ 0.5°")
    if args.slop:
        condition.append(f"soft servos {robot.SERVO_NM_PER_RAD:g} N·m/rad")
    if args.sensing != "perfect":
        condition.append({"current": "servo current only", "tactile": "SensX pad", "loadcell": "load cell"}[args.sensing])
    if args.real_driver:
        condition.append("RealArm")
    condition = ", ".join(condition + (["refine off"] if args.no_refine else []))
    print(condition, flush=True)
    viewer = video = None
    if live:
        import mujoco.viewer
        viewer = mujoco.viewer.launch_passive(sim.m, sim.d, show_left_ui=False, show_right_ui=False)
    if args.record:
        os.makedirs(os.path.dirname(os.path.abspath(args.record)), exist_ok=True)
        video = viz.Video(args.record, FPS)
    show = Show(sim, sim.world, phone, wrist, video, viewer, condition, refine=not args.no_refine, rgb=not args.depth,
                pace=SLOP_PACE if args.slop else 1, driver=arm)
    show.wrist_survey = not args.depth  # the team dropped the iPhone; only the D405 route still uses it
    t0 = time.perf_counter()
    try:
        for stage in DEPTH_STAGES if args.depth else STAGES:
            stage(show)
            if show.aborted:
                break
    finally:
        if video:
            video.close()
        if viewer:
            viewer.close()
        rig.close()
    if args.real_driver:  # the real arm has no collision check: what the sim saw it hit, and the true peak force
        fake = arm.bus.fake
        print(f"simulated bus: collisions {sorted(fake.collisions) or 'none'}, true peak force {fake.peak_true_n:.1f} N, "
              f"RealArm's clock {arm.d.time:.2f} s")
    print(f"done: {sim.d.time:.1f} s of sim, {show.n_frames} frames ({show.n_frames / FPS:.1f} s of video) in "
          f"{time.perf_counter() - t0:.0f} s wall, {1000 * show.render_s / max(show.n_frames, 1):.0f} ms per frame")
    return show


if __name__ == "__main__":
    main()
