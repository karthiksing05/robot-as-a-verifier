"""Find a device's controls with cameras alone: no CAD, no tags on the device.

    scene = perceive(arm, PhoneCamera(arm), WristCamera(arm))   # moves the arm, then parks it home
    scene.parts                        # features.Part list in the arm frame
    p = refine(arm, wrist, p)          # at a skill's approach pose: p re-measured from one wrist frame
    evaluate(scene.parts, w.truth(arm.m, arm.d))                 # sim check; perceive() never sees truth

Stages: survey (phone LiDAR: device box, coarse panel plane), views (wrist poses the arm can
reach), scan (move, settle, capture, register each frame to the cloud so far), fuse (voxel
average), plane (fine panel plane), heightmap, segment (blobs above and below the plane),
classify (size rules per kind, then a features.Part per blob). perceive() reads only camera
frames and the arm's joint readings, plus the arm's own geometry to crop it out of the clouds.

Parts follow device.truth()'s conventions and meta keys, except what vision can't measure: a
button's travel and switch point, and a door's push travel, are left out (range (0, 0) means
unknown). A dial's or knob's stops and detent come from its printed scale when that reads, and a
toggle's "on" assumes up the slope or to the arm's right is ON. Positions sit in the frame of
the first wrist view, so they carry that view's few-mm calibration error, which the probe shares
in part when the same arm acts on them. refine() removes most of the rest just before an action.
"""
import math
import time
from dataclasses import dataclass, field, replace
from functools import partial

import cv2
import mujoco
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

import features
import rig
import skills
from rig import TABLE_Z, SafetyStop

# survey (phone LiDAR)
SURVEY_BOX = np.array([[0.08, 0.6], [-0.35, 0.35], [TABLE_Z + 0.01, 0.35]])  # where a device can sit


def set_table_z(z):
    """The surface the device stands on, in the arm's frame, where a rig's isn't the default."""
    global TABLE_Z
    TABLE_Z = z
    SURVEY_BOX[2, 0] = z + 0.01


LIDAR_EDGE_M = 0.02     # depth spread over ~2 LiDAR pixels above this: a blurred silhouette, not a surface
SURVEY_VOXEL = 0.005
COARSE_THR = 0.004
# wrist views: look-at offsets from the panel centre (up the slope, to the arm's left), a 3x3 grid
# walked as a loop from the centre, whose frame anchors registration and overlaps every other.
# Fewer views left the panel behind tall parts (dial, toggle) seen by one frame or none.
VIEW_LOOKS = [(0.0, 0.0), (0.0, -0.05), (0.05, -0.05), (0.05, 0.0), (0.05, 0.05), (0.0, 0.05),
              (-0.05, 0.05), (-0.05, 0.0), (-0.05, -0.05)]
# Views tip toward horizontal: straight along -normal is often out of reach. A view the first tilt
# can't reach (far, shallow panels) tries the next, which brings the camera lower and nearer.
VIEW_TILTS = np.radians([10, 20, 30])
MIN_TIP_CLEAR = 0.03
SETTLE_TICKS = 15
PROBE_CROP = 0.09       # wrist points nearer the camera than this are the probe (8 to 8.4 cm)
BOX_MARGIN = 0.03       # the LiDAR box can be a few cm short on the side the phone can't see
ICP_POINTS = 20000
ICP_HUBER = 0.0003
MIN_POINTS = 5000
# fusion, plane, height map
VOXEL = 0.00075
MIN_FRAMES = 2
FINE_THR = 0.0008
CELL = 0.0005
# segmentation
PROTRUDE = 0.0006       # above the plane: about 7 sigma of the fused panel's noise. Not scaled up with
                        # the measured noise: low tops near the plane (a display, slider rails) inflate
                        # that estimate, and a 1 mm door pad or slider rail then fell below it
MIN_BLOB = 15e-6        # m^2; smaller blobs are noise
SUB_STEP = 0.0025       # a blob's upper part (fin, lever, slider knob) rises this far above its plateau
RECESS = 0.001          # below the plane: the door seam
# refine (one wrist frame from a skill's approach pose)
REFINE_SHIFT = 0.01     # a part found further than this from where it was believed is another part
                        # (only buttons repeat on a device, 23 mm or more apart)
REFINE_PANEL = 0.006    # panel kept around the part's footprint for the plane fit
# From a skill's approach pose the probe hides part of the target (half a dial, from a turn's hover
# pose) and a leaning lever hides its own lower length, so refine checks a blob against the size
# rules that its outline doesn't set.
OUTLINE = ("diam", "circ", "area", "length", "fill", "sub_off", "sub_len")


@dataclass
class Scene:
    parts: list = field(default_factory=list)       # features.Part, arm frame
    survey: dict = field(default_factory=dict)      # points, colors (RGB), box (8x3), panel (4x4), extent
    frames: list = field(default_factory=list)      # rig.Frame: the phone's, then every wrist frame
    cloud: tuple = None      # (Nx3 points, Nx3 uint8 RGB), fused, arm frame
    plane: tuple = None      # (4x4 panel frame, z outward, x down the slope; (u0, u1, v0, v1) extent, m)
    heightmap: tuple = None  # (HxW height above the plane, m, NaN empty; HxWx3 BGR; cell m; (u0, v0) of cell [0, 0])
    blobs: list = field(default_factory=list)       # dicts: kind, score, outline (Nx3), part (id or None), why
    timings: dict = field(default_factory=dict)     # stage -> seconds
    views: list = field(default_factory=list)       # planned wrist views: dicts q, T (believed camera pose),
                                                    # look (point), tilt (deg), ok, why (if unreachable)
    rejected: list = field(default_factory=list)    # with rgbperceive.KEEP_REJECTED: Parts (ids cand_k) for candidates
                                                    # no kind fit, for a review to name; never in parts


def perceive(arm, phone, wrist, on_stage=None, on_frame=None):
    """Survey, scan and segment the device in front of the arm. on_stage(name, scene) runs at the
    start of each stage, on_frame(frame, (points, rgb)) after each wrist capture."""
    scene, clock = Scene(), [None, time.perf_counter()]

    def stage(name):
        now = time.perf_counter()
        if clock[0]:
            scene.timings[clock[0]] = round(now - clock[1], 3)
        clock[:] = [name, now]
        if on_stage:
            on_stage(name, scene)

    stage("survey")
    scene.frames.append(phone.capture())
    scene.survey = survey(arm, scene.frames[0])
    stage("views")
    scene.views = plan_views(arm, scene.survey)
    stage("scan")
    frames, clouds = scan(arm, wrist, scene.views, scene.survey["box"], on_frame)
    scene.frames += frames
    stage("fuse")
    pts, rgb, _, seen = fuse(clouds)
    two = seen >= MIN_FRAMES  # seen twice: a lone frame's stray point can't spike the height map
    scene.cloud = (pts[two], rgb[two])
    stage("plane")
    scene.plane = fit_panel(pts[two], scene.survey["panel"])
    stage("heightmap")
    # cells only one frame saw (often behind a tall part) take that frame's points over a hole
    scene.heightmap = height_map(pts[two], rgb[two], *scene.plane, spare=(pts[~two], rgb[~two]))
    hm, img, cell, origin = scene.heightmap
    grid = Grid(scene.plane[0], cell, origin)
    stage("segment")
    blobs, door, _ = segment(hm, img, cell)
    scene.blobs = [dict(kind=None, score=0.0, part=None, why="", outline=grid.point(b["outline"], 0.0003))
                   for b in blobs]
    stage("classify")
    scene.parts, scene.blobs = classify(blobs, door, hm, img, grid)
    stage("done")
    return scene


# --- survey ---

def survey(arm, f):
    """Device box and coarse panel plane from the phone's LiDAR frame."""
    pts, rgb, px = rig.backproject(f, stride=2)
    d, k = f.depth, np.ones((11, 11), np.uint8)
    spread = cv2.dilate(d, k) - cv2.erode(np.where(d > 0, d, 9.0).astype(np.float32), k)
    keep = (spread[px[:, 1], px[:, 0]] < LIDAR_EDGE_M) & _inside(pts, _survey_box(arm)) & ~_on_arm(arm, pts)
    pts, rgb = pts[keep], rgb[keep]
    dev = _largest_cluster(pts, SURVEY_VOXEL)
    pts, rgb = pts[dev], rgb[dev]
    foot = cv2.boxPoints(cv2.minAreaRect(pts[:, :2].astype(np.float32)))  # corners going around
    top = np.percentile(pts[:, 2], 99.5)
    box = np.vstack([np.c_[foot, np.full(4, arm.table_z)], np.c_[foot, np.full(4, top)]])
    T, extent = _coarse_panel(pts, f.T_base_cam[:3, 3])
    return dict(points=pts, colors=rgb, box=box, panel=T, extent=extent)


