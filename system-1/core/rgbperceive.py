"""Find a device's controls with the RGB wrist camera alone: no depth, no CAD, no tags on the device.

    scene = perceive_rgb(arm, None, WristCamera(arm, usb=True))   # moves the arm, then parks it home
    scene.parts                        # features.Part list in the arm frame, built by perceive's per-kind builders
    scene.rgb["touch_hints"]           # where a touch would tell the probe most (see touch_hints)

The RGB counterpart of perceive.perceive, for a wrist camera with no depth. Stages:
survey (perceive.survey on the phone's LiDAR, or survey_wrist on overview frames from the wrist camera: coarse panel plane); views (perceive.plan_views'
3x3 grid at 12 cm: the USB frame covers 75 x 47 deg undistorted); scan
(settle the arm on each view, capture, capture again 15 mm to the side); poses (every capture's pose
re-estimated from the panel's print by bundle adjustment, the believed poses a soft prior, and the panel plane
through that print); orthophoto (the captures projected onto the plane); segment (OWLv2 boxes, SAM outlines,
SAM's automatic masks inside them as sub-parts); then, once, views, scan and poses again for any candidate a
cell of which fewer than two views see (those captures only join the height sweep); heights (a plane sweep over
each candidate, read as a plateau and an upper part); classify (perceive's size rules on each reading,
perceive's builders, turn limits from printed scales).

Positions are approach targets: they carry the scan's pose error (a few mm, shared in part by the probe), and
a re-measure at the approach pose removes most of it (perceive.refine needs depth; an RGB one is not here).
Heights are measured against the panel plane in the same images, so the arm's calibration error mostly cancels;
the probe's own plane should still come from touch-offs (touch_hints "plane").

Besides perceive.Scene's fields (no cloud): scene.heightmap is (heights above the plane, m, NaN where unseen;
the orthophoto with every cell seen at its own height, BGR; cell; (0, 0)) on the grid of scene.plane[0], whose
origin is cell [0, 0]. scene.rgb holds poses (4x4 camera pose per capture, arm frame), poses_from (how they
were found), captures ((view index, partner) per wrist frame), masks ({part id: dict(whole, upper: fin, lever
or slider knob, or None; subs: SAM's sub-part masks; flap and pad for a door)}, HxW on the grid), touch_hints.
"""
import functools
import math
import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import cv2
import mujoco
import numpy as np
from scipy import ndimage
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

import features
import perceive
import skills

PARTNER_SHIFT = 0.015   # a second capture this far along the camera's y at every view: a short baseline for heights
SAG_TOL = 0.0005        # a view is commanded again until the joint readings put the camera this close to it
# The gripper and probe in the USB wrist frame (px), a fixed region: the arm's own geometry rendered once, standing
# in for masking it at calibration, grown by about 30 px (a sim render; redraw it from a real frame once mounted). Kept
# for the stock gripper too: a jaw-only mask let two more features into the coffee grinder's wrist survey, and its
# panel fit (normal z 0.93, the cutoff 0.95) failed
GRIPPER_PX = np.array([(1137, 0), (1137, 31), (1080, 320), (1064, 351), (1030, 375), (992, 383), (908, 381), (869, 364),
                       (850, 344), (839, 320), (793, 31), (793, 0)], np.int32)
PX_WIDTH = 1920         # the frame width the pixel constants here are for; other sizes scale them
# bundle adjustment
PANEL_INSET = 0.008     # panel features come from the survey's panel rectangle shrunk this much (off the housing)
THREADS = 4             # captures (SIFT) and candidates (height sweep) at once: cv2 and numpy let go of the GIL
FK_TOL_PX = 135         # a pair whose panel matches land this far from where the believed poses put them: a wild fit
EXTRA_VIEWS = True      # a second pass of views on candidates fewer than two views saw (hw_rig turns it off: one pass)
SAM_AUTO = True         # SAM's automatic masks as candidates' sub-parts (hw_rig turns it off: the real centrifuge's
                        # scan found the same parts without it, in 9 s instead of 43)
KEEP_REJECTED = False   # a candidate no kind fits is kept as a round part in scene.rejected, for a review (hw_rig)
REJECTED_MIN_H, REJECTED_MAX_W = 0.003, 0.040  # ... when it stands at least this proud, and is no wider than this
ROW_MAX = None          # m: parts and rejected candidates further than this along the slope from the parts' median are
                        # dropped, for a panel whose controls sit in one row (hw_rig)
SAVE_CAPS = None        # a file the survey and captures go to before the vision stages, to replay with analyse (hw_rig)
SURVEY_TRIES = 1        # surveys to take until one passes SURVEY_CHECK (hw_rig)
SURVEY_CHECK = None     # (panel normal's z range, fewest points on the panel plane, shortest panel side's longer one, m)
PROGRESS = None         # PROGRESS(what, **info) gets each stage and intermediate product as it comes (live_view draws them)


def _progress(what, **info):
    if PROGRESS:
        try:
            PROGRESS(what, **info)
        except Exception as e:  # noqa: BLE001 - a display must never stop the scan
            print(f"  scan progress: {type(e).__name__}: {e}")


def survey_doubt(survey):
    """Why survey's panel is not to be trusted under SURVEY_CHECK, or None."""
    if SURVEY_CHECK is None:
        return None
    (nz_lo, nz_hi), min_pts, min_len = SURVEY_CHECK
    nz, pts = survey["panel"][2, 2], len(survey["candidates"][survey["picked"]][2])
    u0, u1, v0, v1 = survey["extent"]
    if not nz_lo <= nz <= nz_hi:
        return f"the panel's normal has z {nz:.2f}, outside {nz_lo}-{nz_hi}"
    if pts < min_pts:
        return f"only {pts} points on the panel's plane"
    if max(u1 - u0, v1 - v0) < min_len:
        return f"the panel is only {max(u1 - u0, v1 - v0) * 1000:.0f} mm long"
    return None
FLAT_BUTTONS = False    # real-rig rules (hw_rig sets it): round button-sized outlines are buttons even when their height
                        # reads flat (dark glossy tops give the sweep little texture) or knob-tall, and extra views
                        # chase only candidates on the panel
BUTTON_DIAM = (0.012, 0.030)
BUTTON_MAX_H = 0.014   # and under this tall: arcade buttons stand 7-10 mm proud, which the sim's rules call a knob or dial;
                        # the real START read 12.4 mm
MIN_TRACKS = 30         # fewer panel feature tracks than this (a plain panel): keep the believed poses
# reprojection noise; prior on each pose's correction. On the real remote photos (system-1/arm/camera/pose_test.py)
# a 1 deg, 3 mm prior corrected 1 deg, 3 mm errors to 0.15 mm median height error, against 0.27 with 0.25 deg, 0.5 mm
SIG_PX, SIG_ROT, SIG_T = 0.5, math.radians(1.0), 0.003
# survey from the wrist camera (no phone)
# overview views: joint moves from home (rad; pan, lift, elbow, wrist flex, roll), always reachable. Panning moves
# the camera sideways for parallax; the second row raises it and looks further down
SURVEY_DQ = [(p, *r) for r in ((0, 0, 0, 0), (-0.15, 0.15, 0.1, 0)) for p in (-0.3, 0.0, 0.3)]
SURVEY_REPROJ_PX = 30   # at PX_WIDTH: a triangulated feature off its matches by more, through the believed poses, is dropped
CANDIDATE_COLORS = [(0, 0, 255), (0, 200, 0), (255, 80, 0), (0, 200, 255), (255, 0, 255), (255, 255, 0), (128, 0, 255),
                    (0, 128, 255)]
SURVEY_PAD = 0.01       # features stop short of the panel's edges: the extent grows this much on each side
# orthophoto
CELL = 0.00025
ORTHO_MARGIN = 0.03     # the survey can come up a few cm short on the side the phone can't see
FEATHER_PX = 180
# segmentation
MIN_AREA = 15e-6        # m^2; smaller masks are specks (perceive.MIN_BLOB)
# heights
SWEEP_H = np.arange(-0.004, 0.0241, 0.0005)  # heights tried (m over the plane); a parabola refines the best
ZNCC_W = 7              # matching window, cells
MIN_STD = 3.0           # grey levels: a patch flatter than this has no texture to match
MIN_SCORE = 0.8         # a cell's height counts when its best match scores this
PILE_MIN = 0.25         # a height votes pile up at counts with this share of the biggest pile
UPPER_MAX = 0.4         # an upper part (fin, lever, slider knob) covers less of its part's footprint than this
UPPER_MIN = 10e-6       # m^2, and more than this (a black fin may vote only along its mark and one edge)
LOCAL_MIN = 30          # votes on the panel around a part for its height there to count
ROUND = 0.9             # a SAM outline this circular (its hull's circularity) is a round part's: buttons 0.98 and up,
                        # dials and knobs 0.90 and up (fin and ridges lean out of it); toggles 0.71 to 0.91
LEVER_CUT = 0.010       # a toggle's footprint is opened with a disc this wide: it fits in the base (12 mm across) but
                        # not across the lever, which reaches past the base in the orthophoto (5 mm thick, 8-10 where
                        # views of it blend) and moved the hinge, the footprint's middle, 2-5 mm toward the lever
# touch hints
PLANE_CLEAR = 0.014     # a plane touch-off spot is this far from every candidate: the 12 mm pad, 8 mm of scan error
PLANE_INSET = 0.015     # and this far inside the survey's panel edge


@dataclass
class Capture:
    frame: object       # rig.Frame (no depth)
    view: int           # index into scene.views
    partner: bool       # the capture PARTNER_SHIFT to the side of its view
    extra: bool = False  # from a view added for a candidate few views saw (its pose is fitted to the others')


