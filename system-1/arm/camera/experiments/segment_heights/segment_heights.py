"""Segment-based height: pick one height (or one tilted plane) per SAM region by summing the sweep's matching cost over
the region, instead of taking each cell's own winner. Compared against scan_test.classify on the remote and on coins.

    cd system-1/arm/camera; PYTHONPATH=. python experiments/segment_heights/segment_heights.py remote|coins
"""
import json
import os
import sys

import cv2
import numpy as np
import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv += ["--dir", "scan_1080"]
import height_test as ht  # noqa: E402
import scan_test as st  # noqa: E402

ct = ht.ct
box, local_norm, DEV, MM_PX = ht.box, ht.local_norm, ht.DEV, ht.MM_PX


def sweep_volume(frames, poses, K, dist, heights):
    """height_test.sweep, but also returns the full cost volume (planes, rows, cols) and the texture map."""
    w_mm, h_mm = ct.SQ[0] * ct.SQ_MM, ct.SQ[1] * ct.SQ_MM
    size = (int(w_mm / MM_PX), int(h_mm / MM_PX))
    straight = [cv2.undistort(f, K, dist) for f in frames]
    ones = [cv2.undistort(np.ones_like(f), K, dist) for f in frames]
    S = np.diag([MM_PX / 1000, MM_PX / 1000, 1.0])
    raw = cv2.warpPerspective(straight[0], K @ np.c_[cv2.Rodrigues(np.array(poses[0]['rvec']))[0][:, :2],
                              np.array(poses[0]['tvec'])] @ S, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    m = cv2.blur(raw, (ht.WIN, ht.WIN))
    texture = np.sqrt(np.maximum(cv2.blur(raw * raw, (ht.WIN, ht.WIN)) - m * m, 0))
    src = torch.from_numpy(np.stack([np.stack([s, o]) for s, o in zip(straight, ones)])).to(DEV)
    ih, iw = frames[0].shape
    ys, xs = torch.meshgrid(torch.arange(size[1]), torch.arange(size[0]), indexing="ij")
    cells = torch.stack([xs, ys, torch.ones_like(xs)], -1).reshape(-1, 3).float().to(DEV)
    Rs = [cv2.Rodrigues(np.array(p["rvec"]))[0] for p in poses]
    ts = [np.array(p["tvec"]) for p in poses]
    costs = []
    for h in heights:
        Hs = np.stack([K @ np.c_[R[:, 0], R[:, 1], t - (h / 1000) * R[:, 2]] @ S for R, t in zip(Rs, ts)])
        uvw = cells @ torch.from_numpy(Hs).float().to(DEV).transpose(1, 2)
        uv = uvw[..., :2] / uvw[..., 2:]
        grid = torch.stack([uv[..., 0] / (iw - 1) * 2 - 1, uv[..., 1] / (ih - 1) * 2 - 1], -1)
        warped = F.grid_sample(src, grid.reshape(len(poses), size[1], size[0], 2), align_corners=True)
        stack, valid = local_norm(warped[:, :1]), (warped[:, 1:] > 0.99).float()
        n = valid.sum(0)
        mean = (stack * valid).sum(0) / n.clamp(min=1)
        var = ((stack - mean) ** 2 * valid).sum(0) / n.clamp(min=1)
        costs.append(torch.where(n[0] >= 4, box(var[None])[0, 0], torch.inf).cpu())
    del src
    torch.cuda.empty_cache()
    cost = torch.stack(costs)
    seen = torch.isfinite(cost)
    total, count = torch.where(seen, cost, 0).sum(0), seen.sum(0)
    best, k = cost.min(0)
    kk = k.clamp(1, len(heights) - 2)
    c0, c1, c2 = (cost.gather(0, (kk + d)[None])[0] for d in (-1, 0, 1))
    curve = c0 - 2 * c1 + c2
    off = torch.where(torch.isfinite(curve) & (curve > 0) & (k == kk), 0.5 * (c0 - c2) / curve, 0).clamp(-0.5, 0.5)
    height = torch.as_tensor(heights, dtype=torch.float32)[k] + off * float(heights[1] - heights[0])
    best, height, total, count = (x.numpy() for x in (best, height, total, count))
    conf = np.where(count > 0, 1 - best / np.maximum(total / np.maximum(count, 1), 1e-6), 0).astype(np.float32)
    conf[texture < ht.MIN_TEXTURE] = 0
    return height, conf, cost.numpy(), texture


# ---- per-region height choices ------------------------------------------------------------------------------------

def refine(curve, heights):
    k = int(np.argmin(curve))
    if 0 < k < len(curve) - 1:
        c0, c1, c2 = curve[k - 1:k + 2]
        d = c0 - 2 * c1 + c2
        if d > 0:
            return heights[k] + float(np.clip(0.5 * (c0 - c2) / d, -0.5, 0.5)) * (heights[1] - heights[0])
    return float(heights[k])


def columns(cost, mask):
    """The region's cost columns (planes x cells), only cells seen at every plane, and their (row, col)."""
    c = cost[:, mask]
    ok = np.isfinite(c).all(0)
    ys, xs = np.nonzero(mask)
    return c[:, ok], ys[ok], xs[ok], ok


def seg_height(cost, mask, heights, w=None):
    c, _, _, ok = columns(cost, mask)
    if c.shape[1] < 20:
        return np.nan
    w = np.ones(c.shape[1]) if w is None else w[mask][ok]
    return refine((c * w).sum(1) / w.sum(), heights)


def seg_plane(cost, mask, heights, w, at, tilts=np.arange(-0.15, 0.151, 0.05), span=4.0, step=0.1):
    """Best tilted plane z = h + a*dx + b*dy (dx, dy in mm from `at`) over the summed cost; its height at `at`."""
    c, ys, xs, ok = columns(cost, mask)
    if c.shape[1] < 20:
        return np.nan
    w = w[mask][ok]
    h0 = seg_height(cost, mask, heights, None if w is None else None)
    if not np.isfinite(h0):
        return np.nan
    dx, dy = (xs - at[1]) * MM_PX, (ys - at[0]) * MM_PX
    hs = np.arange(h0 - span, h0 + span + 1e-6, step)
    dh = heights[1] - heights[0]
    cols = np.arange(c.shape[1])
    best = (np.inf, h0)
    for a in tilts:
        for b in tilts:
            z = hs[:, None] + a * dx[None] + b * dy[None]          # (hs, cells)
            f = np.clip((z - heights[0]) / dh, 0, len(heights) - 1.001)
            i = f.astype(int)
            t = f - i
            v = c[i, cols] * (1 - t) + c[i + 1, cols] * t
            curve = (v * w).sum(1)
            k = int(np.argmin(curve))
            if curve[k] < best[0]:
                best = (curve[k], refine(curve, hs))
    return best[1]


def rises(top, ring, height, conf, cost, texture, heights):
    """Each variant's rise of `top` over `ring` (both boolean grids). Returns dict variant -> mm."""
    good = conf > 0.5
    out = {}
    t, r = height[top & good], height[ring & good]
    if t.size < 20 or r.size < 20:
        return None
    out["current (p30 ring)"] = float(np.median(t) - np.percentile(r, 30))
    out["median conf cells"] = float(np.median(t) - np.median(r))
    wconf = np.clip(conf, 0, None)
    out["cost sum"] = seg_height(cost, top, heights) - seg_height(cost, ring, heights)
    out["cost sum, conf-wt"] = seg_height(cost, top, heights, wconf) - seg_height(cost, ring, heights, wconf)
    out["cost sum, texture-wt"] = seg_height(cost, top, heights, texture) - seg_height(cost, ring, heights, texture)
    ys, xs = np.nonzero(top)
    at = (ys.mean(), xs.mean())
    out["flat top, plane ring (tex-wt)"] = seg_height(cost, top, heights, texture) - seg_plane(cost, ring, heights, texture, at)
    out["plane top+ring (tex-wt)"] = seg_plane(cost, top, heights, texture, at) - seg_plane(cost, ring, heights, texture, at)
    return out


# ---- remote --------------------------------------------------------------------------------------------------------

def remote():
    d = os.path.join(ct.OUT, "scan_1080")
    poses = json.load(open(os.path.join(d, "poses.json")))
    bgr = [cv2.imread(os.path.join(d, p["file"])) for p in poses]
    K, dist = ct.load_calib(bgr[0].shape[1])
    heights = st.HEIGHTS
    cache = os.path.join(HERE, "remote_volume.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        height, conf, cost, texture = z["height"], z["conf"], z["cost"].astype(np.float32), z["texture"]
    else:
        gray = [cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for b in bgr]
        height, conf, cost, texture = sweep_volume(gray, poses, K, dist, heights)
        np.savez(cache, height=height, conf=conf, cost=cost.astype(np.float16), texture=texture)
    old = np.load(os.path.join(d, "scan_sweep.npz"))
    print("matches the pipeline's cached sweep: max |dh| on confident cells",
          float(np.abs(old["height"] - height)[conf > 0.5].max()))
    # object, crop, ortho, masks: as scan_test.cmd_scan
    good = conf > 0.5
    raised = height[good & (height > 3)]
    top = float(np.median(raised))
    obj = (good & (height > max(top - 6, 1.0))).astype(np.uint8)
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, lab, stt, _ = cv2.connectedComponentsWithStats(obj)
    obj = lab == 1 + int(np.argmax(stt[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(obj)
    mc = int(3 / MM_PX)
    c0, r0 = max(xs.min() - mc, 0), max(ys.min() - mc, 0)
    c1, r1 = min(xs.max() + mc, obj.shape[1] - 1), min(ys.max() + mc, obj.shape[0] - 1)
    mcache = os.path.join(HERE, "remote_masks.npz")
    if os.path.exists(mcache):
        grids = list(np.load(mcache)["grids"])
    else:
        region = (c0 * MM_PX, r0 * MM_PX, (c1 + 1) * MM_PX, (r1 + 1) * MM_PX)
        ortho = st.orthophoto(bgr, poses, K, dist, top, region, st.ORTHO_MM_PX)
        inside = cv2.resize(obj[r0:r1 + 1, c0:c1 + 1].astype(np.uint8), ortho.shape[1::-1], interpolation=cv2.INTER_NEAREST)
        ortho[~cv2.dilate(inside, np.ones((15, 15), np.uint8)).astype(bool)] = 128
        cv2.imwrite(os.path.join(HERE, "ortho.jpg"), ortho)
        grids = []
        for m in st.part_masks(ortho, st.ORTHO_MM_PX):
            g = np.zeros_like(obj)
            g[r0:r1 + 1, c0:c1 + 1] = cv2.resize(m.astype(np.uint8), (c1 - c0 + 1, r1 - r0 + 1), interpolation=cv2.INTER_NEAREST) > 0
            grids.append(g)
        np.savez_compressed(mcache, grids=np.array(grids))
    others = cv2.dilate(np.any(grids, axis=0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    obj_wide = cv2.dilate(obj.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (height > top - 8)
    ell = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (97, 97))
    rows = []
    for g in grids:
        c = st.classify(g, height, conf, others, obj_wide)
        if not c:
            continue
        inner = cv2.erode(g.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        ring = cv2.dilate(g.astype(np.uint8), ell).astype(bool) & ~others & obj_wide
        r = rises(inner, ring, height, conf, cost, texture, heights)
        if r:
            rows.append({"centre_mm": c["centre_mm"], "size_mm": c["size_mm"], **r})
    rows.sort(key=lambda p: (round(p["centre_mm"][1] / 4), p["centre_mm"][0]))
    json.dump(rows, open(os.path.join(HERE, "remote_rows.json"), "w"), indent=1)
    keys = list(rows[0].keys())[2:]
    print(" #   centre(mm)    size(mm)   " + " | ".join(k[:12] for k in keys))
    for i, p in enumerate(rows):
        print(f"{i:2d} ({p['centre_mm'][0]:5.1f},{p['centre_mm'][1]:5.1f}) {p['size_mm'][0]:4.1f}x{p['size_mm'][1]:4.1f}  "
              + " | ".join(f"{p[k]:12.2f}" for k in keys))
    # labelled picture of the crop to identify keys
    vis = cv2.cvtColor((np.clip(height[r0:r1 + 1, c0:c1 + 1] / max(top, 1), 0, 1) * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    vis = cv2.resize(vis, None, fx=3, fy=3)
    for i, p in enumerate(rows):
        x, y = int((p["centre_mm"][0] / MM_PX - c0) * 3), int((p["centre_mm"][1] / MM_PX - r0) * 3)
        cv2.putText(vis, str(i), (x - 10, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    cv2.imwrite(os.path.join(HERE, "remote_index.jpg"), vis)


# ---- coins ---------------------------------------------------------------------------------------------------------

def coins():
    d = os.path.join(ct.OUT, "height")
    poses = json.load(open(os.path.join(d, "poses.json")))
    frames = [cv2.cvtColor(cv2.imread(os.path.join(d, p["file"])), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for p in poses]
    c = json.load(open(os.path.join(ct.OUT, "calib_720p_before_refocus", "calib.json")))
    K, dist = ct.scaled(c["K"], frames[0].shape[1], c["size"][0]), np.array(c["dist"])
    heights = ht.HEIGHTS
    height, conf, cost, texture = sweep_volume(frames, poses, K, dist, heights)
    base, found = ht.find_coins(height, conf)
    print("find_coins (pipeline):", [round(f["height_mm"], 2) for f in found])
    good = conf > 0.5
    mask = ((height - base > 0.8) & good).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, lab, stt, _ = cv2.connectedComponentsWithStats(mask)
    segs = [lab == i for i in range(1, n) if stt[i, cv2.CC_STAT_AREA] * MM_PX ** 2 > 150]
    others = cv2.dilate(np.any(segs, 0).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    ell = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (97, 97))
    res = []
    for s in segs:
        core = cv2.erode(s.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        ring = cv2.dilate(s.astype(np.uint8), ell).astype(bool) & ~others
        r = rises(core, ring, height, conf, cost, texture, heights)
        res.append(r)
    res.sort(key=lambda r: r["cost sum"])
    out = {}
    for k in res[0]:
        single, stack = res[0][k], res[-1][k]
        out[k] = {"single": single, "stack": stack, "diff": stack - single}
        print(f"{k:30s} single {single:5.2f} (1.75)  stack {stack:5.2f} (5.25)  diff {stack - single:5.2f} (3.50)")
    json.dump(out, open(os.path.join(HERE, "coins.json"), "w"), indent=1)


if __name__ == "__main__":
    {"remote": remote, "coins": coins}[next(a for a in sys.argv[1:] if a in ("remote", "coins"))]()