def _survey_box(arm):
    """SURVEY_BOX with its floor 1 cm over the arm's desk."""
    box = SURVEY_BOX.copy()
    box[2, 0] = arm.table_z + 0.01
    return box


def _inside(pts, box):
    return np.all((pts >= box[:, 0]) & (pts <= box[:, 1]), axis=1)


def _on_arm(arm, pts, margin=0.01):
    """Points inside the arm's own geoms (local bounding boxes plus a margin), posed by forward
    kinematics of the joint readings."""
    m = arm.m
    fk = mujoco.MjData(m)
    fk.qpos[arm.qadr] = arm.read_q()
    mujoco.mj_kinematics(m, fk)
    out = np.zeros(len(pts), bool)
    for b in arm.arm_bodies:
        for g in range(m.body_geomadr[b], m.body_geomadr[b] + m.body_geomnum[b]):
            loc = (pts - fk.geom_xpos[g]) @ fk.geom_xmat[g].reshape(3, 3) - m.geom_aabb[g, :3]
            out |= np.all(np.abs(loc) < m.geom_aabb[g, 3:] + margin, axis=1)
    return out


def _largest_cluster(pts, voxel):
    """Mask of the points in the largest 26-connected group of occupied voxels."""
    vox = np.floor(pts / voxel).astype(int)
    vox -= vox.min(0)
    grid = np.zeros(vox.max(0) + 1, bool)
    grid[tuple(vox.T)] = True
    lab, n = ndimage.label(grid, np.ones((3, 3, 3)))
    sizes = np.bincount(lab[tuple(vox.T)])
    sizes[0] = 0
    return lab[tuple(vox.T)] == np.argmax(sizes)


def ransac_plane(pts, thr, iters=300, normal=None, max_deg=20, rng=None):
    """(unit normal, point on the plane, inlier mask), refit by least squares. With `normal`, only
    planes within max_deg of it count."""
    rng = rng or np.random.default_rng(0)
    best, best_n = None, -1
    for _ in range(iters):
        s = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        if normal is not None and abs(n @ normal) < math.cos(math.radians(max_deg)):
            continue
        k = np.count_nonzero(np.abs((pts - s[0]) @ n) < thr)
        if k > best_n:
            best, best_n = (n, s[0]), k
    n, p = best
    for _ in range(2):
        inl = np.abs((pts - p) @ n) < thr
        p = pts[inl].mean(0)
        n = np.linalg.svd(pts[inl] - p, full_matrices=False)[2][2]
    if normal is not None and n @ normal < 0:
        n = -n
    return n, p, np.abs((pts - p) @ n) < thr


def plane_frame(n, p):
    """4x4 frame on a sloped plane: z = n, x down the slope, y to the arm's right (so x, y index a
    height map that reads like the panel seen from the arm), origin p."""
    up = np.array([0, 0, 1.0]) - n[2] * n
    return features.frame(p, n, -up)


PANEL_NZ = (0.3, 0.95)  # the panel's normal's up component: tilted between about 18 and 73 deg from flat
PANEL_PLANES, PANEL_MIN_PTS = 4, 100  # planes tried, and the points that must be left to try another
PANEL_GROUP = None  # m: when set, the panel's extent comes from its plane's largest group of points this close on a grid
VERTICAL_NZ = -0.1  # an upright panel may lean back this far (its normal's z)


LEVER_MIN_H, LEVER_R = 0.010, 0.002  # a lever's tip stands this far up at least (a 6.8 mm reading was the base alone; 11.7 the real lever); its radius (the toggle readings: 1.5-2.7 mm)


def lever_from_points(p, plane):
    """A switch the scan read as something else (a knob) and the model named a switch, as a toggle flip() can plan: the
    lever's tip is its highest measured point, its lean (x) the way that tip leans from the hinge (the part's origin).
    On the real POWER switch that came within 4-6 mm of the toggle readings' tips, leaning the same way. None when the
    highest point is under LEVER_MIN_H: one reading's was 6.8 mm, the base alone, and leaned the wrong way."""
    n, o = plane[:3, 2], plane[:3, 3]
    pts = np.asarray(p.points if p.points is not None else np.zeros((0, 3)))
    if not len(pts) or ((pts - o) @ n).max() < LEVER_MIN_H:
        return None
    tip = pts[np.argmax((pts - o) @ n)]
    lean = (tip - p.pos) - ((tip - p.pos) @ n) * n
    if np.linalg.norm(lean) < 1e-3:
        return None
    x = lean / np.linalg.norm(lean)
    q = replace(p, meta=dict(p.meta))
    q.T = q.T.copy()
    q.T[:3, :3] = np.c_[x, np.cross(n, x), n]
    q.kind = "toggle"
    q.meta = {**p.meta, "tip": tip, "lever_radius": LEVER_R, "lever_len": float(np.linalg.norm(tip - p.pos)) + LEVER_R}
    return q


def panel_candidates(pts, cam_pos):
    """Every plane the coarse panel fit tries, each the biggest left, as (normal toward the camera, point, inlier
    indices into pts, faces the arm), and the index of the control panel among them: the biggest that faces up and
    toward the arm, or with none, the biggest that faces the arm upright (a wall thermostat's face: n_z down to
    VERTICAL_NZ). None if neither."""
    rest, cands = np.ones(len(pts), bool), []
    for _ in range(PANEL_PLANES):
        if rest.sum() < PANEL_MIN_PTS:
            break
        n, p, inl = ransac_plane(pts[rest], COARSE_THR)
        if n @ (cam_pos - p) < 0:
            n = -n
        toward_arm = bool(-p[:2] @ n[:2] > 0.5 * np.linalg.norm(n[:2]) * np.linalg.norm(p[:2]))
        cands.append((n, p, np.flatnonzero(rest)[inl], toward_arm))
        rest[cands[-1][2]] = False
    tilted = [k for k, c in enumerate(cands) if PANEL_NZ[0] < c[0][2] < PANEL_NZ[1] and c[3]]
    upright = [k for k, c in enumerate(cands) if VERTICAL_NZ < c[0][2] <= PANEL_NZ[0] and c[3]]
    return cands, max(tilted or upright, key=lambda k: len(cands[k][2]), default=None)


def panel_frame(pts, cand):
    """A panel_candidates plane as a plane frame (z toward the camera) and its extent (u0, u1, v0, v1) in that frame."""
    n, p, idx, _ = cand
    T = plane_frame(n, p)
    uv = (pts[idx] - p) @ T[:3, :2]
    if PANEL_GROUP:
        uv = uv[_largest_group(uv, PANEL_GROUP)]
    (u0, v0), (u1, v1) = np.percentile(uv, 1, axis=0), np.percentile(uv, 99, axis=0)
    T[:3, 3] = p + T[:3, :2] @ [(u0 + u1) / 2, (v0 + v1) / 2]
    return T, ((u0 - u1) / 2, (u1 - u0) / 2, (v0 - v1) / 2, (v1 - v0) / 2)


def _largest_group(uv, cell):
    """Which of the points uv (Nx2, m) are in the largest group joined through occupied cells of this size on a grid."""
    ij = np.floor((uv - uv.min(0)) / cell).astype(int)
    grid = np.zeros(ij.max(0) + 1, bool)
    grid[ij[:, 0], ij[:, 1]] = True
    label = ndimage.label(ndimage.binary_dilation(grid))[0][ij[:, 0], ij[:, 1]]
    return label == np.bincount(label).argmax()


NO_PANEL = "no control panel in the scan: no plane of 100+ points faces the arm, either tilted up toward the camera or upright"


def _coarse_panel(pts, cam_pos):
    """The control panel (panel_candidates' pick) as panel_frame gives it."""
    cands, pick = panel_candidates(pts, cam_pos)
    if pick is None:
        raise ValueError(NO_PANEL)
    return panel_frame(pts, cands[pick])


# --- wrist views and the scan ---

def _camera_pose(arm, fk, cam, q):
    """Wrist camera pose (OpenCV axes) the controller would believe at joint angles q."""
    fk.qpos[arm.qadr] = q
    mujoco.mj_kinematics(arm.m, fk)
    mujoco.mj_camlight(arm.m, fk)
    return rig._cv_pose(fk, cam)