def perceive_rgb(arm, phone, wrist, on_stage=None, on_frame=None, on_survey=None):
    """Survey, scan and segment the device in front of the arm with an RGB wrist camera (WristCamera(arm, usb=True)).
    phone=None surveys with the wrist camera too (survey_wrist).
    on_stage(name, scene) runs at the start of each stage, on_frame(frame, None) after each wrist capture (no
    cloud: the frame has no depth). on_survey(survey) runs after the wrist survey. Returns a perceive.Scene; see the
    module docstring for scene.rgb."""
    scene, clock = perceive.Scene(), [None, time.perf_counter()]

    def stage(name):  # a stage that runs twice (views, scan and poses, for extra views) adds up
        now = time.perf_counter()
        if clock[0]:
            scene.timings[clock[0]] = round(scene.timings.get(clock[0], 0.0) + now - clock[1], 3)
        clock[:] = [name, now]
        _progress("stage", name=name, scene=scene)
        if on_stage:
            on_stage(name, scene)

    stage("survey")
    if phone is None:
        for k in range(SURVEY_TRIES):
            scene.survey = survey_wrist(arm, wrist)
            why = survey_doubt(scene.survey)
            if not why:
                break
            print(f"  survey {k + 1} of {SURVEY_TRIES}: {why}")
        else:
            raise RuntimeError(f"no survey to trust in {SURVEY_TRIES} tries: {why}")
        if on_survey:  # it may pick another of the survey's candidate surfaces (use_panel) before the views are planned
            on_survey(scene.survey)
    else:
        scene.frames.append(phone.capture())
        scene.survey = perceive.survey(arm, scene.frames[0])
    stage("views")
    scene.views = perceive.plan_views(arm, scene.survey)
    stage("scan")
    caps = scan(arm, wrist, scene.views, on_frame)
    if SAVE_CAPS:
        with open(SAVE_CAPS, "wb") as f:
            pickle.dump((scene.survey, scene.views, caps), f)

    def more(cands, poses, Tg):  # a view centred on each candidate with a cell fewer than two views see
        short = [c for c in cands if _fewest_views(c, caps, poses, Tg) < 2 and (not FLAT_BUTTONS or _on_panel(c, Tg, scene.survey))]
        if not short:
            return []
        stage("views")
        new = []
        for c in short:
            T = Tg.copy()
            T[:3, 3] = Tg[:3, :3] @ [*(np.argwhere(c["mask"]).mean(0) * CELL), 0] + Tg[:3, 3]
            new.append(dict(perceive.plan_views(arm, {"panel": T})[0], extra=True))
        stage("scan")
        scene.views += new
        return scan(arm, wrist, scene.views, on_frame, first=len(scene.views) - len(new))

    analyse(scene, caps, stage, more if EXTRA_VIEWS else None)
    stage("done")
    return scene


def analyse(scene, caps, stage, more=None):
    """The vision stages on the captures of a scan (scene.survey filled in). more(candidates, poses, grid frame)
    may return further captures: their poses are fitted to the main captures', which stay as they are (and so do
    the orthophoto and the candidates), and they join the height sweep."""
    stage("poses")
    poses, plane, how = adjust(caps, scene.survey)
    stage("orthophoto")
    Tg, shape = ortho_frame(scene.survey, plane)
    img, best = orthophoto(caps, poses, Tg, shape, live=True)
    stage("segment")
    cands = candidates(img, scene.survey)
    _progress("segment", img=img, cands=cands)
    extra = more(cands, poses, Tg) if more else []
    if extra:
        stage("poses")
        caps = caps + extra
        poses, _, how = adjust(caps, scene.survey, held=poses)
    stage("heights")
    swept = []
    with ThreadPoolExecutor(THREADS) as ex:
        for c in ex.map(lambda c: sweep_part(c, caps, poses, Tg), cands):
            swept.append(c)
            _progress("heights", img=img, cands=swept[:], of=len(cands))
    cands = swept
    fix, Tg = panel_fix(cands, Tg, shape)  # from here heights and the grid are on the panel the sweep sees
    cands = [measure(c, fix, poses, Tg, best) for c in cands]
    stage("classify")
    return fill(scene, cands, caps, poses, Tg, img, best, how)


def fill(scene, cands, caps, poses, Tg, img, best, how):
    """Classify the measured candidates and fill the scene with them."""
    grid = perceive.Grid(Tg, CELL, (0.0, 0.0))
    picks, hm = classify(cands, np.where(best >= 0, 0.0, np.nan).astype(np.float32), img)
    shape = img.shape[:2]
    img = orthophoto(caps, poses, Tg, shape, np.nan_to_num(hm))[0]  # every cell seen at its own height
    scene.parts, scene.blobs, masks = build(cands, picks, hm, img, grid)
    scene.rejected = [p for p in (b.pop("rejected", None) for b in scene.blobs) if p is not None]
    if ROW_MAX and len(scene.parts) >= 3:
        along = lambda p: (p.pos - Tg[:3, 3]) @ Tg[:3, 0]
        row = np.median([along(p) for p in scene.parts])
        off = [p.id for p in scene.parts if abs(along(p) - row) > ROW_MAX]
        scene.parts = [p for p in scene.parts if abs(along(p) - row) <= ROW_MAX]
        scene.rejected = [p for p in scene.rejected if abs(along(p) - row) <= ROW_MAX]
        if off:
            print(f"  off the controls' row: {', '.join(off)}")
    for k, p in enumerate(scene.rejected):
        p.id = f"cand_{k + 1}"
    scene.parts = [_limits(p, grid, caps, poses) if p.kind in ("dial", "knob") else p for p in scene.parts]
    scene.frames += [c.frame for c in caps]
    m = ORTHO_MARGIN
    scene.plane = (Tg, (m, shape[0] * CELL - m, m, shape[1] * CELL - m))
    scene.heightmap = (hm, img, CELL, (0.0, 0.0))
    taken = np.any([c["mask"] for c in cands], axis=0) if cands else np.zeros(shape, bool)
    scene.rgb = dict(poses=poses, poses_from=how, captures=[(c.view, c.partner) for c in caps],
                     masks=masks, touch_hints=touch_hints(scene.parts, taken, hm, grid))
    return scene


# --- scan ---

def _settle(arm, q, site):
    """Move to q and hold it. Soft servos sag under gravity (robot.SimArm), so the command is raised by however
    far the joint readings fall short until they put the camera within SAG_TOL of where q does."""
    skills.move_joints(arm, q)
    for _ in range(3):
        if np.linalg.norm(arm.ik.fk(arm.read_q(), site)[0] - arm.ik.fk(q, site)[0]) < (arm.view_tol or SAG_TOL):
            break
        skills.move_joints(arm, arm.cmd + q - arm.read_q())
    for _ in range(perceive.SETTLE_TICKS):
        arm.send(arm.cmd)
        arm.tick()


def scan(arm, wrist, views, on_frame=None, first=0, home=True):
    """Visit each reachable view from views[first], settle, capture, then capture again PARTNER_SHIFT along the
    camera's y. Returns the captures."""
    site = arm.m.site("wrist_cam").id
    caps = []
    for k, v in enumerate(views):
        if k < first or not v["ok"]:
            continue
        pos, axis = arm.ik.fk(v["q"], site)
        q2, ok, _, _ = arm.ik.solve(pos + PARTNER_SHIFT * v["T"][:3, 1], axis, v["q"], site=site)
        for q, partner in ((v["q"], False), (q2, True)):
            if partner and not ok:
                continue
            try:
                _settle(arm, q, site)
            except perceive.SafetyStop as e:
                v.update(ok=partner, why=f"safety stop on the way: {e}")
                break
            caps.append(Capture(wrist.capture(), k, partner, bool(v.get("extra"))))
            _progress("capture", frame=caps[-1].frame, view=k, views=len(views))
            if on_frame:
                on_frame(caps[-1].frame, None)
    if home:
        skills.go_home(arm)
    return caps


def survey_wrist(arm, wrist, on_frame=None):
    """The device's coarse panel plane and extent from the wrist camera alone, in perceive.survey's format: a few
    overview captures from near the home pose, SIFT features matched across them, triangulated with the believed poses,
    then perceive's coarse panel fit on the points above the table. The panel's print and the controls give most
    of the features, so a plain panel gives too few (RuntimeError)."""
    cam = arm.m.camera("wrist_cam").id
    fk, q0, views = mujoco.MjData(arm.m), arm.home_q.copy(), []
    for dq in SURVEY_DQ if getattr(arm, "survey_dq", None) is None else arm.survey_dq:
        q = np.clip(q0 + dq, arm.ik.lo, arm.ik.hi)
        views.append(dict(q=q, T=perceive._camera_pose(arm, fk, cam, q), ok=True, why=""))
    caps = scan(arm, wrist, views, on_frame)
    poses = [c.frame.T_base_cam for c in caps]
    with ThreadPoolExecutor(THREADS) as ex:
        feats = list(ex.map(lambda c: _sift(c.frame, np.full(c.frame.rgb.shape[:2], 255, np.uint8)), caps))
    tracks = _pair_tracks(feats)
    X = np.array([_triangulate(caps, poses, t) for t in tracks]).reshape(-1, 3)
    lim = SURVEY_REPROJ_PX * caps[0].frame.rgb.shape[1] / PX_WIDTH if caps else 0
    ok = [max(np.linalg.norm(_project(caps[c].frame.K, poses[c], x[None])[0][0] - uv) for c, uv in t) < lim
          for t, x in zip(tracks, X)]
    keep = np.array(ok, bool) & perceive._inside(X, perceive._survey_box(arm)) & ~perceive._on_arm(arm, X)
    pts = X[keep]
    colors = np.array([caps[t[0][0]].frame.rgb[int(t[0][1][1]), int(t[0][1][0])] for t, k in zip(tracks, keep) if k])
    if len(pts) < 100:
        raise RuntimeError(f"wrist survey: only {len(pts)} features above the table (a plain panel?)")
    cands, pick = perceive.panel_candidates(pts, np.mean([T[:3, 3] for T in poses], axis=0))
    if pick is None:
        raise ValueError(perceive.NO_PANEL)
    foot = cv2.boxPoints(cv2.minAreaRect(pts[:, :2].astype(np.float32)))
    top = np.percentile(pts[:, 2], 99.5)
    box = np.vstack([np.c_[foot, np.full(4, arm.table_z)], np.c_[foot, np.full(4, top)]])
    survey = dict(points=pts, colors=colors.reshape(-1, 3), box=box, captures=caps, candidates=cands)
    use_panel(survey, pick)
    return survey


def use_panel(survey, k):
    """Make survey_wrist's candidate surface k (an index into survey["candidates"]) its panel."""
    T, (u0, u1, v0, v1) = perceive.panel_frame(survey["points"], survey["candidates"][k])
    a = SURVEY_PAD
    survey.update(panel=T, extent=(u0 - a, u1 + a, v0 - a, v1 + a), picked=k)


