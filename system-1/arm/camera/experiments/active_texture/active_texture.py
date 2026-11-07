"""Does projected texture let the plane sweep see heights on plain dark plastic? Rendered, not photographed.

    python active_texture.py        # writes results.json and a few preview images next to this file

Scene: an 80 x 60 mm matte black panel (albedo 0.06, almost no texture) with four raised buttons, 1 and 2 mm tall,
seen by the real camera's calibrated focal length at 1920x1080 from 15-20 cm. Rendering is a small ray caster in numpy
(each camera ray is intersected with the height map by fixed-point iteration), not MuJoCo: MuJoCo's lights cannot
project an image, so the pattern is computed per surface point instead. Every frame gets shot noise, read noise,
8-bit quantising and JPEG at quality 85, then goes through height_test.sweep unchanged.

Lighting variants:
  plain      room light only
  fixed      random-dot pattern from a projector fixed over the panel (pattern stays put as the camera moves)
  wrist      the same projector mounted 4 cm beside the camera (pattern moves with the camera)
  laser      a laser line fixed to the wrist, triangulated frame by frame while the arm steps across (no sweep)
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import height_test as ht  # noqa: E402
ct = ht.ct

RNG = np.random.default_rng(0)
W_MM, H_MM = 80.0, 60.0
ct.SQ, ct.SQ_MM = (8, 6), 10.0          # sweep grid = the 80 x 60 mm panel (sweep reads these at call time)
K, _ = ct.load_calib(1920)
IW, IH = 1920, 1080
MAP_RES = 0.1                            # mm per cell of the scene's height / albedo maps
BUTTONS = [((20, 20), 6, 1.0), ((45, 20), 6, 2.0), ((20, 42), 8, 1.0), ((58, 40), 10, 2.0)]  # centre mm, half-size, height


def scene():
    ys, xs = np.mgrid[0:H_MM:MAP_RES, 0:W_MM:MAP_RES]
    h = np.zeros_like(xs)
    for (cx, cy), r, z in BUTTONS:
        if r == 6:
            h[np.hypot(xs - cx, ys - cy) < r] = z                       # round buttons
        else:
            h[(abs(xs - cx) < r) & (abs(ys - cy) < r * 0.6)] = z         # rectangular
    # barely-there texture: 2% low-frequency albedo variation, like moulded plastic
    noise = cv2.GaussianBlur(RNG.standard_normal(xs.shape).astype(np.float32), (0, 0), 30)
    alb = 0.06 * (1 + 0.02 * noise / noise.std())
    return h.astype(np.float32), alb.astype(np.float32)


HMAP, ALB = scene()


def look_at(C, T, up=(0, -1, 0)):
    """rvec, tvec (board -> camera) for a camera at C looking at T; board z points into the panel."""
    z = (T - C) / np.linalg.norm(T - C)
    x = np.cross(up, z); x /= np.linalg.norm(x)
    R = np.stack([x, np.cross(z, x), z])
    return R, -R @ C


def sample(img, X):
    """Bilinear look-up of a scene map at board points X (..., 2), metres."""
    mx = (X[..., 0] * 1000 / MAP_RES).astype(np.float32)
    my = (X[..., 1] * 1000 / MAP_RES).astype(np.float32)
    return cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def cast(R, t):
    """Surface point (board coords, metres) under every pixel, inside-panel mask."""
    u, v = np.meshgrid(np.arange(IW, dtype=np.float32), np.arange(IH, dtype=np.float32))
    d = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u)], -1) @ R.astype(np.float32)
    C = (-R.T @ t).astype(np.float32)
    h = np.zeros(u.shape, np.float32)
    for _ in range(6):                    # ray meets plane z = -h, read h there, repeat
        s = (-h / 1000 - C[2]) / d[..., 2]
        X = C + s[..., None] * d
        h = sample(HMAP, X[..., :2])
    inside = (X[..., 0] > 0) & (X[..., 0] < W_MM / 1000) & (X[..., 1] > 0) & (X[..., 1] < H_MM / 1000)
    return X, inside


# random-dot slide: 0.3 mm dots where it lands, 50% fill, slightly soft (projector focus)
PAT = cv2.GaussianBlur((RNG.random((500, 500)) > 0.5).astype(np.float32), (0, 0), 0.7)


def projector_light(X, Rp, tp, fp):
    """Pattern brightness (0-1) falling on board points X from a pinhole projector at pose Rp, tp."""
    Pc = X @ Rp.T + tp
    px = (fp * Pc[..., 0] / Pc[..., 2] + 250).astype(np.float32)
    py = (fp * Pc[..., 1] / Pc[..., 2] + 250).astype(np.float32)
    return cv2.remap(PAT, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


FIXED_PROJ = look_at(np.array([0.04, -0.06, -0.25]), np.array([0.04, 0.03, 0.0]))


def render(R, t, mode, laser=None):
    X, inside = cast(R, t)
    alb = sample(ALB, X[..., :2])
    alb = np.where(inside, alb, 0.25).astype(np.float32)   # grey table around the panel
    light = np.full(alb.shape, 1.0, np.float32)            # room light: black plastic reads ~15/255
    if mode == "fixed":
        light += 2.0 * projector_light(X, *FIXED_PROJ, fp=0.27 / 0.0003)
    elif mode == "wrist":
        C = -R.T @ t
        Rp, tp = R, -R @ (C + 0.04 * R[0])                  # projector 4 cm along the camera's x axis, same heading
        light += 2.0 * projector_light(X, Rp, tp, fp=0.18 / 0.0003)
    elif mode == "laser":
        n, d0 = laser                                       # laser plane n.X = d0 in board coords
        dist_mm = (X @ n - d0) * 1000
        light += 12.0 * np.exp(-0.5 * (dist_mm / 0.25) ** 2)   # ~0.6 mm wide line, bright enough to stand out on black
    img = np.clip(alb * light, 0, 1)
    # sensor: shot noise (~0.01 at mid grey), read noise, 8 bit, JPEG q85
    img = img + RNG.standard_normal(img.shape).astype(np.float32) * np.sqrt(0.0002 * img + 0.002 ** 2)
    img8 = np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)
    img8 = cv2.imdecode(cv2.imencode(".jpg", img8, [cv2.IMWRITE_JPEG_QUALITY, 85])[1], cv2.IMREAD_GRAYSCALE)
    return img8, X, inside


def views(n=20):
    out = []
    for _ in range(n):
        C = np.array([0.04 + RNG.uniform(-0.03, 0.03), 0.03 + RNG.uniform(-0.03, 0.03), -RNG.uniform(0.15, 0.20)])
        T = np.array([0.04 + RNG.uniform(-0.01, 0.01), 0.03 + RNG.uniform(-0.01, 0.01), 0.0])
        R, t = look_at(C, T)
        out.append((R, t))
    return out


TRUTH = cv2.resize(HMAP, (int(W_MM / ht.MM_PX), int(H_MM / ht.MM_PX)), interpolation=cv2.INTER_NEAREST)
edge = cv2.morphologyEx(TRUTH, cv2.MORPH_GRADIENT, np.ones((9, 9), np.uint8)) > 0   # within ~1 mm of a button edge
BORDER = np.zeros_like(edge); BORDER[8:-8, 8:-8] = True
ON_BTN = (TRUTH > 0) & ~edge & BORDER
ON_PANEL = (TRUTH == 0) & ~edge & BORDER


def score(height, trusted):
    row = {}
    for name, m in (("button", ON_BTN), ("panel", ON_PANEL)):
        e = (height - TRUTH)[m & trusted]
        row[name] = {"coverage_pct": round(100 * (m & trusted).sum() / m.sum(), 1),
                     "median_abs_err_mm": round(float(np.median(abs(e))), 3) if e.size else None,
                     "p90_abs_err_mm": round(float(np.percentile(abs(e), 90)), 3) if e.size else None}
    return row


def run_sweep(mode, poses):
    frames, ps = [], []
    for R, t in poses:
        img, _, _ = render(R, t, mode)
        frames.append(img.astype(np.float32) / 255)
        ps.append({"rvec": cv2.Rodrigues(R)[0].ravel().tolist(), "tvec": t.tolist()})
    cv2.imwrite(os.path.join(HERE, f"view_{mode}.jpg"), (frames[0] * 255).astype(np.uint8))
    height, conf = ht.sweep(frames, ps, K, np.zeros(5), heights=np.arange(-1.0, 4.01, 0.25))
    vis = np.clip(height / 2.5 * 255, 0, 255).astype(np.uint8)
    vis[conf <= 0.5] = 0
    cv2.imwrite(os.path.join(HERE, f"height_{mode}.png"), cv2.applyColorMap(vis, cv2.COLORMAP_VIRIDIS))
    return score(height, conf > 0.5)


def run_laser():
    """Wrist laser 5 cm beside the camera, its sheet tilted back to cross the optical axis at 17 cm. The arm steps the
    camera across the panel in 0.5 mm moves; each frame, the brightest pixel per column on the line gives a point."""
    grid_h = np.zeros(TRUTH.shape, np.float32); grid_n = np.zeros(TRUTH.shape, np.float32)
    ang = np.arctan2(0.05, 0.17)
    n_cam = np.array([0, np.cos(ang), np.sin(ang)])            # plane normal in camera coords, through y=0.05 at the lens
    d_cam = n_cam @ np.array([0, 0.05, 0.0])
    for y in np.arange(-0.025, 0.085, 0.0005):
        C = np.array([0.04, y, -0.17])
        R, t = look_at(C, C + np.array([0, 0, 0.17]))
        n_w = R.T @ n_cam; d_w = d_cam + n_w @ C                # same plane in board coords
        img, X, inside = render(R, t, "laser", laser=(n_w, d_w))
        f = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.0)
        rows = f.argmax(0)
        peak = f[rows, np.arange(IW)]
        ok = (peak > 60) & (rows > 0) & (rows < IH - 1)
        cols = np.arange(IW)[ok]; r = rows[ok]
        a, b, c = f[r - 1, cols], f[r, cols], f[r + 1, cols]
        curve = np.where(a - 2 * b + c < 0, a - 2 * b + c, -1)
        sub = r + np.clip(0.5 * (a - c) / curve, -0.5, 0.5)    # parabola through the peak and its neighbours
        ray = np.stack([(cols - K[0, 2]) / K[0, 0], (sub - K[1, 2]) / K[1, 1], np.ones_like(sub)], -1)
        s = d_cam / (ray @ n_cam)                               # ray meets laser plane, camera coords
        P = (ray * s[:, None] - t) @ R                          # back to board coords
        gx = (P[:, 0] * 1000 / ht.MM_PX).astype(int); gy = (P[:, 1] * 1000 / ht.MM_PX).astype(int)
        keep = (gx >= 0) & (gx < TRUTH.shape[1]) & (gy >= 0) & (gy < TRUTH.shape[0])
        np.add.at(grid_h, (gy[keep], gx[keep]), -P[keep, 2] * 1000)
        np.add.at(grid_n, (gy[keep], gx[keep]), 1)
        if abs(y - 0.03) < 1e-4:
            cv2.imwrite(os.path.join(HERE, "view_laser.jpg"), img)
    height = grid_h / np.maximum(grid_n, 1)
    # columns of the sweep spacing (0.5 mm) leave gaps on the 0.25 mm grid: fill from neighbours within 0.5 mm
    hs = cv2.blur(height * (grid_n > 0), (3, 3)); ns = cv2.blur((grid_n > 0).astype(np.float32), (3, 3))
    trusted = ns > 0
    height = np.where(grid_n > 0, height, hs / np.maximum(ns, 1e-6))
    vis = np.clip(height / 2.5 * 255, 0, 255).astype(np.uint8); vis[~trusted] = 0
    cv2.imwrite(os.path.join(HERE, "height_laser.png"), cv2.applyColorMap(vis, cv2.COLORMAP_VIRIDIS))
    return score(height, trusted)


if __name__ == "__main__":
    poses = views()
    results = {m: run_sweep(m, poses) for m in ("plain", "fixed", "wrist")}
    results["laser"] = run_laser()
    json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for m, r in results.items():
        print(m, r)