def plan_views(arm, surv):
    """Wrist views over the coarse panel. The arm can't always point the camera where asked (4
    joints aim the tool), so each view is re-aimed: the camera moves until the direction it does
    reach passes through the look-at point."""
    T = surv["panel"]
    c, down, n = T[:3, 3], T[:3, 0], T[:3, 2]
    left = -T[:3, 1]
    site, cam = arm.m.site("wrist_cam").id, arm.m.camera("wrist_cam").id
    fk = mujoco.MjData(arm.m)
    views, q0 = [], arm.home_q.copy()
    for du, dv in VIEW_LOOKS if getattr(arm, "view_looks", None) is None else arm.view_looks:
        look = c - du * down + dv * left
        for tilt in VIEW_TILTS if getattr(arm, "view_tilts", None) is None else arm.view_tilts:
            view = aim = -n * math.cos(tilt) - down * math.sin(tilt)
            for _ in range(3):
                q, ok, err, _ = arm.ik.solve(look - arm.standoff * aim, view, q0, site=site)
                aim = arm.ik.fk(q, site)[1]
            clear = (arm.ik.fk(q)[0] - c) @ n
            why = ""
            if err > 1e-3:
                why = f"camera {err * 1000:.0f} mm short of its pose"
            elif clear < (getattr(arm, "tip_clear", None) or MIN_TIP_CLEAR):
                why = f"probe tip only {clear * 1000:.0f} mm off the panel"
            if not why:
                break
        views.append(dict(q=q, T=_camera_pose(arm, fk, cam, q), look=look, ok=not why, why=why,
                          tilt=round(math.degrees(tilt))))
        if not why:
            q0 = q
    return views


def scan(arm, wrist, views, box, on_frame=None):
    """Visit each reachable view, settle, capture, and register the frame to the cloud so far.
    Returns the wrist frames and their registered clouds (points, RGB, normals)."""
    frames, clouds = [], []
    for v in views:
        if not v["ok"]:
            continue
        try:
            skills.move_joints(arm, v["q"])
            for _ in range(SETTLE_TICKS):
                arm.send(v["q"])
                arm.tick()
        except SafetyStop as e:  # the arm has backed off; count the view as unreachable
            v.update(ok=False, why=f"safety stop on the way: {e}")
            continue
        frames.append(wrist.capture())
        cloud = wrist_points(frames[-1], box)
        if len(cloud[0]) >= MIN_POINTS:  # a frame that saw almost nothing of the device adds nothing
            clouds.append(register(cloud, clouds))
        if on_frame:
            on_frame(frames[-1], fuse(clouds)[:2] if clouds else (np.zeros((0, 3)), np.zeros((0, 3), np.uint8)))
    skills.go_home(arm)
    return frames, clouds


# --- registration and fusion ---

def wrist_points(f, box):
    """A wrist frame's arm-frame points, RGB and normals, cropped to the device box and away from
    the probe."""
    pts, rgb, px = rig.backproject(f)
    z = f.depth[px[:, 1], px[:, 0]]
    nrm = rig.normals(f)[px[:, 1], px[:, 0]]
    keep = (z > PROBE_CROP) & _in_box(pts, box, BOX_MARGIN) & np.any(nrm != 0, axis=1)
    return pts[keep], rgb[keep], nrm[keep]


def _in_box(pts, box, margin):
    """Points inside the survey box (8 corners, bottom face first, on the desk) grown by margin, above the desk."""
    c, ok = box.mean(0), pts[:, 2] > box[0, 2] + 0.005
    for e in ((box[1] - box[0]) / 2, (box[3] - box[0]) / 2, (box[4] - box[0]) / 2):
        half = np.linalg.norm(e)
        ok &= np.abs((pts - c) @ (e / half)) < half + margin
    return ok


def register(cloud, model):
    """The cloud moved onto the registered clouds so far (unchanged if it is the first). Each
    view's believed pose carries its own few-mm error from the joint offsets, so fusing
    unregistered frames would double every edge."""
    if not model:
        return cloud
    mp, _, mn, _ = fuse(model)
    pts, rgb, nrm = cloud
    sel = np.random.default_rng(0).choice(len(pts), min(ICP_POINTS, len(pts)), replace=False)
    T = icp(pts[sel], nrm[sel], mp, mn)
    return pts @ T[:3, :3].T + T[:3, 3], rgb, nrm @ T[:3, :3].T


def icp(src, src_n, dst, dst_n, iters=20):
    """4x4 rigid motion taking src onto dst: point-to-plane ICP, Huber-weighted, with a shrinking
    match radius. Rotations are about the source centroid so they don't couple with translation."""
    tree, c0 = cKDTree(dst), src.mean(0)
    R, t = np.eye(3), np.zeros(3)
    for it in range(iters):
        p = (src - c0) @ R.T + c0 + t
        dist, j = tree.query(p, distance_upper_bound=max(0.004 * 0.75 ** it, 0.0008))
        ok = np.isfinite(dist)
        ok[ok] = np.einsum("ij,ij->i", src_n[ok] @ R.T, dst_n[j[ok]]) > 0.8
        q, n, p = dst[j[ok]], dst_n[j[ok]], p[ok]
        r = np.einsum("ij,ij->i", p - q, n)
        w = np.minimum(1.0, ICP_HUBER / np.maximum(np.abs(r), 1e-12))
        A = np.c_[np.cross(p - c0 - t, n), n]
        H = (A * w[:, None]).T @ A
        x = np.linalg.solve(H + 1e-9 * np.trace(H) * np.eye(6), -(A * w[:, None]).T @ r)
        R, t = cv2.Rodrigues(x[:3])[0] @ R, t + x[3:]
        if np.linalg.norm(x[3:]) < 1e-6 and np.linalg.norm(x[:3]) < 1e-5:
            break
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, c0 + t - R @ c0
    return T


def fuse(clouds, voxel=VOXEL):
    """Voxel averages of position, RGB and normal over the clouds, and how many frames saw each
    voxel: (points, uint8 RGB, normals, frames)."""
    P = np.vstack([c[0] for c in clouds])
    fid = np.concatenate([np.full(len(c[0]), i) for i, c in enumerate(clouds)])
    k = np.floor(P / voxel).astype(np.int64)
    k -= k.min(0)
    span = k.max(0) + 1
    _, inv, cnt = np.unique((k[:, 0] * span[1] + k[:, 1]) * span[2] + k[:, 2], return_inverse=True,
                            return_counts=True)

    def avg(a):
        return np.stack([np.bincount(inv, a[:, i]) for i in range(3)], 1) / cnt[:, None]

    n = avg(np.vstack([c[2] for c in clouds]))
    rgb = np.round(avg(np.vstack([c[1] for c in clouds]).astype(float))).astype(np.uint8)
    seen = np.bincount(np.unique(inv * len(clouds) + fid) // len(clouds))
    return avg(P), rgb, n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12), seen


# --- panel plane and height map ---

def fit_panel(pts, coarse):
    """Fine panel plane near the coarse one: (4x4 plane frame, (u0, u1, v0, v1) extent of its inliers)."""
    n, p, inl = ransac_plane(pts, FINE_THR, normal=coarse[:3, 2], max_deg=15)
    T = plane_frame(n, p)
    uv = (pts[inl] - p) @ T[:3, :2]
    (u0, v0), (u1, v1) = np.percentile(uv, 0.5, axis=0), np.percentile(uv, 99.5, axis=0)
    return T, (u0, u1, v0, v1)