def draw_candidates(survey, shown=None):
    """The survey photo that shows the most of the picked panel, turned so the panel's slope runs down the picture, with
    each shown candidate surface's points, outline and number (k + 1), at half size: what System 2 sees at a
    survey_review stop. shown: candidate indices (default all)."""
    pts, cands = survey["points"], survey["candidates"]
    shown = range(len(cands)) if shown is None else shown

    def seen(f, idx):
        uv, z = _project(f.K, f.T_base_cam, pts[idx])
        h, w = f.rgb.shape[:2]
        ok = (z > 0) & (uv[:, 0] >= 0) & (uv[:, 1] >= 0) & (uv[:, 0] < w) & (uv[:, 1] < h)
        return uv[ok]
    f = max((c.frame for c in survey["captures"]), key=lambda f: len(seen(f, cands[survey["picked"]][2])))
    h, w = f.rgb.shape[:2]
    T = survey["panel"]
    d = np.diff(_project(f.K, f.T_base_cam, np.array([T[:3, 3], T[:3, 3] + 0.05 * T[:3, 0]]))[0], axis=0)[0]
    # the wrist camera is mounted rolled: turn the picture so "down the panel" points down, as a person would see it
    if abs(d[1]) >= abs(d[0]):
        code, turn = (None, lambda uv: uv) if d[1] > 0 else (cv2.ROTATE_180, lambda uv: np.c_[w - 1 - uv[:, 0], h - 1 - uv[:, 1]])
    else:
        code, turn = ((cv2.ROTATE_90_CLOCKWISE, lambda uv: np.c_[h - 1 - uv[:, 1], uv[:, 0]]) if d[0] > 0 else
                      (cv2.ROTATE_90_COUNTERCLOCKWISE, lambda uv: np.c_[uv[:, 1], w - 1 - uv[:, 0]]))
    img, labels = (f.rgb.copy() if code is None else cv2.rotate(f.rgb, code)), []
    for k in shown:
        uv = turn(seen(f, cands[k][2]))
        if len(uv) < 3:
            continue
        col = CANDIDATE_COLORS[k % len(CANDIDATE_COLORS)]
        for u, v in uv.astype(int):
            cv2.circle(img, (int(u), int(v)), 5, col, -1)
        cv2.polylines(img, [cv2.convexHull(uv.astype(np.int32))], True, col, 3)
        # the number on one of its own points, the one furthest from the numbers already drawn (surfaces' middles meet)
        u, v = uv[np.argmax([min((np.hypot(*(p - q)) for q in labels), default=-np.hypot(*(p - uv.mean(0)))) for p in uv])]
        labels.append(np.array([u, v]))
        for color, width in (((0, 0, 0), 12), (col, 4)):
            cv2.putText(img, str(k + 1), (int(u) - 14, int(v) + 16), cv2.FONT_HERSHEY_SIMPLEX, 1.8, color, width)
    return cv2.resize(img, None, fx=0.5, fy=0.5)


def _pair_tracks(feats):
    """Features matched across captures with no pose: ratio test, then a fundamental matrix per pair (RANSAC).
    Lists of (capture index, pixel), each capture at most once."""
    bf, parent = cv2.BFMatcher(cv2.NORM_L2), {}

    def root(x):
        while parent.setdefault(x, x) != x:
            parent[x] = x = parent[parent[x]]
        return x

    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            (pa, da), (pb, db) = feats[i], feats[j]
            if min(len(pa), len(pb)) < 20:
                continue
            good = [m for m, m2 in (x for x in bf.knnMatch(da, db, k=2) if len(x) == 2)
                    if m.distance < 0.75 * m2.distance]
            if len(good) < 20:
                continue
            ia, ib = np.array([m.queryIdx for m in good]), np.array([m.trainIdx for m in good])
            _, inl = cv2.findFundamentalMat(pa[ia], pb[ib], cv2.FM_RANSAC, 1.5, 0.999)
            if inl is None:
                continue
            for a, b in zip(ia[inl.ravel() > 0], ib[inl.ravel() > 0]):
                ra, rb = root((i, int(a))), root((j, int(b)))
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for x in list(parent):
        groups.setdefault(root(x), []).append(x)
    return [[(c, feats[c][0][k]) for c, k in sorted(g)] for g in groups.values()
            if len(g) == len({c for c, _ in g}) >= 2]


# --- camera geometry ---

def _project(K, T, X):
    """Pixels (Nx2) and depths (N) of arm-frame points X (Nx3) in a camera at pose T (OpenCV axes)."""
    Xc = (X - T[:3, 3]) @ T[:3, :3]
    return Xc[:, :2] / Xc[:, 2:] * K[[0, 1], [0, 1]] + K[:2, 2], Xc[:, 2]


def _on_plane(K, T, uv, n, p):
    """Where the rays through pixels uv (Nx2) meet the plane through p with normal n: Nx3, arm frame."""
    d = np.c_[(uv - K[:2, 2]) / K[[0, 1], [0, 1]], np.ones(len(uv))] @ T[:3, :3].T
    return T[:3, 3] + ((p - T[:3, 3]) @ n / (d @ n))[:, None] * d


def _exp(w, t):
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = cv2.Rodrigues(np.asarray(w, float))[0], t
    return T


# --- camera poses from the panel's print ---

def _features(caps, survey):
    """SIFT keypoints and descriptors per capture, inside the survey's panel rectangle and off the gripper."""
    T, (u0, u1, v0, v1) = survey["panel"], survey["extent"]
    a = PANEL_INSET
    rect = T[:3, 3] + np.array([[u0 + a, v0 + a], [u1 - a, v0 + a], [u1 - a, v1 - a], [u0 + a, v1 - a]]) @ T[:3, :2].T

    def panel(f):
        mask = np.zeros(f.rgb.shape[:2], np.uint8)
        return _sift(f, cv2.fillPoly(mask, [np.round(_project(f.K, f.T_base_cam, rect)[0]).astype(np.int32)], 255))
    with ThreadPoolExecutor(THREADS) as ex:
        return list(ex.map(lambda c: panel(c.frame), caps))


def _sift(f, mask):
    """SIFT keypoints (Nx2 pixels) and descriptors of frame f inside mask, off the gripper. A detector per call, so
    frames can run on threads."""
    cv2.fillPoly(mask, [_gripper(f.rgb.shape[1])], 0)
    kp, des = cv2.SIFT_create(4000).detectAndCompute(cv2.cvtColor(f.rgb, cv2.COLOR_BGR2GRAY), mask)
    return np.float32([k.pt for k in kp]).reshape(-1, 2), des


def _tracks(caps, feats, survey):
    """Panel points seen in two or more captures: lists of (capture index, pixel). A pair's matches count only
    if one homography (the panel is a plane) fits them and the believed poses roughly agree with it."""
    n, p = survey["panel"][:3, 2], survey["panel"][:3, 3]
    bf, parent = cv2.BFMatcher(cv2.NORM_L2), {}

    def root(x):
        while parent.setdefault(x, x) != x:
            parent[x] = x = parent[parent[x]]
        return x

    for i in range(len(caps)):
        for j in range(i + 1, len(caps)):
            (pa, da), (pb, db) = feats[i], feats[j]
            if min(len(pa), len(pb)) < 20:
                continue
            good = [m for m, m2 in (x for x in bf.knnMatch(da, db, k=2) if len(x) == 2)
                    if m.distance < 0.8 * m2.distance]
            if len(good) < 20:
                continue
            ia, ib = np.array([m.queryIdx for m in good]), np.array([m.trainIdx for m in good])
            H, inl = cv2.findHomography(pa[ia], pb[ib], cv2.USAC_MAGSAC, 2.0)
            if H is None or inl.sum() < 20:
                continue
            ia, ib = ia[inl.ravel() > 0], ib[inl.ravel() > 0]
            fi, fj = caps[i].frame, caps[j].frame
            pred = _project(fj.K, fj.T_base_cam, _on_plane(fi.K, fi.T_base_cam, pa[ia], n, p))[0]
            if np.median(np.linalg.norm(pred - pb[ib], axis=1)) > FK_TOL_PX * fj.rgb.shape[1] / PX_WIDTH:
                continue
            for a, b in zip(ia, ib):
                ra, rb = root((i, int(a))), root((j, int(b)))
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for x in list(parent):
        groups.setdefault(root(x), []).append(x)
    return [[(c, feats[c][0][k]) for c, k in g] for g in groups.values()
            if len(g) == len({c for c, _ in g}) >= 2]  # a capture twice in one track is an ambiguous match


def _triangulate(caps, poses, track):
    A = []
    for c, uv in track:
        P = caps[c].frame.K @ np.linalg.inv(poses[c])[:3]
        A += [uv[0] * P[2] - P[0], uv[1] * P[2] - P[1]]
    X = np.linalg.svd(np.array(A))[2][-1]
    return X[:3] / X[3]


def adjust(caps, survey, held=()):
    """Every capture's pose re-estimated from panel features seen in several captures (bundle adjustment), with
    the believed (forward-kinematics) poses as a soft prior, then the panel plane through those features.
    Returns (poses, (n, p) of the plane, note). With too few features the believed poses and the survey's
    plane stay. held: poses already fitted for the first captures, which then stay put (a prior 100 times
    stiffer) while the others are fitted to them."""
    T0 = list(held) + [c.frame.T_base_cam for c in caps[len(held):]]
    tracks = [t for t in _tracks(caps, _features(caps, survey), survey) if len(t) >= 3]
    n0, p0 = survey["panel"][:3, 2], survey["panel"][:3, 3]
    # Bad matches out first: left in, a few can drag a capture that sees only a few features far off. With the
    # believed poses, a track's point reprojects off its matches by the pose error, which on a plane is a
    # homography per capture; matches 3 px off that homography are bad.
    X = np.array([_triangulate(caps, T0, t) for t in tracks]).reshape(-1, 3)
    good = set()
    for c in range(len(caps)):
        ob = [(k, uv) for k, t in enumerate(tracks) for cc, uv in t if cc == c]
        if len(ob) >= 8:
            pred = _project(caps[c].frame.K, T0[c], X[[k for k, _ in ob]])[0]
            _, inl = cv2.findHomography(pred, np.array([uv for _, uv in ob]), cv2.RANSAC, 3.0)
            good |= {(k, c) for (k, _), ok in zip(ob, inl.ravel()) if ok}
    tracks = [[(c, uv) for c, uv in t if (k, c) in good] for k, t in enumerate(tracks)]
    keep = [len(t) >= 2 and abs((x - p0) @ n0) < 0.02 for t, x in zip(tracks, X)]
    tracks, X = [t for t, ok in zip(tracks, keep) if ok], X[np.array(keep, bool)]
    if len(tracks) < MIN_TRACKS:
        return T0, (n0, p0), f"believed poses and the survey's plane: only {len(tracks)} panel feature tracks"
    # robust to matches 2 px off, then (Cauchy: not convex, so started from there) almost blind to those 2 px off
    cam = np.zeros((len(caps), 6))
    for loss, scale in (("soft_l1", 4.0), ("cauchy", 2.0)):
        cam, X, err, obs = _bundle(caps, T0, tracks, cam, X, loss, scale, len(held))
    n, p = _panel_plane(X, n0)
    return _poses(T0, cam), (n, p), (f"bundle adjustment: {len(tracks)} panel feature tracks, {len(obs)} "
                                    f"observations, {np.mean(err < 1):.0%} within 1 px")