def height_map(pts, rgb, T, extent, spare=None, cell=CELL, margin=0.005):
    """Highest point per cell over the plane: (HxW float32 height (m), NaN where empty; HxWx3 BGR;
    cell; (u0, v0) plane coordinates of cell [0, 0]). Rows run along the frame's x (down the
    slope), columns along y. spare (points, RGB) fills cells the main cloud left empty; then cells
    a voxel missed take the mean of their filled neighbours."""
    u0, u1, v0, v1 = extent[0] - margin, extent[1] + margin, extent[2] - margin, extent[3] + margin
    H, W = int((u1 - u0) / cell) + 1, int((v1 - v0) / cell) + 1
    hm, img = np.full(H * W, np.nan, np.float32), np.zeros((H * W, 3), np.uint8)
    for p, rgb_ in [(pts, rgb)] + ([spare] if spare is not None else []):
        a, b, h = ((p - T[:3, 3]) @ T[:3, :3]).T
        i, j = np.round((a - u0) / cell).astype(int), np.round((b - v0) / cell).astype(int)
        ok = (i >= 0) & (i < H) & (j >= 0) & (j < W) & (h > -0.01) & (h < 0.05)
        c, h, col = i[ok] * W + j[ok], h[ok], rgb_[ok]
        order = np.lexsort((h, c))
        last = order[np.r_[c[order][1:] != c[order][:-1], True]]  # the highest point in each cell
        new = np.isnan(hm[c[last]])
        hm[c[last][new]], img[c[last][new]] = h[last][new], col[last][new][:, ::-1]
    hm, img = hm.reshape(H, W), img.reshape(H, W, 3)
    for _ in range(2):
        ok = np.isfinite(hm)
        k = np.ones((3, 3), np.float32)
        cnt = cv2.filter2D(ok.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        s = cv2.filter2D(np.where(ok, hm, 0).astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        si = cv2.filter2D(np.where(ok[..., None], img, 0).astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        fill = ~ok & (cnt >= 3)
        hm[fill] = s[fill] / cnt[fill]
        img[fill] = np.round(si[fill] / cnt[fill][:, None]).astype(np.uint8)
    return hm, img, cell, (u0, v0)


# --- segmentation ---

def plane_noise(hm):
    """Robust sigma (m) of the flat panel in the height map."""
    flat = hm[np.isfinite(hm) & (np.abs(hm) < 0.001)]
    return 1.4826 * float(np.median(np.abs(flat - np.median(flat))))


def region(mask, hm, cell):
    """Shape of a height-map region: centre and long axis (row, col), length and width along and
    across that axis, area, circularity of its convex hull, fill of its oriented box, heights (m)."""
    rc = np.argwhere(mask).astype(float)
    centre = rc.mean(0)
    axis = np.linalg.eigh(np.cov((rc - centre).T))[1][:, 1] if len(rc) > 2 else np.array([1.0, 0.0])
    along, across = (rc - centre) @ axis, (rc - centre) @ [-axis[1], axis[0]]
    length, width = (np.ptp(along) + 1) * cell, (np.ptp(across) + 1) * cell
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    hs = hm[mask & np.isfinite(hm)]
    area = len(rc) * cell ** 2
    return dict(centre=centre, axis=axis, length=length, width=width, area=area,
                circ=4 * math.pi * cv2.contourArea(hull) / max(cv2.arcLength(hull, True), 1e-9) ** 2,
                fill=area / (length * width), h_max=float(np.percentile(hs, 98)) if len(hs) else 0.0,
                outline=c[:, 0, ::-1])


def segment(hm, img, cell):
    """Blobs above the plane, and the door seam below it. A blob is region() of its cells plus its
    mask, plateau (most common height: knob top, toggle base, slider rails) and, if it rises
    SUB_STEP above that plateau, its upper part ("sub": a dial's fin, a toggle's lever, a slider's
    knob). Returns (blobs, door or None, plane noise sigma)."""
    sigma = plane_noise(hm)
    h = np.nan_to_num(hm, nan=-1.0)
    up = cv2.morphologyEx((h > PROTRUDE).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    lab, n = ndimage.label(up, np.ones((3, 3)))
    blobs = []
    for k in range(1, n + 1):
        mask = lab == k
        if mask.sum() * cell ** 2 < MIN_BLOB:
            continue
        b = dict(mask=mask, **region(mask, hm, cell))
        counts, edges = np.histogram(hm[mask & np.isfinite(hm)], bins=np.arange(0, 0.04, 0.0005))
        b["plateau"] = float(edges[np.argmax(counts)] + 0.00025)
        sub_lab, m = ndimage.label(mask & (h > b["plateau"] + SUB_STEP), np.ones((3, 3)))
        if m:
            biggest = sub_lab == np.argmax(np.bincount(sub_lab.ravel())[1:]) + 1
            if biggest.sum() * cell ** 2 > 5e-6:
                b["sub"] = dict(mask=biggest, **region(biggest, hm, cell))
        b["bgr"] = img[mask].mean(0)
        blobs.append(b)
    return blobs, find_door(hm, cell), sigma


def find_door(hm, cell, inset=0.007):
    """The door: a thin recess loop (its seam) well inside the panel's edge. The loop can have gaps
    where no camera saw down into the seam, so it is taken as the oriented box around the biggest
    recess and accepted when the recess runs along most of the box's outline. Returns dict(corners
    (4x2 row, col) of the flap inside the seam, seam width in cells, coverage) or None."""
    down = np.nan_to_num(hm, nan=0.0) < -RECESS
    k = int(inset / cell)
    down[:k], down[-k:], down[:, :k], down[:, -k:] = False, False, False, False  # the panel's own edge
    closed = cv2.morphologyEx(down.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    lab, n = ndimage.label(closed, np.ones((3, 3)))
    if n == 0:
        return None
    seam = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
    if seam.sum() * cell ** 2 < 100e-6:
        return None
    box = cv2.boxPoints(cv2.minAreaRect(np.argwhere(seam)[:, ::-1].astype(np.float32)))[:, ::-1]
    c, e1, e2 = box.mean(0), (box[1] - box[0]) / 2, (box[2] - box[1]) / 2
    half = np.array([np.linalg.norm(e1), np.linalg.norm(e2)])
    width = seam.sum() / (4 * half.sum())  # seam area over the box's perimeter
    e1, e2 = e1 / half[0], e2 / half[1]
    # how much of the seam's centre line, half a width inside the box, is recess
    t = np.linspace(-1, 1, 50)[:, None]
    lines = [c + s * (half[0] - width / 2) * e1 + t * (half[1] - width / 2) * e2 for s in (-1, 1)]
    lines += [c + s * (half[1] - width / 2) * e2 + t * (half[0] - width / 2) * e1 for s in (-1, 1)]
    near = cv2.dilate(down.astype(np.uint8), np.ones((5, 5), np.uint8))
    p = np.round(np.vstack(lines)).astype(int).clip(0, np.array(hm.shape) - 1)
    coverage = near[p[:, 0], p[:, 1]].mean()
    if coverage < 0.7 or min(half) * 2 * cell < 0.02:
        return None
    flap = [c + a * (half[0] - width) * e1 + b * (half[1] - width) * e2
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return dict(corners=np.array(flap), width=width, coverage=coverage)


# --- classification ---

# Size rules per kind, in metres. Each feature must fall in its range; a feature a little outside
# lowers the score instead of failing outright (see _soft). "sub" features describe the blob's
# upper part; kinds without one require it to be absent (sub_area near 0).
RULES = {
    "button": dict(diam=(0.009, 0.022), circ=(0.85, 1.2), h_max=(0.0018, 0.006), sub_area=(0, 0)),
    "knob": dict(diam=(0.018, 0.036), circ=(0.85, 1.2), h_max=(0.007, 0.018), sub_area=(0, 0)),
    "dial": dict(diam=(0.020, 0.038), circ=(0.8, 1.2), plateau=(0.006, 0.013), sub_len=(0.015, 0.032),
                 sub_width=(0.003, 0.008), sub_off=(0, 0.004)),
    "slider": dict(length=(0.04, 0.11), width=(0.012, 0.024), plateau=(0.0008, 0.0025), sub_len=(0.008, 0.02),
                   sub_h=(0.005, 0.014)),
    "toggle": dict(area=(100e-6, 400e-6), h_max=(0.012, 0.028), plateau=(0.0025, 0.006), sub_len=(0.006, 0.014),
                   sub_width=(0.003, 0.007), sub_off=(0.002, 0.008)),
    "display": dict(length=(0.04, 0.1), width=(0.015, 0.04), h_max=(0.0008, 0.0025), fill=(0.85, 1.2),
                    green=(10, 255), sub_area=(0, 0)),
    "pad": dict(diam=(0.010, 0.026), circ=(0.8, 1.2), h_max=(0.0005, 0.002), sub_area=(0, 0)),
}


def _soft(x, lo, hi):
    """1 inside [lo, hi], falling to 0 a quarter of the range (or 2 mm^2 for empty ranges) outside."""
    pad = 0.25 * (hi - lo) or 2e-6
    return float(np.clip(1 + min(x - lo, hi - x) / pad, 0, 1))


def blob_features(b, cell):
    s = b.get("sub")
    return dict(diam=2 * math.sqrt(b["area"] / math.pi), circ=b["circ"], h_max=b["h_max"], plateau=b["plateau"],
                length=b["length"], width=b["width"], fill=b["fill"], area=b["area"],
                green=float(b["bgr"][1] - max(b["bgr"][0], b["bgr"][2])), sub_area=s["area"] if s else 0.0,
                sub_len=s["length"] if s else 0.0, sub_width=s["width"] if s else 0.0, sub_h=s["h_max"] if s else 0.0,
                sub_off=float(np.linalg.norm(s["centre"] - b["centre"]) * cell) if s else 0.0)


def classify_blob(b, cell):
    """(kind or "unknown", score, why) from the size rules."""
    f = blob_features(b, cell)
    scores = {k: math.prod(_soft(f[name], *r) for name, r in rule.items()) for k, rule in RULES.items()}
    kind = max(scores, key=scores.get)
    if scores[kind] < 0.5:
        worst = min(RULES[kind], key=lambda name: _soft(f[name], *RULES[kind][name]))
        return "unknown", scores[kind], f"closest is {kind} ({scores[kind]:.2f}), but {worst} = {f[worst]:.4g}"
    mm = {k: v * 1000 for k, v in f.items()}
    why = {"dial": f"round, {mm['diam']:.0f} mm across, {mm['plateau']:.0f} mm tall, a {mm['sub_len']:.0f} mm fin",
           "slider": f"{mm['length']:.0f} x {mm['width']:.0f} mm track, a knob {mm['sub_h']:.1f} mm tall in it",
           "toggle": f"a {mm['plateau']:.0f} mm tall base with a lever leaning up to {mm['h_max']:.0f} mm",
           "display": f"flat {mm['length']:.0f} x {mm['width']:.0f} mm, {mm['h_max']:.1f} mm proud, green screen"}
    return kind, scores[kind], why.get(kind, f"round, {mm['diam']:.0f} mm across, {mm['h_max']:.1f} mm tall")


class Grid:
    """Height-map cells to the arm frame."""

    def __init__(self, T, cell, origin):
        self.T, self.cell, self.o = T, cell, origin
        self.n = T[:3, 2]

    def point(self, rc, h=0.0):
        rc = np.asarray(rc, float)
        a, b = self.o[0] + rc[..., :1] * self.cell, self.o[1] + rc[..., 1:2] * self.cell
        return self.T[:3, 3] + a * self.T[:3, 0] + b * self.T[:3, 1] + np.asarray(h, float)[..., None] * self.n

    def vec(self, d_rc):
        v = d_rc[0] * self.T[:3, 0] + d_rc[1] * self.T[:3, 1]
        return v / np.linalg.norm(v)

    def cells(self, mask, hm):
        rc = np.argwhere(mask & np.isfinite(hm))
        return self.point(rc, hm[rc[:, 0], rc[:, 1]])


def _extent(rc, centre, axis):
    """Min and max of points (row, col) along a unit axis through centre, in cells."""
    s = (rc - centre) @ axis
    return s.min(), s.max()


def classify(blobs, door, hm, img, grid):
    """Kind per blob, then a features.Part per recognised blob. Returns (parts, blob records)."""
    for b in blobs:
        b["kind"], b["score"], b["why"] = classify_blob(b, grid.cell)
    pad = None
    if door is not None:
        poly = door["corners"][:, ::-1].astype(np.float32)
        inside = [b for b in blobs if b["kind"] == "pad"
                  and cv2.pointPolygonTest(poly, tuple(float(v) for v in b["centre"][::-1]), False) > 0]
        pad = max(inside, key=lambda b: b["area"], default=None)
    for b in blobs:
        if b["kind"] == "pad" and b is not pad:
            b["kind"], b["why"] = "unknown", "low round blob, but not inside a door seam"
    if pad is not None:
        pad.update(kind="door", why=f"seam loop ({door['coverage']:.0%} seen) around a "
                                    f"{2 * math.sqrt(pad['area'] / math.pi) * 1000:.0f} mm push pad")
    known = sorted((b for b in blobs if b["kind"] != "unknown"),
                   key=lambda b: (features.KINDS.index(b["kind"]), b["centre"][1], b["centre"][0]))
    build = dict(button=_button, slider=_slider, dial=_dial, knob=_knob, toggle=_toggle, display=_display,
                 door=lambda b, hm, img, g: _door(b, door, hm, g))
    parts, count = [], {}
    for b in known:
        count[b["kind"]] = count.get(b["kind"], 0) + 1
        p = build[b["kind"]](b, hm, img, grid)
        p.id, p.score, p.points = f"{b['kind']}_{count[b['kind']]}", b["score"], grid.cells(b["mask"], hm)
        b["part"] = p.id
        parts.append(p)
    records = []
    for b in blobs:
        outline = door["corners"] if b["kind"] == "door" else b["outline"]
        records.append(dict(kind=b["kind"], score=round(b["score"], 3), part=b.get("part"), why=b["why"],
                            outline=grid.point(outline, np.full(len(outline), 0.0003))))
    if door is not None and pad is None:
        records.append(dict(kind="unknown", score=0.0, part=None, why="door seam with no push pad inside it",
                            outline=grid.point(door["corners"], np.zeros(4))))
    return parts, records


def _filled(mask):
    return ndimage.binary_fill_holes(mask)


def _circle(disc, hm, r=None):
    """Centre (row, col) and radius (cells) of a round region, fitted to its outline. Stretches of
    outline next to unseen cells are left out: an occlusion there would pull a centroid aside.
    With r (cells) known, only the centre is fitted, which a short arc of outline still fixes."""
    edge = disc & ~cv2.erode(disc.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    unseen = cv2.dilate(np.isnan(hm).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    rc = np.argwhere(edge & ~unseen).astype(float)
    if len(rc) < 10 or (r is None and len(rc) < 0.3 * edge.sum()):
        rc = np.argwhere(disc)
        return rc.mean(0), math.sqrt(len(rc) / math.pi) if r is None else r
    d, e, f = np.linalg.lstsq(np.c_[rc, np.ones(len(rc))], -(rc ** 2).sum(1), rcond=None)[0]
    c = -np.array([d, e]) / 2
    if r is None:
        return c, math.sqrt(max(c @ c - f, 0.0)) + 0.5  # edge cells sit half a cell inside the edge
    for _ in range(10):  # Gauss-Newton on the distance of each edge cell from the circle
        v = rc - c
        dist = np.linalg.norm(v, axis=1)
        c = c + np.linalg.lstsq(v / dist[:, None], dist - (r - 0.5), rcond=None)[0]
    return c, r


def _round_part(b, hm, g, level, r=None):
    """Centre (row, col), radius (m) and top height (m) of a round part cut at `level`; the top is
    the median height within 60% of the radius. r (m), if known, is kept."""
    disc = _filled(b["mask"] & (np.nan_to_num(hm, nan=-1.0) > level))
    c, r = _circle(disc, hm, None if r is None else r / g.cell)
    rc = np.argwhere(disc)
    inner = rc[np.linalg.norm(rc - c, axis=1) <= 0.6 * r]
    inner = inner if len(inner) else rc  # a fragment's fitted centre can land outside it; NaN would win min()
    return c, r * g.cell, float(np.nanmedian(hm[inner[:, 0], inner[:, 1]]))


def _button(b, hm, img, g, r=None):
    c, r, top = _round_part(b, hm, g, b["h_max"] / 2, r)
    o, n = g.point(c, top), g.n
    return features.Part("", "button", features.frame(o, n, features.canonical_x(g.T[:3, 1], n)),
                         np.array([2 * r, 2 * r, top]), "translation", -n, o, 0.0, (0.0, 0.0), meta=dict(radius=r))


def _mark_angle(g, centre, mask, img, axis=None):
    """Angle about the normal (rad, counter-clockwise from up the slope) of the brightly coloured
    pointer mark in mask, seen from the centre, or None. With axis (a unit vector) the mark only
    picks which way along that axis the pointer runs."""
    rc = np.argwhere(mask)
    col = img[rc[:, 0], rc[:, 1]].astype(float)
    dev = np.linalg.norm(col - np.median(col, axis=0), axis=1)
    hot = np.zeros(mask.shape, bool)
    hot[tuple(rc[dev > max(40.0, 3 * np.median(dev))].T)] = True
    lab, n = ndimage.label(hot, np.ones((3, 3)))
    if n == 0:
        return None
    mark = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1  # the mark, not stray glints on the rim
    if mark.sum() < 3:
        return None
    d = g.vec(np.argwhere(mark).mean(0) - centre)
    if axis is not None:
        d = axis if d @ axis > 0 else -axis
    up, left = -g.T[:3, 0], -g.T[:3, 1]
    return math.atan2(d @ left, d @ up)


def _scale(g, c, r, img, hm):
    """The printed scale around a dial or knob, read from the colour map in a ring just outside
    it: (angle of the stop turning clockwise, angle of the stop turning counter-clockwise, tick
    step), in rad counter-clockwise from up the slope, or None if no regular scale shows. The
    stops are the ticks either side of the widest gap."""
    th = np.radians(np.arange(0.0, 360.0))
    rad = np.arange(r + 0.0022 / g.cell, r + 0.0065 / g.cell, 0.5)
    rc = np.round(c + rad[None, :, None] * np.stack([-np.cos(th), -np.sin(th)], 1)[:, None, :]).astype(int)
    ok = np.all((rc >= 0) & (rc < hm.shape), axis=2)
    rc[~ok] = 0
    ok &= np.isfinite(hm[rc[..., 0], rc[..., 1]])
    if ok.mean() < 0.5:
        return None
    gray = img.mean(2)[rc[..., 0], rc[..., 1]]
    gray = np.where(ok, gray, np.median(gray[ok]))  # unseen samples carry no ink
    bg = ndimage.median_filter(gray, size=(21, 1), mode="wrap")  # the panel around each angle, shading and all
    ink = np.abs(gray / np.maximum(bg, 10) - 1).max(1)  # ticks are radial lines: the most contrast per angle
    w = np.exp(-0.5 * (np.arange(-4, 5) / 1.5) ** 2)  # smooth over ~2 deg: neighbouring angles share cells
    ink = sum(k * np.roll(ink, i) for i, k in zip(range(-4, 5), w)) / w.sum()
    near = np.max([np.roll(ink, k) for k in range(-6, 7)], axis=0)
    ticks = np.flatnonzero((ink >= max(0.25, 0.3 * ink.max())) & (ink == near))
    if len(ticks) < 5:
        return None
    gaps = np.diff(np.r_[ticks, ticks[0] + 360])
    step = float(np.mean(gaps[np.abs(gaps - np.median(gaps)) < 0.25 * np.median(gaps)]))  # a 1 deg error adds up
    off = (ticks - ticks[np.argmax(ink[ticks])] + step / 2) % step - step / 2
    ticks = ticks[np.abs(off) < 0.25 * step]  # stray marks off the regular spacing aren't ticks
    if len(ticks) < 5:
        return None
    gaps = np.diff(np.r_[ticks, ticks[0] + 360])
    n = np.round(gaps / step)
    if np.any(np.abs(gaps - n * step) > 0.3 * step):
        return None
    # A gap over a sector no camera saw may only hide ticks, so the stops bound the widest gap the
    # ring saw in full, and only if no other seen gap is as wide.
    seen = ok.mean(1) > 0.5
    full = [i for i in range(len(gaps)) if n[i] >= 2 and seen[(ticks[i] + np.arange(3, gaps[i] - 2)) % 360].all()]
    if not full or sum(n[i] == max(n[full]) for i in full) > 1:
        return None
    widest = max(full, key=lambda i: gaps[i])
    return math.radians(ticks[(widest + 1) % len(ticks)]), math.radians(ticks[widest]), math.radians(step)


def _turn_limits(meta, g, c, r, img, hm):
    """range (rad, to the stops) and the detent count from the printed scale, if it shows and the
    pointer was found. Detent 1 is at the counter-clockwise stop, as on the device's own readout."""
    scale = _scale(g, c, r, img, hm)
    if scale is None or "angle" not in meta:
        return (0.0, 0.0)
    lo, hi, step = scale
    span = (hi - lo) % (2 * math.pi)  # the scale, counter-clockwise from the clockwise stop
    s = (meta["angle"] - lo) % (2 * math.pi)  # the pointer's way along it
    if s > span:  # a hair past a stop: put it on the nearer one
        s = span if s - span < 2 * math.pi - s else 0.0
    meta.update(detent=1 + round((span - s) / step), detent_step=step)
    return -s, span - s


def _dial(b, hm, img, g, r=None):
    s = b["sub"]
    fin = cv2.dilate(s["mask"].astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    disc = _filled(b["mask"] & (np.nan_to_num(hm, nan=-1.0) > b["plateau"] / 2))
    c, r = _circle(disc, hm, None if r is None else r / g.cell)
    r *= g.cell
    knob_top = float(np.nanmedian(hm[disc & ~fin]))
    fin_top = float(np.nanmedian(hm[s["mask"]]))
    axis = g.vec(s["axis"])
    angle = _mark_angle(g, c, s["mask"], img, axis)
    o, n = g.point(c, knob_top), g.n
    meta = dict(knob_radius=r, knob_height=knob_top, fin_length=s["length"], fin_width=s["width"],
                fin_height=fin_top - knob_top)
    if angle is not None:
        meta["angle"] = angle
    limits = _turn_limits(meta, g, c, r / g.cell, img, hm)
    return features.Part("", "dial", features.frame(o, n, features.canonical_x(axis, n)),
                         np.array([2 * r, 2 * r, fin_top]), "rotation", n, o, 0.0, limits, meta=meta)


def _knob(b, hm, img, g, r=None):
    c, r, top = _round_part(b, hm, g, b["plateau"] / 2, r)
    o, n = g.point(c, top), g.n
    meta = dict(knob_radius=r, knob_height=top)
    angle = _mark_angle(g, c, _filled(b["mask"] & (np.nan_to_num(hm, nan=-1.0) > top - 0.001)), img)
    if angle is not None:
        meta["angle"] = angle
    limits = _turn_limits(meta, g, c, r / g.cell, img, hm)
    return features.Part("", "knob", features.frame(o, n, features.canonical_x(g.T[:3, 1], n)),
                         np.array([2 * r, 2 * r, top]), "rotation", n, o, 0.0, limits, meta=meta)


def _slider(b, hm, img, g, ax=None):
    """With ax (row, col), the slot's direction as the scan measured it, the knob is centred across the
    slot on the track: from a skill's approach pose the probe can hide most of the knob's width while
    the rails still show, and a partly hidden track tilts its own long axis."""
    h = np.nan_to_num(hm, nan=-1.0)
    rc_track = np.argwhere(b["mask"]).astype(float)
    tc, known = rc_track.mean(0), ax is not None
    ax = ax if known else b["axis"]
    across = np.array([-ax[1], ax[0]])
    t0, t1 = _extent(rc_track, tc, ax)
    rail = b["plateau"]
    knob_top = float(np.nanmedian(hm[b["sub"]["mask"]]))
    rc_knob = np.argwhere(b["mask"] & (h > (rail + knob_top) / 2)).astype(float)
    k0, k1 = _extent(rc_knob, tc, ax)
    w0, w1 = _extent(rc_knob, tc, across)
    m0, m1 = _extent(rc_track, tc, across) if known else (w0, w1)  # the knob rides centred in the track
    # the open channel: the low stretch of the track's centre line, between its end caps
    s = np.arange(t0, t1 + 0.5, 0.5)
    line = np.round(tc + np.outer(s, ax)).astype(int).clip(0, np.array(hm.shape) - 1)
    high = h[line[:, 0], line[:, 1]] >= rail / 2
    first, last = np.argmax(high), len(s) - 1 - np.argmax(high[::-1])  # the end caps' outer edges
    low = s[first:last + 1][~high[first:last + 1]]
    c0, c1 = (min(k0, low.min()), max(k1, low.max())) if len(low) else (k0, k1)
    knob_len = (k1 - k0 + 1) * g.cell
    travel = max((c1 - c0 + 1) * g.cell - knob_len, 0.0)
    x = features.canonical_x(g.vec(ax), g.n)
    sign = 1.0 if x @ g.vec(ax) > 0 else -1.0
    start = (c0 if sign > 0 else -c1) * g.cell + knob_len / 2  # knob centre at the -x stop, along x
    f = float(np.clip((sign * (k0 + k1) / 2 * g.cell - start) / travel, 0, 1)) if travel > 0 else 0.0
    o = g.point(tc + (k0 + k1) / 2 * ax + (m0 + m1) / 2 * across, knob_top)
    meta = dict(slot_ends=np.array([o - f * travel * x, o + (1 - f) * travel * x]), travel=travel, knob_len=knob_len,
                knob_width=(w1 - w0 + 1) * g.cell, side_height=(rail + knob_top) / 2, track_len=(t1 - t0 + 1) * g.cell)
    return features.Part("", "slider", features.frame(o, g.n, x), np.array([knob_len, meta["knob_width"], knob_top]),
                         "translation", x, o, f, (-f * travel, (1 - f) * travel), meta=meta)


def _toggle(b, hm, img, g):
    h = np.nan_to_num(hm, nan=-1.0)
    # the base's long side is the lever's axis: first from its outline, as the nut and lever cover much of its top,
    # then from its top once the lever's overhang is cut off (below)
    def long_axis(rc):
        box = cv2.boxPoints(cv2.minAreaRect(rc[:, ::-1].astype(np.float32)))[:, ::-1]
        e1, e2 = box[1] - box[0], box[2] - box[1]
        ax = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
        return ax / np.linalg.norm(ax)
    ax = long_axis(np.argwhere(_filled(b["mask"] & (h > b["plateau"] / 2))))
    base = b["mask"] & (h > b["plateau"] / 2) & (h < b["plateau"] + 0.001)  # its top, clear of nut and lever
    rc = np.argwhere(base).astype(float)
    c0 = rc.mean(0)
    s = b["sub"]
    lever_r = s["width"] / 2
    tip_rc = np.argwhere(s["mask"] & (h > s["h_max"] - 0.001)).mean(0)
    # the panel under the leaning lever can read at the base's height, stretching its outline that way (6 mm on
    # 1656, which put the hinge under the tip, and 19 deg off the axis on 1664): keep the base no further out than
    # the lever's far side, and take the axis again from what is left
    d = ax * (1.0 if (tip_rc - c0) @ ax > 0 else -1.0)
    rc = rc[(rc - c0) @ d <= (tip_rc - c0) @ d + lever_r / g.cell]
    ax = long_axis(rc)
    across = np.array([-ax[1], ax[0]])
    a0, a1 = _extent(rc, c0, ax)
    w0, w1 = _extent(rc, c0, across)
    c = c0 + (a0 + a1) / 2 * ax + (w0 + w1) / 2 * across  # middle of the base's outline: the hinge
    base_top = float(np.median(hm[base]))
    lean = 1.0 if (tip_rc - c) @ ax > 0 else -1.0
    x = g.vec(lean * ax)
    hinge = g.point(c, base_top)
    tip = g.point(c + ((tip_rc - c) @ ax) * ax, s["h_max"] - lever_r)
    tilt = math.atan2((tip - hinge) @ x, (tip - hinge) @ g.n)
    on = bool(x @ (g.T[:3, 1] - g.T[:3, 0]) > 0)  # leaning up the slope or to the arm's right reads as ON
    meta = dict(lever_len=float(np.linalg.norm(tip - hinge)) + lever_r, lever_radius=lever_r, tip=tip,
                base_size=np.array([(a1 - a0 + 1) * g.cell, (w1 - w0 + 1) * g.cell, base_top]),
                angle=tilt if on else -tilt, on=on)
    return features.Part("", "toggle", features.frame(hinge, g.n, x),
                         np.array([meta["base_size"][0], meta["base_size"][1], s["h_max"]]), "rotation",
                         np.cross(x, g.n), hinge, 1.0, (0.0, 2 * tilt), meta=meta)


def _display(b, hm, img, g):
    col = img.astype(int)
    screen = b["mask"] & (col[..., 1] - np.maximum(col[..., 0], col[..., 2]) > 15)  # the lit LCD
    screen = screen if screen.sum() > 0.3 * b["mask"].sum() else b["mask"]
    st = region(screen, hm, g.cell)
    rc = np.argwhere(screen).astype(float)
    across = np.array([-st["axis"][1], st["axis"][0]])
    a0, a1 = _extent(rc, st["centre"], st["axis"])
    w0, w1 = _extent(rc, st["centre"], across)
    c = st["centre"] + (a0 + a1) / 2 * st["axis"] + (w0 + w1) / 2 * across
    top = float(np.nanmedian(hm[screen]))
    o, n = g.point(c, top), g.n
    size = ((a1 - a0 + 1) * g.cell, (w1 - w0 + 1) * g.cell)
    return features.Part("", "display", features.frame(o, n, features.canonical_x(g.vec(st["axis"]), n)),
                         np.array([*size, top]), meta=dict(screen=size))


def _door(pad, door, hm, g):
    corners = door["corners"]  # the flap inside the seam, (row, col), going around
    fc = corners.mean(0)
    e1, e2 = (corners[1] - corners[0]) / 2, (corners[3] - corners[0]) / 2
    if np.linalg.norm(e1) < np.linalg.norm(e2):
        e1, e2 = e2, e1  # e1 along the long edges, one of which is the hinge
    pc, pr, ptop = _round_part(pad, hm, g, pad["h_max"] / 2)
    side = 1.0 if (pc - fc) @ e2 > 0 else -1.0  # the pad sits near the free edge, away from the hinge
    x = g.vec(side * e2)
    y = np.cross(g.n, x)
    half_x, half_y = np.linalg.norm(e2) * g.cell, np.linalg.norm(e1) * g.cell
    flap = np.zeros(hm.shape, np.uint8)
    cv2.fillPoly(flap, [np.round(corners[:, ::-1]).astype(np.int32)], 1)
    flap = flap.astype(bool) & ~cv2.dilate(pad["mask"].astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    flap &= np.isfinite(hm)
    centre = g.point(fc, float(np.median(hm[flap])))
    # opening angle: the flap's slope from the hinge toward the free edge (0 when shut)
    rc = np.argwhere(flap).astype(float)
    s = (rc - fc) @ (side * e2 / np.linalg.norm(e2)) * g.cell
    state = float(math.atan(np.polyfit(s, hm[flap], 1)[0])) if len(s) > 10 else 0.0
    hinge_mid = centre - half_x * x
    o = g.point(pc, ptop)
    corners = [centre + a * half_x * x + b * half_y * y for a, b in ((-1, 1), (-1, -1), (1, -1), (1, 1))]  # hinge first
    meta = dict(corners=np.array(corners), hinge=np.array([hinge_mid + half_y * y, hinge_mid - half_y * y]),
                pad_radius=pr, latched=bool(state < 0.05))
    return features.Part("", "door", features.frame(o, g.n, x), np.array([2 * half_x, 2 * half_y, ptop]), "rotation",
                         y, hinge_mid, state, (0.0, 0.0), meta=meta)


# --- refine ---

def refine(arm, wrist, part):
    """The part re-measured from one wrist frame taken where the arm is now, at a skill's approach
    pose. Camera and probe share the gripper, so a part measured from here sits right relative to
    the fingertip in this same arm configuration, and joint calibration errors mostly cancel. The
    probe itself shows in the frame, so the frame is first shifted to put it where forward
    kinematics does, which takes out the camera mount's calibration error too.

    Runs the full pipeline's rules on a window around the believed part (plane fit, height map,
    blobs, the size rules its outline doesn't set, the per-kind builder; a door is found by its
    push pad), takes the nearest blob of the same kind and moves the part onto it: its origin and
    the panel normal change, its sizes, state and the rest stay as perceived. meta gets refined,
    refine_shift (m, how far the part moved), refine_probe (m, the mount correction) and, if no
    such blob is near, refine_why, with the part otherwise unchanged. Never moves the arm."""
    def fail(why):
        return replace(part, meta={**part.meta, "refined": False, "refine_shift": 0.0, "refine_why": why})

    want, centre, reach = part.kind, part.pos, max(part.size[0], part.size[1])
    if part.kind == "slider":
        centre, reach = np.mean(part.meta["slot_ends"], axis=0), part.meta["track_len"]
    elif part.kind == "door":
        want, reach = "pad", 2 * part.meta["pad_radius"]
    half = reach / 2 + REFINE_SHIFT + REFINE_PANEL
    f = wrist.capture()
    pts, rgb, px = rig.backproject(f)
    z = f.depth[px[:, 1], px[:, 0]]
    probe = _probe_shift(arm, pts[z < PROBE_CROP])
    if probe is not None:  # place what the frame sees relative to the probe, not to the camera mount
        pts += probe
    nrm = rig.normals(f)[px[:, 1], px[:, 0]]
    lift = part.size[2]  # the origin's height above the panel: most parts' origin is on their top
    if part.kind == "dial":
        lift = part.meta["knob_height"]
    elif part.kind == "toggle":
        lift = part.meta["base_size"][2]
    T0 = features.frame(centre - lift * part.normal, part.normal, part.x)  # the panel under the part
    a, b, h = ((pts - T0[:3, 3]) @ T0[:3, :3]).T
    keep = ((z > PROBE_CROP) & (np.abs(a) < half) & (np.abs(b) < half) & (h > -0.01) & (h < 0.05)
            & np.any(nrm != 0, axis=1))
    if keep.sum() < MIN_POINTS:
        return fail(f"only {keep.sum()} points around {part.id} in the frame")
    pts, rgb, _, _ = fuse([(pts[keep], rgb[keep], nrm[keep])])
    n, p, _ = ransac_plane(pts, FINE_THR, normal=part.normal, max_deg=15)
    T = plane_frame(n, p)
    T[:3, 3] = centre - ((centre - p) @ n) * n  # the map is centred on the believed part
    hm, img, cell, origin = height_map(pts, rgb, T, (-half, half, -half, half))
    g = Grid(T, cell, origin)
    blobs, _, _ = segment(hm, img, cell)
    # The probe hides part of the outline from here, so what the scan measured best stays. Round parts keep
    # their radius (a circle fitted to a short arc came out small and off-centre, 1.3 mm on a dial), and a
    # slider keeps its slot direction and is centred across it on the track (5 mm off on a knob's sliver).
    r = part.meta.get({"button": "radius", "door": "pad_radius"}.get(part.kind, "knob_radius"))
    slot = np.array([part.x @ T[:3, 0], part.x @ T[:3, 1]])  # (row, col) in this map
    build = dict(button=partial(_button, r=r), dial=partial(_dial, r=r), knob=partial(_knob, r=r),
                 slider=partial(_slider, ax=slot / np.linalg.norm(slot)), toggle=_toggle, display=_display)
    found, seen_x = [], {}
    for blob in blobs:
        feat = blob_features(blob, cell)
        if math.prod(_soft(feat[k], *rule) for k, rule in RULES[want].items() if k not in OUTLINE) < 0.5:
            continue
        if want == "pad":
            c, _, top = _round_part(blob, hm, g, blob["h_max"] / 2, r)
            found.append(g.point(c, top))
        else:
            q = build[want](blob, hm, img, g)
            found.append(q.pos)
            seen_x[len(found) - 1] = q.x
    if not found:  # from a sideways push's hover pose the probe can stand right in front of the part
        rr, cc = np.mgrid[:hm.shape[0], :hm.shape[1]]
        near = np.hypot(rr + origin[0] / cell, cc + origin[1] / cell) < reach / 2 / cell
        return fail(f"no {want} near {part.id}, and {np.isnan(hm[near]).mean():.0%} of the panel within "
                    f"{reach * 500:.0f} mm of it is unseen from this pose")
    k = min(range(len(found)), key=lambda j: np.linalg.norm(found[j] - part.pos))
    pos = found[k]
    shift = float(np.linalg.norm(pos - part.pos))
    if shift > REFINE_SHIFT:
        return fail(f"the nearest {want} is {shift * 1000:.1f} mm from where {part.id} should be")
    # Along a slot, one frame can't tell calibration error from a knob that sits a little off where the part
    # says. Calibration error is the larger risk (up to 3.7 mm along the slot in tests, against 0.8 mm for the
    # knob), so the slot moves with the knob and the state stays.
    Tp = features.frame(pos, n, part.x)
    D = Tp @ np.linalg.inv(part.T)

    def move(X):
        return None if X is None else np.asarray(X) @ D[:3, :3].T + D[:3, 3]

    meta = {k: move(v) if k in ("slot_ends", "tip", "corners", "hinge") else v for k, v in part.meta.items()}
    meta.update(refined=True, refine_shift=shift, refine_probe=None if probe is None else float(np.linalg.norm(probe)))
    if part.kind == "dial" and k in seen_x:  # the fin's line as this frame sees it (either way along it): a turn checks
        meta["seen_x"] = seen_x[k]          # how far the dial really went by it, not by the device's reading
    meta.pop("refine_why", None)
    return replace(part, T=Tp, axis=None if part.axis is None else D[:3, :3] @ part.axis, origin=move(part.origin),
                   points=move(part.points), meta=meta)


def _probe_model(arm):
    """Surface points and unit normals of the probe's pad and lower rod, where forward kinematics of
    the joint readings puts them (arm frame): the part of the probe the wrist camera sees."""
    m, fk = arm.m, mujoco.MjData(arm.m)
    fk.qpos[arm.qadr] = arm.read_q()
    mujoco.mj_kinematics(m, fk)
    th = np.radians(np.arange(0, 360, 5))
    ring = np.c_[np.cos(th), np.sin(th), np.zeros(len(th))]
    rod, pad = m.geom("probe_rod").id, m.geom("probe_pad").id
    (r_rod, h_rod), (r_pad, h_pad) = m.geom_size[rod][:2], m.geom_size[pad][:2]
    R, c = fk.geom_xmat[pad].reshape(3, 3), fk.geom_xpos[pad]
    back = np.sign((fk.geom_xpos[rod] - c) @ R[:, 2])  # the pad's face toward the rod and the camera
    P, N = [], []
    for z in np.linspace(-h_pad, h_pad, 4):  # pad rim
        P.append(c + (r_pad * ring + [0, 0, z]) @ R.T)
        N.append(ring @ R.T)
    for rho in np.arange(r_rod, r_pad, 0.0005):  # pad back face, around the rod
        P.append(c + (rho * ring + [0, 0, back * h_pad]) @ R.T)
        N.append(np.tile(back * R[:, 2], (len(th), 1)))
    R, c = fk.geom_xmat[rod].reshape(3, 3), fk.geom_xpos[rod]
    for z in np.arange(-h_rod, h_rod, 0.001):  # rod side
        P.append(c + (r_rod * ring + [0, 0, z]) @ R.T)
        N.append(ring @ R.T)
    P, N = np.vstack(P), np.vstack(N)
    near = np.linalg.norm(P - fk.geom_xpos[pad], axis=1) < 0.016  # not the rod's top, where the jaw is
    return P[near], N[near]


def _probe_shift(arm, pts):
    """The translation that moves the probe as a wrist frame sees it (pts: the frame's points nearer
    than PROBE_CROP) onto where forward kinematics puts it: the wrist camera's calibration error at
    the probe, by point-to-plane fitting. None if too little of the probe shows, or the arm has none."""
    if mujoco.mj_name2id(arm.m, mujoco.mjtObj.mjOBJ_GEOM, "probe_pad") < 0:
        return None
    M, Mn = _probe_model(arm)
    tree, t = cKDTree(M), np.zeros(3)
    for _ in range(10):
        d, j = tree.query(pts + t, distance_upper_bound=0.003)
        ok = np.isfinite(d)
        if ok.sum() < 500:
            return None
        n = Mn[j[ok]]
        t -= np.linalg.lstsq(n, np.einsum("ij,ij->i", pts[ok] + t - M[j[ok]], n), rcond=None)[0]
    return t


# --- evaluation (sim truth; perceive() never calls this) ---

def _deg(a, b, sign=True):
    c = float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))
    return math.degrees(math.acos(c if sign else abs(c)))


def evaluate(parts, truth):
    """Perceived parts against sim truth, paired with features.match. Per pair: lateral and
    along-normal position error (m), motion-axis and x-axis angle errors (deg), state error.
    Summary: per-kind recall and precision (a pair counts when the kinds agree), classification
    accuracy over matched pairs, and the median and max of each error."""
    pairs, missed, extra = features.match(parts, truth)
    rows = []
    for t, p in pairs:
        d = p.pos - t.pos
        row = dict(truth=t.id, part=p.id, kind=t.kind, got=p.kind, normal=float(d @ t.normal),
                   lateral=float(np.linalg.norm(d - (d @ t.normal) * t.normal)), normal_deg=_deg(p.normal, t.normal))
        if p.kind == t.kind:
            if t.axis is not None and p.axis is not None:
                row["axis_deg"] = _deg(p.axis, t.axis)
            row["x_deg"] = _deg(p.x, t.x, sign=t.kind not in ("button", "display", "knob"))
            if t.kind in ("slider", "door", "button"):
                row["state_err"] = abs(p.state - t.state)
            elif t.kind == "toggle":
                row["state_err"] = float(p.meta["on"] != t.meta["on"])
            elif "angle" in p.meta:
                row["state_err"] = abs((p.meta["angle"] - t.meta["angle"] + math.pi) % (2 * math.pi) - math.pi)
            if tuple(p.range) != (0.0, 0.0) and t.kind in ("slider", "dial", "knob", "toggle"):
                row["range_err"] = float(np.max(np.abs(np.subtract(p.range, t.range))))
            if "detent" in p.meta:
                row["detent_ok"] = p.meta["detent"] == t.meta["detent"]
        rows.append(row)
    per_kind = {}
    for k in sorted({t.kind for t in truth} | {p.kind for p in parts}):
        n_t, n_p = sum(t.kind == k for t in truth), sum(p.kind == k for p in parts)
        hit = sum(r["kind"] == k and r["got"] == k for r in rows)
        per_kind[k] = dict(truth=n_t, found=n_p, correct=hit, recall=hit / n_t if n_t else None,
                           precision=hit / n_p if n_p else None)
    same = [r for r in rows if r["kind"] == r["got"]]

    def stat(key):
        v = [abs(r[key]) for r in same if key in r]
        return (float(np.median(v)), float(np.max(v))) if v else (None, None)

    return dict(rows=rows, missed=[t.id for t in missed], extra=[p.id for p in extra], per_kind=per_kind,
                accuracy=len(same) / len(rows) if rows else None, lateral=stat("lateral"), normal=stat("normal"),
                axis_deg=stat("axis_deg"), x_deg=stat("x_deg"))