def _panel_plane(X, n0, thr=0.00025, cell=0.01, iters=500):
    """The panel plane through the features. Each 10 mm square of panel votes once, with the median of its
    features, so the dense text of a lit display (1.3 mm up) can't outvote the labels spread over the panel;
    and as nothing lies under the panel, a plane loses two votes for each vote under it. RANSAC on those votes,
    then a least-squares fit to every feature on the winner."""
    e1 = np.cross(n0, [1.0, 0, 0] if abs(n0[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    _, sq = np.unique(np.floor(X @ np.c_[e1, np.cross(n0, e1)] / cell), axis=0, return_inverse=True)
    V = np.array([np.median(X[sq.ravel() == k], axis=0) for k in range(sq.max() + 1)])
    rng, best, score = np.random.default_rng(0), None, -np.inf
    for _ in range(iters):
        s = V[rng.choice(len(V), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        n = n / np.linalg.norm(n) * np.sign(n @ n0)
        d = (V - s[0]) @ n
        sc = np.count_nonzero(np.abs(d) < thr) - 2 * np.count_nonzero(d < -thr)
        if n @ n0 > math.cos(math.radians(20)) and sc > score:
            best, score = (n, s[0]), sc
    n, p = best
    for _ in range(2):
        on = np.abs((X - p) @ n) < thr
        if on.sum() < 3:  # too few features on it to fit a plane (a five-view real scan): the votes' plane stays
            break
        p = X[on].mean(0)
        n = np.linalg.svd(X[on] - p, full_matrices=False)[2][2]
        n *= np.sign(n @ n0)
    return n, p


def _poses(T0, cam):
    return [T @ _exp(c[:3], c[3:]) for T, c in zip(T0, cam)]


def _bundle(caps, T0, tracks, cam0, X0, loss, scale, held=0):
    """One least-squares solve from (cam0, X0), with a robust loss beyond `scale` (in SIG_PX): per capture a 6-dof
    correction to its believed pose T0 (prior SIG_ROT, SIG_T; 100 times stiffer for the first `held`), and per
    feature its depth along the ray of its first observation. Returns the corrections, points, per-observation
    errors (px; 0 for each first observation) and the observations as (track, capture)."""
    C, P = len(caps), len(tracks)
    stiff = np.where(np.arange(C) < held, 100.0, 1.0)[:, None]
    obs = [(k, c) for k, t in enumerate(tracks) for c, _ in t]
    ok_, oc = np.array([o[0] for o in obs]), np.array([o[1] for o in obs])
    uv = np.array([u for t in tracks for _, u in t])
    K = np.array([caps[c].frame.K for c in oc])
    first = np.r_[True, ok_[1:] != ok_[:-1]]
    ref, ray = oc[first], np.c_[(uv[first] - K[first, :2, 2]) / K[first][:, [0, 1], [0, 1]], np.ones(P)]
    z0 = np.einsum("ij,ij->i", X0 - [T0[c][:3, 3] for c in ref], np.array([T0[c][:3, 2] for c in ref]))

    def points(x):
        T = np.array(_poses(T0, x[:6 * C].reshape(C, 6)))
        return np.einsum("nij,nj->ni", T[ref, :3, :3], ray * x[6 * C:, None]) + T[ref, :3, 3], T

    def reproject(x):
        X, T = points(x)
        Ti = np.linalg.inv(T)[oc]
        Xc = np.einsum("nij,nj->ni", Ti[:, :3, :3], X[ok_]) + Ti[:, :3, 3]
        return Xc[:, :2] / Xc[:, 2:] * K[:, [0, 1], [0, 1]] + K[:, :2, 2] - uv

    def resid(x):
        cam = x[:6 * C].reshape(C, 6)
        return np.r_[reproject(x)[~first].ravel() / SIG_PX, (cam[:, :3] * stiff / SIG_ROT).ravel(),
                     (cam[:, 3:] * stiff / SIG_T).ravel()]

    rows = np.flatnonzero(~first)
    S = lil_matrix((2 * len(rows) + 6 * C, 6 * C + P), dtype=int)
    for i, o in enumerate(rows):
        for c in (oc[o], ref[ok_[o]]):
            S[2 * i:2 * i + 2, 6 * c:6 * c + 6] = 1
        S[2 * i:2 * i + 2, 6 * C + ok_[o]] = 1
    for c in range(C):
        S[2 * len(rows) + 6 * c:2 * len(rows) + 6 * c + 6, 6 * c:6 * c + 6] = np.eye(6, dtype=int)
    sol = least_squares(resid, np.r_[cam0.ravel(), z0], jac_sparsity=S, loss=loss, f_scale=scale,
                        x_scale="jac", max_nfev=200)
    return sol.x[:6 * C].reshape(C, 6), points(sol.x)[0], np.linalg.norm(reproject(sol.x), axis=1), obs


# --- orthophoto ---

def ortho_frame(survey, plane):
    """The orthophoto's grid: (4x4 panel frame on the plane, z out, x down the slope; (H, W)); cell [0, 0] at
    the frame's origin, which sits ORTHO_MARGIN outside the survey's panel corner."""
    n, p = plane
    S, (u0, u1, v0, v1) = survey["panel"], survey["extent"]
    T = perceive.plane_frame(n, p)
    c = S[:3, 3] + S[:3, :2] @ [u0 - ORTHO_MARGIN, v0 - ORTHO_MARGIN]
    T[:3, 3] = c - ((c - p) @ n) * n
    return T, (int((u1 - u0 + 2 * ORTHO_MARGIN) / CELL), int((v1 - v0 + 2 * ORTHO_MARGIN) / CELL))


def _cells(T, shape, h=0.0):
    """Arm-frame points of every grid cell, h above the plane: HxWx3."""
    i, j = np.mgrid[:shape[0], :shape[1]] * CELL
    return T[:3, 3] + i[..., None] * T[:3, 0] + j[..., None] * T[:3, 1] + np.asarray(h)[..., None] * T[:3, 2]


def orthophoto(caps, poses, T, shape, h=0.0, live=False):
    """The main captures projected onto the grid at height h (a scalar or HxW) and blended: (HxWx3 BGR, HxW index
    of the capture weighted most per cell, -1 where none sees it). Weights favour a pixel near its image's
    centre and away from the image border and the gripper, sharply, so one view dominates each cell and tall
    parts, which lean differently in every view, aren't doubled. live: PROGRESS gets it as each capture adds to it,
    at every other cell."""
    X = _cells(T, shape, h).reshape(-1, 3)
    acc, wsum, best_w = np.zeros((*shape, 3), np.float32), np.zeros(shape, np.float32), np.zeros(shape, np.float32)
    best = np.full(shape, -1)
    for k, c in enumerate(caps):
        if c.partner:
            continue
        f = c.frame
        hgt, wid = f.rgb.shape[:2]
        free = np.full((hgt, wid), 255, np.uint8)
        cv2.fillPoly(free, [_gripper(wid)], 0)
        free = cv2.distanceTransform(free, cv2.DIST_L2, 5)
        uv, z = _project(f.K, poses[k], X)
        mx, my = (np.float32(a.reshape(shape)) for a in uv.T)
        border = np.minimum.reduce([mx, wid - 1 - mx, my, hgt - 1 - my])
        centre = 1 - np.hypot(mx / wid - 0.5, my / hgt - 0.5) * math.sqrt(2)
        w = np.clip(border / (FEATHER_PX * wid / PX_WIDTH), 0, 1) * np.clip(centre, 0, 1) ** 2
        w *= np.clip(cv2.remap(free, mx, my, cv2.INTER_LINEAR, borderValue=0) / 20, 0, 1)
        w = np.where((z.reshape(shape) > 0.02) & (border > 0), w, 0).astype(np.float32) ** 3
        acc += cv2.remap(f.rgb, mx, my, cv2.INTER_LINEAR).astype(np.float32) * w[..., None]
        wsum += w
        best = np.where(w > best_w, k, best)
        best_w = np.maximum(w, best_w)
        if live and PROGRESS:
            part = acc[::2, ::2] / np.maximum(wsum[::2, ::2], 1e-12)[..., None]
            _progress("orthophoto", img=part.astype(np.uint8), n=sum(not c.partner for c in caps[:k + 1]),
                      of=sum(not c.partner for c in caps))
    img = np.round(acc / np.maximum(wsum, 1e-12)[..., None]).astype(np.uint8)
    return img, np.where(best_w > 0, best, -1)


# --- segmentation ---

def candidates(img, survey, owl_min=0.05):
    """Part candidates on the orthophoto: OWLv2 boxes outlined by SAM, masks that touch merged into one
    candidate (a slider's knob and its two halves of track, a door's flap and pad), and SAM's automatic masks
    lying inside a candidate added as its sub-parts. OWLv2's labels are ignored: kinds come from the shape rules.
    Returns dicts: mask (whole, HxW), subs (masks), score (best OWLv2 score)."""
    import segmodels  # torch and transformers load only when perceive_rgb runs
    boxes, scores, _ = segmodels.owl()(img, threshold=owl_min)
    _progress("owl", img=img, boxes=boxes, scores=scores)
    masks, _ = segmodels.sam_boxes()(img, boxes)
    _progress("sam", img=img, boxes=boxes, masks=masks)
    auto = _sam_auto(segmodels)(img)[0] if SAM_AUTO else []
    segmodels.torch.cuda.empty_cache()  # the card is shared: hand back what the masks took, keep the weights
    H, W = img.shape[:2]
    big = 0.4 * np.prod(np.ptp(np.reshape(survey["extent"], (2, 2)), axis=1)) / CELL ** 2

    def ok(m):  # not a speck, not the panel or the desk, not cut by the edge of the map
        edge = m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any()
        return MIN_AREA / CELL ** 2 < m.sum() < big and not edge

    keep = [(m, s) for m, s in zip(masks, scores) if ok(m)]
    # a box around a row of parts, which SAM outlines whole: it holds two or more masks OWLv2 scored higher
    keep = [(m, s) for m, s in keep if sum(t > s and (n & m).sum() > 0.8 * n.sum() for n, t in keep) < 2]
    near = [cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) for m, _ in keep]  # within 2 mm
    group = list(range(len(keep)))
    for i in range(len(keep)):
        for j in range(i):
            if (near[i] & keep[j][0]).any():
                old, new = group[i], group[j]
                group = [new if g == old else g for g in group]
    cands = []
    for g in sorted(set(group)):
        members = [keep[i] for i in range(len(keep)) if group[i] == g]
        whole = ndimage.binary_fill_holes(np.any([m for m, _ in members], axis=0))
        inside = cv2.dilate(whole.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        subs = []
        for m in [m for m, _ in members] + [m for m in auto if ok(m) and (m & inside).sum() > 0.9 * m.sum()]:
            if m.sum() < 0.9 * whole.sum() and all(_iou(m, s) < 0.9 for s in subs):
                subs.append(m)
        cands.append(dict(mask=whole, subs=subs, score=float(max(s for _, s in members))))
    return cands


@functools.cache
def _sam_auto(segmodels):
    """segmodels' automatic masks on a 16 x 16 grid of points (a point every 14 mm or so) instead of 32 x 32, 8 per
    batch instead of 32: the sub-parts they add (a door's pad) are 18 mm and up, upper parts come from heights, and
    the 6 GB card is shared, where 32 x 32 took over a gigabyte more and four times as long."""
    return segmodels.SamAuto(points_per_side=16, batch=8)


def _iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


# --- heights ---

def _homography(K, T, Tg, i0, j0, h):
    """3x3 map from grid (col, row) of a window whose cell [0, 0] is grid cell (i0, j0), lifted h off the
    plane, to pixels of a camera at pose T."""
    o = Tg[:3, 3] + (i0 * Tg[:3, 0] + j0 * Tg[:3, 1]) * CELL + h * Tg[:3, 2]
    return K @ T[:3, :3].T @ np.c_[CELL * Tg[:3, 1], CELL * Tg[:3, 0], o - T[:3, 3]]


def _gripper(width):
    """GRIPPER_PX for a frame this many pixels wide."""
    return np.round(GRIPPER_PX * (width / PX_WIDTH)).astype(np.int32)


def _free(c):
    """1 where a capture's pixels show the scene: inside the image's border and off the gripper."""
    free = np.zeros(c.frame.rgb.shape[:2], np.float32)
    free[10:-10, 10:-10] = 1
    return cv2.fillPoly(free, [_gripper(free.shape[1])], 0)


def sweep(caps, poses, Tg, roi):
    """Heights over a window of the grid by plane sweep. At each height in SWEEP_H, every capture that sees the
    window is projected onto the grid lifted that far; a cell's height is where the most face-on capture's
    patch best matches the others' (ZNCC over the best half, so one that can't see the cell doesn't veto it).
    Plain plastic has no texture, so only edges and print vote. Returns (heights, NaN where no vote; scores;
    captures used)."""
    i0, i1, j0, j1 = roi
    size, w = (j1 - j0, i1 - i0), ZNCC_W
    H = {k: lambda h, c=c, T=T: _homography(c.frame.K, T, Tg, i0, j0, h) for k, (c, T) in enumerate(zip(caps, poses))}
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    use = [k for k, c in enumerate(caps) if cv2.warpPerspective(_free(c), H[k](0.0), size, flags=flags).mean() > 0.5]
    if len(use) < 3:  # the most face-on and at least two others
        return np.full(size[::-1], np.nan), np.full(size[::-1], -1.0), use
    centre = Tg[:3, 3] + ((i0 + i1) * Tg[:3, 0] + (j0 + j1) * Tg[:3, 1]) * CELL / 2
    ref = max([k for k in use if not caps[k].extra] or use,  # an extra capture's pose is the less sure
              key=lambda k: (poses[k][:3, 3] - centre) @ Tg[:3, 2] / np.linalg.norm(poses[k][:3, 3] - centre))
    grey = {k: cv2.cvtColor(caps[k].frame.rgb, cv2.COLOR_BGR2GRAY).astype(np.float32) for k in use}
    free = {k: _free(caps[k]) for k in use}
    box = lambda a: cv2.boxFilter(a, -1, (w, w))
    best = max(2, (len(use) - 1) // 2)
    agg = np.empty((len(SWEEP_H), *size[::-1]), np.float32)
    for n, h in enumerate(SWEEP_H):
        warp = {k: cv2.warpPerspective(grey[k], H[k](h), size, flags=flags) for k in use}
        seen = {k: cv2.warpPerspective(free[k], H[k](h), size, flags=flags) > 0.99 for k in use}
        a = warp[ref]
        ma = box(a)
        sa = np.sqrt(np.maximum(box(a * a) - ma * ma, 0))
        z = []
        for k in use:
            if k != ref:
                b = warp[k]
                mb = box(b)
                sb = np.sqrt(np.maximum(box(b * b) - mb * mb, 0))
                z.append(np.where((sb > MIN_STD) & seen[k], (box(a * b) - ma * mb) / np.maximum(sa * sb, 1e-3), -1))
        agg[n] = np.sort(z, axis=0)[-best:].mean(0)
        agg[n][(sa < MIN_STD) | ~seen[ref]] = -1
    r = w // 2  # windows reaching past the window's edge
    agg[:, :r], agg[:, -r:], agg[:, :, :r], agg[:, :, -r:] = -1, -1, -1, -1
    k = np.argmax(agg, axis=0)
    score = np.take_along_axis(agg, k[None], 0)[0]
    lo, hi = np.take_along_axis(agg, np.clip(k - 1, 0, len(SWEEP_H) - 1)[None], 0)[0], \
        np.take_along_axis(agg, np.clip(k + 1, 0, len(SWEEP_H) - 1)[None], 0)[0]
    den = lo - 2 * score + hi
    off = np.where(den < -1e-6, 0.5 * (lo - hi) / np.minimum(den, -1e-6), 0)  # the peak's parabola
    hgt = SWEEP_H[k] + np.clip(off, -1, 1) * (SWEEP_H[1] - SWEEP_H[0])
    return np.where(score > MIN_SCORE, hgt, np.nan), score, use


def _peaks(v, share=PILE_MIN, step=0.0005):
    """Heights (m) where the votes v pile up: local maxima of their histogram (0.5 mm bins, smoothed over three)
    holding at least share as many votes as the biggest, lowest first."""
    counts, edges = np.histogram(v, bins=np.arange(SWEEP_H[0], SWEEP_H[-1] + step, step))
    counts = np.convolve(counts, [1, 2, 1], "same")
    top = (counts >= share * counts.max()) & (counts >= np.maximum(np.r_[0, counts[:-1]], np.r_[counts[1:], 0]))
    return edges[:-1][top] + step / 2


def _shift(mask, h, cam, Tg):
    """mask moved back by the lean a height h gives it in an orthophoto made from a camera at cam (arm frame):
    projected onto the panel, a point h up lands further from the point under the camera, by h over the
    camera's height of its distance from that point."""
    C = (cam - Tg[:3, 3]) @ Tg[:3, :3] / CELL  # (row, col, height) in cells
    d = (np.argwhere(mask).mean(0) - C[:2]) * h / (C[2] * CELL)
    return ndimage.shift(mask, -d, order=0)


def sweep_part(cand, caps, poses, Tg):
    """The plane sweep over a candidate and 7 mm around it: adds votes (heights, HxW, NaN elsewhere) and panel,
    the panel's height around it, ((row, col), height) or None: the biggest pile of votes 1.5 to 6 mm outside
    its outline, if at least half of them are in it (print near the part; the panel is plain around a display)."""
    m = cand["mask"]
    rr, cc = np.nonzero(m)
    pad = int(0.007 / CELL)
    roi = (max(rr.min() - pad, 0), min(rr.max() + pad + 1, m.shape[0]), max(cc.min() - pad, 0),
           min(cc.max() + pad + 1, m.shape[1]))
    v = np.full(m.shape, np.nan, np.float32)
    v[roi[0]:roi[1], roi[2]:roi[3]] = sweep(caps, poses, Tg, roi)[0]
    grow = lambda mm: cv2.dilate(m.astype(np.uint8), np.ones((2 * int(mm / 1000 / CELL) + 1,) * 2, np.uint8))
    ring = (grow(6) > 0) & (grow(1.5) == 0) & (np.abs(v) < 0.002)
    h, (counts, edges) = v[ring], np.histogram(v[ring], bins=np.arange(-0.002, 0.00201, 0.0005))
    pile = h[np.abs(h - edges[np.argmax(counts)] - 0.00025) < 0.0005] if len(h) else h
    cand.update(votes=v, roi=roi, panel=(np.argwhere(ring).mean(0), float(np.median(pile)))
                if len(pile) >= max(LOCAL_MIN, 0.5 * len(h)) else None)
    return cand


def panel_fix(cands, Tg, shape):
    """The panel as the sweep sees it around the parts: a plane through the panel's height around each part (see
    sweep_part), or their mean with fewer than three or with all of them within a millimetre of one line (three
    buttons in a row leave the tilt across it to noise). The plane through all the print can sit on a lit display's
    text, or tilt, by a millimetre. Returns (that plane's height over Tg's per cell, HxW; a grid frame like Tg on
    that plane)."""
    pts = np.array([[*c["panel"][0], c["panel"][1]] for c in cands if c["panel"] is not None]).reshape(-1, 3)
    a = b = 0.0
    c = pts[:, 2].mean() if len(pts) else 0.0
    if len(pts) >= 3 and np.linalg.svd(pts[:, :2] - pts[:, :2].mean(0), compute_uv=False)[1] * CELL > 0.001:
        a, b, c = np.linalg.lstsq(np.c_[pts[:, :2], np.ones(len(pts))], pts[:, 2], rcond=None)[0]
    i, j = np.ogrid[:shape[0], :shape[1]]
    P = [Tg[:3, 3] + (u * Tg[:3, 0] + v * Tg[:3, 1]) * CELL + (a * u + b * v + c) * Tg[:3, 2]
         for u, v in ((0, 0), (1, 0), (0, 1))]
    return (a * i + b * j + c).astype(np.float32), features.frame(P[0], np.cross(P[1] - P[0], P[2] - P[0]), P[1] - P[0])


def measure(cand, fix, poses, Tg, best):
    """The votes over a candidate (less the panel fix) read as a stack: a plateau (a button's cap, a knob's top
    under its fin, a toggle's base under its lever, a slider's rails under its knob) and maybe an upper part
    rising SUB_STEP over it (fin, lever, slider knob). Votes pile up at several heights (a skirt, a bezel, ticks),
    so each pile is tried as the plateau, and an upper part both as outlined by its votes and as a dial's fin (see
    _bar), as a flat top, or (an outline not round, see ROUND) as a SAM sub-part (see _sam_upper), then without it
    (stray votes on a display's text can look like one). Each is tried on the mask moved back by its lean (see
    _shift) and, for a round outline, on the disc of its top's rim (see _rim). Adds the readings: dicts plateau,
    upper (mask or None), top (its height, or the plateau's) and mask (the footprint), lowest plateau first, and
    round, the outline's circularity."""
    m, roi = cand["mask"], cand["roi"]
    votes = cand["votes"] = cand["votes"] - fix
    near = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    # Piles 1 mm inside the outline: a window straddling the outline votes for heights between the part's and
    # the panel's.
    v = votes[cv2.erode(m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & np.isfinite(votes)]
    cam = poses[np.bincount(best[m & (best >= 0)]).argmax()][:3, 3]  # the capture the orthophoto shows here
    cand["round"] = perceive.region(m, votes, CELL)["circ"]
    readings = []
    for peak in _peaks(v) if len(v) > 50 else [float(np.median(v)) if len(v) else 0.0]:
        plateau = float(np.median(v[np.abs(v - peak) < 0.0005])) if len(v) > 50 else peak
        above = near & (votes > plateau + perceive.SUB_STEP)
        lean = m & _shift(m, plateau, cam, Tg)
        if lean.sum() * CELL ** 2 < MIN_AREA:  # shifted off itself: a pile of stray votes far over the part
            continue
        feet = [lean]
        if cand["round"] >= ROUND:  # a fin's foot votes at the plateau too: its votes and 2 mm round them are left out
            fin = cv2.dilate(above.astype(np.uint8), np.ones((17, 17), np.uint8)).astype(bool)
            disc = _rim(votes, near & ~fin, plateau, lean)
            feet = feet if disc is None else [disc, lean]  # the disc first, so it wins a tie
        up = _upper(votes, above, plateau, m.sum())
        more = []
        if above.sum() > 50:  # a flat top (slider knob, fin) under stray votes well over it (a slider's ticks and
            pile = _peaks(votes[above], share=1.0)[0]  # edges): only votes up to 2 mm over the biggest pile
            flat = _upper(votes, above & (votes < pile + 0.002), plateau, m.sum())
            if flat is not None and (up is None or abs(flat[1] - up[1]) > 0.001):
                more.append((ndimage.binary_fill_holes(flat[0]), flat[1]))
        if up is None and cand["round"] < ROUND:
            sam = _sam_upper(cand["subs"], votes, plateau, m.sum(), cam, Tg)
            more += [sam] if sam is not None else []
        for foot in feet:
            if up is not None:
                readings += [dict(plateau=plateau, mask=foot, upper=ndimage.binary_fill_holes(up[0]), top=up[1]),
                             dict(plateau=plateau, mask=foot, upper=_bar(up[0], foot, roi), top=up[1])]
            readings += [dict(plateau=plateau, mask=foot, upper=u, top=t) for u, t in more]
            readings.append(dict(plateau=plateau, mask=foot, upper=None, top=plateau))
    h = readings[0]["plateau"] if readings else 0.0
    cand.update(readings=readings, subs=[s & _shift(s, h, cam, Tg) for s in cand["subs"]])
    return cand


def _upper(votes, above, plateau, area):
    """An upper part from the cells above (voting SUB_STEP over the plateau): stray votes opened away, gaps closed,
    the biggest piece, its outline the convex hull (plain tops only vote at their rim). It counts if most of the
    votes in the hull are that high (not a few bad matches on repeated print) and it covers more than UPPER_MIN
    and less than UPPER_MAX of the part (area, cells; more is the top itself, over a skirt). Returns (the piece,
    its top: the median of its higher votes, as a lever slopes up to its tip) or None."""
    up = cv2.morphologyEx(cv2.morphologyEx(above.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)),
                          cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    lab, n = ndimage.label(up)
    if not n:
        return None
    big = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
    hull = cv2.fillConvexPoly(np.zeros_like(up), cv2.convexHull(np.argwhere(big)[:, ::-1]), 1).astype(bool)
    hv = votes[hull & np.isfinite(votes)]
    if not (UPPER_MIN < hull.sum() * CELL ** 2 < UPPER_MAX * area * CELL ** 2 and
            np.mean(hv > plateau + perceive.SUB_STEP) > 0.5):
        return None
    return big, float(np.median(hv[hv >= np.mean(np.percentile(hv, [10, 90]))]))


def _sam_upper(subs, votes, plateau, area, cam, Tg):
    """An upper part from SAM's sub-part outlines, for a part not round (see ROUND) whose votes are too few for
    _upper: a chrome lever matches badly, as its highlights move with the camera. The smallest sub-part of an upper
    part's size, moved back by the lean at the height of the votes over the plateau in and 2 mm around it, if 30 or
    more of its votes, a tenth, are that high. Returns (the moved sub-part, its top) or None."""
    for s in sorted(subs, key=np.sum):
        if not UPPER_MIN < s.sum() * CELL ** 2 < UPPER_MAX * area * CELL ** 2:
            continue
        v = votes[cv2.dilate(s.astype(np.uint8), np.ones((17, 17), np.uint8)).astype(bool) &
                  (votes > plateau + perceive.SUB_STEP)]
        if len(v) < 30:
            continue
        s = _shift(s, float(np.median(v)), cam, Tg)
        v = votes[s & np.isfinite(votes)]
        hi = v[v > plateau + perceive.SUB_STEP]
        if len(hi) >= max(30, 0.1 * len(v)):
            return s, float(np.median(hi[hi >= np.mean(np.percentile(hi, [10, 90]))]))
    return None


def _rim(votes, near, h, foot, tol=0.00075):
    """A round top's footprint: the disc whose edge the votes at its height (within 0.75 mm) lie on, fitted with
    RANSAC, if a third of them fit it within tol and they ring at least half of it, and it is about the size of foot
    (the mask moved back by its lean) or smaller by as much as a dial's skirt (0.6 to 1.1 times its area), centred
    within 3.5 mm of it. Its votes sit where the part's top is, unlike the mask, which takes in the skirt and the
    lean of the side. Else None."""
    area, middle = foot.sum(), np.argwhere(foot).mean(0)
    rc = np.argwhere(near & (np.abs(votes - h) < 0.00075)).astype(float)
    if len(rc) < 40:
        return None
    def fit(pts):  # algebraic circle fit: centre, radius
        d, e, f = np.linalg.lstsq(np.c_[pts, np.ones(len(pts))], -(pts ** 2).sum(1), rcond=None)[0]
        c = -np.array([d, e]) / 2
        return c, math.sqrt(max(c @ c - f, 0.0))

    size = lambda r: 0.6 < math.pi * r * r / area < 1.1
    rng, on = np.random.default_rng(0), np.zeros(len(rc), bool)
    for _ in range(200):  # only circles of a size it could be: on a black dial most votes are on the fin and mark
        c, r = fit(rc[rng.choice(len(rc), 3, replace=False)])
        near_c = np.abs(np.linalg.norm(rc - c, axis=1) - r) < tol / CELL
        if size(r) and near_c.sum() > on.sum():
            on = near_c
    if on.sum() < 3:
        return None
    c, r = fit(rc[on])
    if on.mean() < 0.3 or not size(r) or np.linalg.norm(c - middle) * CELL > 0.0035:
        return None
    ang = np.arctan2(*(rc[on] - c).T)
    if len(np.unique(np.floor((ang + math.pi) / (math.pi / 4)))) < 4:  # inliers in at least 4 of 8 sectors
        return None
    i, j = np.ogrid[:votes.shape[0], :votes.shape[1]]
    return (i - c[0]) ** 2 + (j - c[1]) ** 2 <= (r + 0.5) ** 2


def _bar(up, m, roi):
    """A dial's fin: a bar through the middle of the footprint m, along the votes up that rose over the knob
    (the principal axis of their spread about that middle). Black on a black knob, the fin's votes are often only
    its pointer mark and one edge, so the bar reaches as far along and across that axis as they do."""
    i0, i1, j0, j1 = roi
    c = np.argwhere(m).mean(0)
    rc = np.argwhere(up) - c
    axis = np.linalg.eigh(rc.T @ rc)[1][:, 1]
    across = np.array([-axis[1], axis[0]])
    half = np.percentile(np.abs(rc @ axis), 95), max(np.percentile(np.abs(rc @ across), 90), 0.0015 / CELL)
    d = np.stack(np.mgrid[i0:i1, j0:j1], -1) - c
    bar = np.zeros_like(m)
    bar[i0:i1, j0:j1] = (np.abs(d @ axis) <= half[0]) & (np.abs(d @ across) <= half[1])
    return bar


# --- classification ---

def _paint(hm, cand, r):
    """A copy of the height map with a reading written in: the footprint at the plateau, the upper part at its
    own votes (a lever slopes) up to 2 mm over its top (stray votes run higher) and at its top where it has none."""
    hm = hm.copy()
    hm[r["mask"]] = r["plateau"]
    if r["upper"] is not None:
        v = cand["votes"][r["upper"]]
        hm[r["upper"]] = np.where(v > r["plateau"] + perceive.SUB_STEP, np.minimum(v, r["top"] + 0.002), r["top"])
    return hm


def _blob(mask, hm, img, plateau, upper=None):
    """A perceive.segment-style blob, for perceive's size rules and Part builders. Votes stray, so the upper part's
    length and width are read robustly: across a bar, the median distance from its axis is a quarter of its width."""
    b = dict(mask=mask, plateau=plateau, bgr=img[mask].mean(0), **perceive.region(mask, hm, CELL))
    if upper is not None:
        s = b["sub"] = dict(mask=upper, **perceive.region(upper, hm, CELL))
        rc = np.argwhere(upper) - s["centre"]
        s["length"], s["width"] = (4 * np.median(np.abs(rc @ a)) * CELL + CELL
                                   for a in (s["axis"], [-s["axis"][1], s["axis"][0]]))
    return b


def _pad(cand, hm, img):
    """A door, if the candidate is one: a big flat rectangle (the flap) holding a round sub-part about 1 mm
    proud that the size rules read as a push pad. Returns (pad blob, door dict as perceive.find_door's, score,
    why) or None."""
    flap = perceive.region(cand["mask"], hm, CELL)
    if not (0.03 < flap["width"] < 0.12 and flap["fill"] > 0.8):
        return None
    for s in cand["subs"]:
        inner = cv2.erode(s.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        v = cand["votes"][inner & (cand["votes"] > perceive.PROTRUDE)]
        if len(v) < 20:
            continue
        h = _peaks(v)[0]  # the lowest pile: stray votes on its plain face run higher
        h = float(np.median(v[np.abs(v - h) < 0.0005]))
        pad = _blob(s, np.where(s, h, hm), img, h)
        kind, score, why = perceive.classify_blob(pad, CELL)
        if kind == "pad":
            box = cv2.boxPoints(cv2.minAreaRect(np.argwhere(cand["mask"])[:, ::-1].astype(np.float32)))[:, ::-1]
            return pad, dict(corners=box), score, f"a {flap['length'] * 1000:.0f} x {flap['width'] * 1000:.0f} mm " \
                                                  f"flap around a {why}"
    return None


def classify(cands, hm, img):
    """Kind per candidate: each of its readings (see measure) is painted into the height map and scored by
    perceive's size rules, and the best wins; a door is a flap holding a push pad (see _pad). Returns picks, one
    (kind or "unknown", score, why, reading; for a door (pad blob, door dict)) per candidate, and the height map
    with every candidate painted at its pick."""
    picks = []
    for c in cands:
        pick = ("unknown", 0.0, "no reading fits a kind", None)
        for r in sorted(c["readings"], key=lambda r: r["upper"] is None):  # on a tie an upper part wins
            kind, score, why = perceive.classify_blob(_blob(r["mask"], _paint(hm, c, r), img, r["plateau"], r["upper"]),
                                                      CELL)
            if kind == "display" and np.mean(_lit(img[r["mask"]])) < 0.3:  # the green rule has a 61-unit margin:
                kind, score, why = "unknown", 0.0, "flat, but no lit screen"  # a grey slider track scored 0.8 on it
            # SAM outlines a button round (0.98 and up) and a toggle not (0.91 at most): a toggle whose lever got no
            # votes can look like a button, and stray votes over a button like a lever
            if kind in ("button", "toggle") and (c["round"] >= 0.95) != (kind == "button"):
                why = f"{kind} by size, {'not ' * (kind == 'button')}round ({c['round']:.2f})"
                kind, score = "unknown", 0.0
            if kind != "pad" and score > pick[1]:
                pick = (kind, score, why, r)
        w = perceive.region(c["mask"], hm, CELL)["width"]
        r = pick[3] if isinstance(pick[3], dict) else (c["readings"] or [None])[0]
        if (FLAT_BUTTONS and r is not None and pick[0] in ("unknown", "knob", "dial") and c["round"] >= 0.95
                and BUTTON_DIAM[0] <= w <= BUTTON_DIAM[1] and r["plateau"] <= BUTTON_MAX_H):
            pick = ("button", 0.5, f"round, {w * 1000:.0f} mm across, {r['plateau'] * 1000:.1f} mm tall (real-rig rule)", r)
        door = _pad(c, hm, img)
        if door and door[2] > pick[1]:
            pick = ("door", door[2], door[3], door[:2])
        picks.append(pick)
        if pick[0] == "door":
            hm = np.where(pick[3][0]["mask"], pick[3][0]["plateau"], hm)
        elif pick[3] is not None:
            hm = _paint(hm, c, pick[3])
            if pick[0] == "slider":
                hm = _slot(hm, pick[3])
    return picks, hm


def _base(mask):
    """A toggle's footprint without the lever (see LEVER_CUT), cracks closed first. A footprint the disc mostly
    doesn't fit in is a ring round a lever SAM left out: it is kept as it is."""
    m = ndimage.binary_fill_holes(cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
    k = round(LEVER_CUT / CELL) | 1
    out = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return out.astype(bool) if out.sum() > 0.5 * mask.sum() else mask


def _lit(bgr):
    """Lit-LCD green pixels, as perceive._display finds the screen."""
    bgr = bgr.astype(int)
    return bgr[..., 1] - np.maximum(bgr[..., 0], bgr[..., 2]) > 15


def _slot(hm, r):
    """A slider's channel painted down to the panel: the track's middle 3 mm less 3 mm end caps. Its floor is
    plain and dark, so it gets no votes; this prior is where perceive._slider finds the knob's travel."""
    reg = perceive.region(r["mask"], hm, CELL)
    rc = np.argwhere(r["mask"] if r["upper"] is None else r["mask"] & ~r["upper"])
    along, across = (rc - reg["centre"]) @ reg["axis"], (rc - reg["centre"]) @ [-reg["axis"][1], reg["axis"][0]]
    end = 0.5 * reg["length"] / CELL - 0.003 / CELL
    rc = rc[(np.abs(across) < 0.0015 / CELL) & (np.abs(along) < end)]
    hm = hm.copy()
    hm[rc[:, 0], rc[:, 1]] = 0.0
    return hm


def build(cands, picks, hm, img, grid):
    """features.Part per recognised candidate from perceive's per-kind builders, numbered as perceive.classify
    numbers them, a blob record per candidate, and each part's masks on the grid: whole, upper (fin, lever, slider
    knob; or None), subs (SAM's sub-part masks), and for a door flap and pad. Returns (parts, records, masks)."""
    make = dict(button=perceive._button, slider=perceive._slider, dial=perceive._dial, knob=perceive._knob,
                toggle=perceive._toggle, display=perceive._display)
    centre = [np.argwhere(c["mask"]).mean(0) for c in cands]
    order = sorted(range(len(cands)), key=lambda i: (features.KINDS.index(picks[i][0]) if picks[i][0] in features.KINDS
                                                     else len(features.KINDS), centre[i][1], centre[i][0]))
    parts, records, masks, count = [], [], {}, {}
    for i in order:
        kind, score, why, r = picks[i]
        pid, mask = None, cands[i]["mask"]
        if kind == "door":
            p = perceive._door(r[0], r[1], hm, grid)
            m = dict(whole=mask, upper=None, flap=mask, pad=r[0]["mask"])
        elif kind in make:
            mask = r["mask"]
            foot = _base(mask) if kind == "toggle" else mask
            p = make[kind](_blob(foot, hm, img, r["plateau"], r["upper"]), hm, img, grid)
            m = dict(whole=mask, upper=r["upper"])
        if kind in features.KINDS:
            count[kind] = count.get(kind, 0) + 1
            pid = p.id = f"{kind}_{count[kind]}"
            p.score, p.points = score, grid.cells(mask, hm)
            parts.append(p)
            masks[pid] = dict(m, subs=cands[i]["subs"])
        outline = perceive.region(mask, hm, CELL)["outline"]
        records.append(dict(kind=kind, score=round(score, 3), part=pid, why=why,
                            outline=grid.point(outline, np.full(len(outline), 0.0003))))
        if KEEP_REJECTED and kind not in features.KINDS and kind != "door":
            try:  # a candidate that can't be built just isn't offered: it must never stop the scan
                records[-1]["rejected"] = _rejected(cands[i], hm, img, grid)
            except Exception as e:  # noqa: BLE001
                print(f"  a rejected candidate couldn't be kept: {type(e).__name__}: {e}")
    return parts, records, masks


def _rejected(cand, hm, img, grid):
    """A candidate no kind fits as a round part (perceive._knob) and, from a reading with a lever, a toggle
    (perceive._toggle), whichever its readings allow, for a review to name: the real SPEED knob (12 mm across, 15 tall)
    and POWER switch (its outline stretched over the lever and round it) fit no rule in some scans. Returns the knob
    build, else the toggle build, with both in meta["as"]; None when it is wider than a control or neither builds."""
    if perceive.region(cand["mask"], hm, CELL)["width"] > REJECTED_MAX_W:
        return None
    builds = {}
    for r in sorted(cand["readings"], key=lambda r: r["upper"] is None):
        hp = _paint(hm, cand, r)  # its cells at this reading's height: an unknown pick leaves them at the panel's
        tries = {"knob": lambda: perceive._knob(_blob(r["mask"], hp, img, r["plateau"], r["upper"]), hp, img, grid)}
        if r["upper"] is not None:
            tries["toggle"] = lambda: perceive._toggle(_blob(_base(r["mask"]), hp, img, r["plateau"], r["upper"]), hp, img, grid)
        for kind, make in tries.items():
            if kind in builds or (kind == "knob" and r["plateau"] < REJECTED_MIN_H):
                continue
            try:
                builds[kind] = make()
            except Exception:  # noqa: BLE001 - a reading that doesn't build is skipped
                pass
    p = builds.get("knob") or builds.get("toggle")
    if p is not None:
        p.meta = {**p.meta, "as": builds}
    return p


def _on_panel(cand, Tg, survey, margin=0.01):
    """Whether a candidate's centre lies on the survey's panel (within margin): extra views chase only those, as
    cables and boards beside a real panel pulled the arm off to the side."""
    p = Tg[:3, :3] @ [*(np.argwhere(cand["mask"]).mean(0) * CELL), 0] + Tg[:3, 3]
    u, v = (np.linalg.inv(survey["panel"]) @ np.r_[p, 1])[:2]
    u0, u1, v0, v1 = survey["extent"]
    return u0 - margin <= u <= u1 + margin and v0 - margin <= v <= v1 + margin


def _fewest_views(cand, caps, poses, Tg):
    """The fewest main captures that see any one cell of a candidate, at the panel and 12 mm up, clear of the
    gripper. The sweep needs every cell in at least two (each with its partner)."""
    rr, cc = np.nonzero(cand["mask"])
    i0, j0 = rr.min(), cc.min()
    m = cand["mask"][i0:rr.max() + 1, j0:cc.max() + 1]
    seen = sum(np.all([cv2.warpPerspective(_free(c), _homography(c.frame.K, poses[k], Tg, i0, j0, h), m.shape[::-1],
                                           flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0 for h in (0.0, 0.012)],
                      axis=0) for k, c in enumerate(caps) if not c.partner)
    return int(np.min(seen[m]))


def _limits(p, grid, caps, poses):
    """A dial's or knob's stops and detent from its printed scale, in place of perceive._turn_limits: its ring of
    samples misses ticks when the centre is a millimetre or two off, as centres from RGB can be. Here the ticks
    are short radial strokes around the part, found in each main capture projected onto the panel (the part
    hides different ticks from each); their lines meet at its axis, which also moves the part there. The stops
    are the ticks either side of the one gap wider than the rest, as perceive reads them, once stray print off
    the ticks' regular spacing is dropped, and detent 1 is at the counter-clockwise stop. Without a scale the range
    is (0, 0) and there is no detent."""
    c, r = (p.pos - grid.T[:3, 3]) @ grid.T[:3, :2] / CELL, p.meta["knob_radius"] / CELL
    meta = {k: v for k, v in p.meta.items() if k not in ("detent", "detent_step")}
    ring, found = (r - 0.002 / CELL, r + 0.0075 / CELL), []  # the radius can be 3 mm out
    for _ in range(2):  # strokes around where the part was thought to be, then around where they put its axis
        found += _strokes(c, ring, grid, caps, poses)
        if len(found) < 5:
            return replace(p, range=(0.0, 0.0), meta=meta)
        # Where most of their lines meet (some strokes are the knob's edge or print): of the crossings of two
        # lines over 24 deg apart, the one with the most lines passing within 0.5 mm; then least squares on those.
        m, u = (np.array(x) for x in zip(*found))
        i, j = np.tril_indices(len(found), -1)
        det = u[i, 0] * u[j, 1] - u[i, 1] * u[j, 0]
        i, j, det = i[np.abs(det) > 0.4], j[np.abs(det) > 0.4], det[np.abs(det) > 0.4]
        d = m[j] - m[i]
        cross = m[i] + ((d[:, 0] * u[j, 1] - d[:, 1] * u[j, 0]) / det)[:, None] * u[i]
        near = np.abs(u[:, 0] * (cross[:, 1:] - m[:, 1]) - u[:, 1] * (cross[:, :1] - m[:, 0])) < 0.0005 / CELL
        on = near[np.argmax(near.sum(1))] if len(i) else []  # crossings x lines: within 0.5 mm
        if np.sum(on) < 5:
            return replace(p, range=(0.0, 0.0), meta=meta)
        P = np.eye(2) - u[on, :, None] * u[on, None, :]
        c = np.linalg.solve(P.sum(0), np.einsum("kab,kb->a", P, m[on]))
        rho = np.median(np.linalg.norm(m[on] - c, axis=1))  # the ticks' middles
        ring = (rho - 0.0008 / CELL, rho + 0.0025 / CELL)  # their outer part: the knob leans over the inner ends
    # The ticks: strokes whose middles lie on that circle, pointing at the axis within 20 deg (a short stroke's
    # direction is too rough for its line to pass within 0.5 mm of the axis every time)
    lines = [(m, u) for m, u in found if abs(np.linalg.norm(m - c) - rho) < 0.0015 / CELL and
             abs(u @ (c - m)) > 0.94 * np.linalg.norm(c - m)]
    ang = np.sort([math.atan2(c[1] - m[1], c[0] - m[0]) % (2 * math.pi) for m, _ in lines])  # ccw from up the slope
    ticks = ang[np.diff(np.r_[ang[-1] - 2 * math.pi, ang]) > math.radians(8)]  # one per tick, seen in several captures
    step = float(np.median(np.diff(np.r_[ticks, ticks[0] + 2 * math.pi])))
    off = lambda t0: np.abs((ticks - t0 + step / 2) % step - step / 2)  # stray print near the scale falls off the
    ticks = ticks[off(max(ticks, key=lambda t0: np.sum(off(t0) < 0.25 * step))) < 0.25 * step]  # ticks' spacing
    gaps = np.diff(np.r_[ticks, ticks[0] + 2 * math.pi])
    o = grid.point(c, p.size[2] if p.kind == "knob" else meta["knob_height"])
    p = replace(p, T=features.frame(o, grid.n, p.x), origin=o, range=(0.0, 0.0), meta=meta)
    # A gap is the scale's only if a capture saw where its missing ticks would be: the part hides the ticks on
    # its far side from every capture, which leaves gaps that only look empty. A tick the scan missed leaves a gap
    # too, so with two such gaps the stops stay unknown.
    wide = [i for i in np.flatnonzero(gaps > 1.5 * step)
            if all(_clear(c + rho * np.array([-math.cos(a), -math.sin(a)]), c, r + 0.0005 / CELL, p.size[2], grid, caps,
                          poses) for a in ticks[i] + step * np.arange(1, round(gaps[i] / step)))]
    if len(ticks) < 5 or len(wide) != 1 or "angle" not in meta:
        return p
    lo, hi = ticks[(wide[0] + 1) % len(ticks)], ticks[wide[0]]  # the stops turning clockwise and counter-clockwise
    span = (hi - lo) % (2 * math.pi)
    s = (meta["angle"] - lo) % (2 * math.pi)  # the pointer's way along the scale
    if s > span:  # a hair past a stop: put it on the nearer one
        s = span if s - span < 2 * math.pi - s else 0.0
    meta.update(detent=1 + round((span - s) / step), detent_step=step)
    return replace(p, range=(-s, span - s), meta=meta)


def _clear(P, c, r, h, grid, caps, poses):
    """Whether some main capture sees panel cell P (grid row, col) clear of the gripper and not hidden behind a
    cylinder at c, r cells across and h (m) tall: the ray from P to the camera, up to height h, misses it."""
    for k, cap in enumerate(caps):
        (u, v), _ = (a[0] for a in _project(cap.frame.K, poses[k], grid.point(P, 0.0)[None]))
        hgt, wid = cap.frame.rgb.shape[:2]
        if cap.partner or not (10 < u < wid - 10 and 10 < v < hgt - 10) or \
                cv2.pointPolygonTest(_gripper(wid), (float(u), float(v)), False) >= 0:
            continue
        C = (poses[k][:3, 3] - grid.T[:3, 3]) @ grid.T[:3, :3] / CELL  # the camera: row, col, height in cells
        Q = P + (C[:2] - P) * h / (C[2] * CELL)
        t = np.clip((c - P) @ (Q - P) / max((Q - P) @ (Q - P), 1e-9), 0, 1)
        if np.linalg.norm(P + t * (Q - P) - c) > r:
            return True
    return False


def _strokes(c, ring, grid, caps, poses):
    """Short radial strokes (printed ticks) in a ring around c (inner and outer radius, cells), in each main
    capture projected onto the panel: (point, unit direction) per stroke, grid cells."""
    half = int(ring[1]) + 2
    i0, j0 = int(c[0]) - half, int(c[1]) - half
    i, j = np.ogrid[:2 * half, :2 * half]
    d = np.hypot(i + i0 - c[0], j + j0 - c[1])
    panel = (d > ring[0] - 0.0005 / CELL).astype(np.float32)  # the part left out of the panel's local brightness:
    ring = (d > ring[0]) & (d < ring[1])                       # a dark knob would light up a white panel around it
    flags, size, lines = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, (2 * half, 2 * half), []
    for k, cap in enumerate(caps):
        if cap.partner:
            continue
        H = _homography(cap.frame.K, poses[k], grid.T, i0, j0, 0.0)
        grey = cv2.cvtColor(cap.frame.rgb, cv2.COLOR_BGR2GRAY)
        grey = cv2.warpPerspective(grey, H, size, flags=flags).astype(np.float32)
        seen = cv2.warpPerspective(_free(cap), H, size, flags=flags) > 0.99
        bg = cv2.blur(grey * panel, (41, 41)) / np.maximum(cv2.blur(panel, (41, 41)), 1e-3)
        ink = np.abs(grey / np.maximum(bg, 10) - 1) > 0.25  # print against the panel around it
        lab, _ = ndimage.label(ink & ring & seen)
        for n, s in enumerate(ndimage.find_objects(lab)):
            rc = np.argwhere(lab[s] == n + 1) + [s[0].start + i0, s[1].start + j0]
            if len(rc) < 6:
                continue
            m = rc.mean(0)
            u = np.linalg.eigh(np.cov((rc - m).T))[1][:, 1]
            long, wide = (np.ptp((rc - m) @ a) * CELL for a in (u, [-u[1], u[0]]))
            if 0.0012 < long < 0.005 and wide < 0.002 and abs(u @ (c - m)) > 0.94 * np.linalg.norm(c - m):  # 20 deg
                lines.append((m, u))
    return lines


# --- touch hints ---

def touch_hints(parts, taken, hm, grid):
    """Where a touch would tell the probe most, arm frame: {"panel": three clear spots on the panel, far apart,
    for its plane, PLANE_CLEAR from every cell taken (taken: every candidate, recognised or not); part id:
    [(point, purpose)]}, purposes "top" (a button's or knob's cap), "plateau" (a dial's top, off its fin), "knob" (a
    slider's), "toggle base" (the end of the base away from the lever, which a touch could flip) and "pad" (a door's
    push pad)."""
    clear = cv2.distanceTransform((~taken & np.isfinite(hm)).astype(np.uint8), cv2.DIST_L2, 5) * CELL > PLANE_CLEAR
    inset = int((ORTHO_MARGIN + PLANE_INSET) / CELL)  # off the survey's panel edge, where the probe can't land square
    clear[:inset], clear[-inset:], clear[:, :inset], clear[:, -inset:] = False, False, False, False
    rc = np.argwhere(clear)[::97]
    hints = {"panel": []}
    if len(rc) >= 3:
        a = rc[np.argmax(np.linalg.norm(rc - rc.mean(0), axis=1))]
        b = rc[np.argmax(np.linalg.norm(rc - a, axis=1))]
        c = rc[np.argmax(np.abs((b - a)[0] * (rc - a)[:, 1] - (b - a)[1] * (rc - a)[:, 0]))]  # the biggest triangle
        hints["panel"] = [(grid.point(x, 0.0), "plane") for x in (a, b, c)]
    for p in parts:
        side, m = np.cross(p.normal, p.x), p.meta
        hints[p.id] = {"button": [(p.pos, "top")], "knob": [(p.pos, "top")], "slider": [(p.pos, "knob")],
                       "door": [(p.pos, "pad")],
                       "dial": [(p.pos + (m.get("fin_width", 0) / 2 + m.get("knob_radius", 0)) / 2 * side, "plateau")],
                       "toggle": [(p.pos - (m.get("base_size", [0])[0] / 2 - 0.003) * p.x, "toggle base")]
                       }.get(p.kind, [])
    return hints
