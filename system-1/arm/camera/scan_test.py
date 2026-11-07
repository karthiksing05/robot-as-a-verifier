"""The robot's scan, end to end on real photos: a TV remote lying on the tablet's calibration board.
Run with the repo's environment, after camera_test.py calib.

    python scan_test.py capture     # handheld, 15-20 cm above: 20 steady views, each a beep
    python scan_test.py scan        # heights, a straight-on picture, outlines, each part's height and kind
    python scan_test.py scan --720  # the same photos shrunk to 720p, saved as *_720, to compare

The board gives each photo's camera position, standing in for the arm's joint readings. Then the robot's own steps:
1. heights by plane sweep (height_test.py), from the board up to 35 mm;
2. a straight-on picture of the scene (an orthophoto): the photos projected onto the remote's top surface and averaged;
3. part outlines: OWLv2 boxes outlined by SAM, plus SAM's own search for parts (system-1/core/segmodels.py);
4. each outline's height above the surface just around it, as a button stands above its panel;
5. a kind for each: raised and compact is a button, raised and long a rocker, flat is printing.

Results go to camera_out/scan/ (or --dir NAME): scan_map.jpg (the picture with each part labelled) and scan_heights.png.
"""
import json
import os
import sys
import threading
import time

import cv2
import numpy as np
import torch

import height_test as ht

ct = ht.ct
ht.DIR = os.path.join(ct.OUT, sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else "scan")
os.makedirs(ht.DIR, exist_ok=True)
HEIGHTS = np.arange(-1.0, 35.01, 0.5)   # mm above the board image: the remote is about 20 mm thick. Refined between planes
RAISED_MM = 0.5                        # a part standing this far above the surface around it is raised
TAG = "_720" if "--720" in sys.argv else ""   # --720: shrink the photos to 1280x720 first, to compare with 1080p
ORTHO_MM_PX = 0.1                      # the straight-on picture's resolution: fine enough for SAM to find small buttons
sys.path.insert(0, ct.CORE)  # segmodels.py


def orthophoto(frames_bgr, poses, K, dist, h_mm, region, mm_px):
    """The photos projected onto a flat plane h mm above the board, over region (x0, y0, x1, y1 in board mm) at mm_px
    per pixel, and averaged (median): a straight-on picture."""
    x0, y0, x1, y1 = region
    size = (int((x1 - x0) / mm_px), int((y1 - y0) / mm_px))
    S = np.array([[mm_px / 1000, 0, x0 / 1000], [0, mm_px / 1000, y0 / 1000], [0, 0, 1.0]])  # picture px -> board metres
    stack, valid = [], []
    for f, p in zip(frames_bgr, poses):
        R, t = cv2.Rodrigues(np.array(p["rvec"]))[0], np.array(p["tvec"])
        H = K @ np.c_[R[:, 0], R[:, 1], t - (h_mm / 1000) * R[:, 2]] @ S
        flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
        stack.append(cv2.warpPerspective(cv2.undistort(f, K, dist), H, size, flags=flags).astype(np.float32))
        valid.append(cv2.warpPerspective(cv2.undistort(np.full(f.shape[:2], 255, np.uint8), K, dist), H, size, flags=flags) > 250)
    stack = np.stack(stack)
    stack[~np.stack(valid)] = np.nan
    # the median of the photos that see each pixel, on the GPU (NumPy's nanmedian takes about 6 s). Sorting puts the
    # unseen (NaN) last; with an even count, the two middle values are averaged, as NumPy does
    srt = torch.from_numpy(stack).to(ht.DEV).sort(0).values
    n = (~srt.isnan()).sum(0, keepdim=True)
    med = (srt.gather(0, (n - 1).clamp(min=0) // 2) + srt.gather(0, n // 2)) / 2
    return np.nan_to_num(med[0].cpu().numpy(), nan=0).astype(np.uint8)


def part_masks(img, mm_px):
    """Outlines from the robot's two sources: OWLv2 boxes outlined by SAM, and SAM's own search. Overlaps merged."""
    import segmodels
    boxes, _, _ = segmodels.owl()(img)
    masks = list(segmodels.sam_boxes()(img, boxes)[0]) if len(boxes) else []
    masks += list(segmodels.sam_auto()(img)[0])
    area = img.shape[0] * img.shape[1]
    keep = []
    for m in sorted((m.astype(bool) for m in masks), key=lambda m: m.sum()):
        a = m.sum()
        if not (20 / mm_px ** 2 < a < 0.08 * area):  # from 20 mm2 (a 4.5 mm square) to a twelfth of the picture
            continue
        if any((m & k).sum() > 0.5 * min(a, k.sum()) for k in keep):  # mostly the same region as one already kept
            continue
        keep.append(m)
    return keep


def classify(mask, height, conf, others, obj):
    """Height of a part above the surface around it, its size, and its kind. The surface is the 30th percentile of the
    confident heights within 12 mm, outside every outlined part: between packed buttons, the body is often too plain
    to measure, and a ring's middle value would land on the neighbours' raised edges."""
    good = conf > 0.5
    near = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (97, 97))).astype(bool)
    around = near & ~others & good & obj  # on the object only: past its edge is the board, far below
    inner = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    top, base = height[inner & good], height[around]
    if top.size < 20 or base.size < 20:
        return None
    rise = float(np.median(top) - np.percentile(base, 30))
    ys, xs = np.nonzero(mask)
    (w, h) = cv2.minAreaRect(np.c_[xs, ys].astype(np.float32))[1]
    long_mm, short_mm = max(w, h) * ht.MM_PX, min(w, h) * ht.MM_PX
    kind = "flat print" if rise < RAISED_MM else "rocker" if long_mm > 1.8 * short_mm and long_mm > 15 else "button"
    return {"rise_mm": rise, "size_mm": (long_mm, short_mm), "kind": kind, "surface_mm": float(np.percentile(base, 30)),
            "centre_mm": (float(xs.mean() * ht.MM_PX), float(ys.mean() * ht.MM_PX))}


def load_models():
    import segmodels
    segmodels.owl(), segmodels.sam_boxes(), segmodels.sam_auto()


def cmd_scan():
    loader = threading.Thread(target=load_models, daemon=True)  # loads while the heights and picture are worked out
    loader.start()
    poses = json.load(open(os.path.join(ht.DIR, "poses.json")))
    bgr = [cv2.imread(os.path.join(ht.DIR, p["file"])) for p in poses]
    if TAG:
        bgr = [cv2.resize(b, (1280, 720), interpolation=cv2.INTER_AREA) for b in bgr]
    K, dist = ct.load_calib(bgr[0].shape[1])
    gray = [cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for b in bgr]
    heights = HEIGHTS if "--coins" not in sys.argv else ht.HEIGHTS
    t0 = time.time()
    print(f"1. heights: {len(poses)} views, {len(heights)} planes from {heights[0]:.0f} to {heights[-1]:.0f} mm...")
    cache = os.path.join(ht.DIR, f"scan_sweep{TAG}.npz")
    if os.path.exists(cache) and "--resweep" not in sys.argv and os.path.getmtime(cache) > os.path.getmtime(os.path.join(ht.DIR, "poses.json")):
        d = np.load(cache)
        height, conf = d["height"], d["conf"]
        print("   (reusing the saved height map; --resweep recomputes it)")
    else:
        height, conf = ht.sweep(gray, poses, K, dist, heights)
        np.savez(cache, height=height, conf=conf)
    good = conf > 0.5
    raised = height[good & (height > 3)]
    top = float(np.median(raised)) if raised.size > 500 else 0.0
    print(f"   done in {time.time() - t0:.0f} s. Board at {np.median(height[good & (height < 3)]):+.2f} mm; "
          f"the object's top surface at about {top:.1f} mm")
    # the object: the largest confident region standing well above the board, with a 3 mm margin
    obj = (good & (height > max(top - 6, 1.0))).astype(np.uint8)
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))  # bridges the plain bands between key rows
    n, lab, st, _ = cv2.connectedComponentsWithStats(obj)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])) if n > 1 else 0
    obj = lab == k
    ys, xs = np.nonzero(obj)
    m_cells = int(3 / ht.MM_PX)
    c0, r0 = max(xs.min() - m_cells, 0), max(ys.min() - m_cells, 0)
    c1, r1 = min(xs.max() + m_cells, obj.shape[1] - 1), min(ys.max() + m_cells, obj.shape[0] - 1)
    region = (c0 * ht.MM_PX, r0 * ht.MM_PX, (c1 + 1) * ht.MM_PX, (r1 + 1) * ht.MM_PX)
    print(f"2. straight-on picture of the object ({region[2] - region[0]:.0f} x {region[3] - region[1]:.0f} mm) "
          f"at {top:.1f} mm, {ORTHO_MM_PX} mm per pixel...")
    ortho = orthophoto(bgr, poses, K, dist, top, region, ORTHO_MM_PX)
    # grey out everything that isn't the object, so the image models only see it
    inside = cv2.resize(obj[r0:r1 + 1, c0:c1 + 1].astype(np.uint8), ortho.shape[1::-1], interpolation=cv2.INTER_NEAREST)
    inside = cv2.dilate(inside, np.ones((15, 15), np.uint8)).astype(bool)
    ortho[~inside] = 128
    loader.join()
    print("3. outlines (OWLv2 + SAM, then SAM's own search)...")
    masks = part_masks(ortho, ORTHO_MM_PX)
    print(f"   {len(masks)} regions")
    print("4-5. each region's height above the surface around it, and its kind:")
    grids = []
    for m in masks:
        grid = np.zeros_like(obj)  # the outline moved onto the height map's grid
        grid[r0:r1 + 1, c0:c1 + 1] = cv2.resize(m.astype(np.uint8), (c1 - c0 + 1, r1 - r0 + 1), interpolation=cv2.INTER_NEAREST) > 0
        grids.append(grid)
    others = cv2.dilate(np.any(grids, axis=0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) if grids else np.zeros_like(obj)
    obj_wide = cv2.dilate(obj.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (height > top - 8)
    parts = []
    for m, grid in zip(masks, grids):
        c = classify(grid, height, conf, others, obj_wide)
        if c:
            parts.append((m, c))
    out = ortho.copy()
    colours = {"button": (0, 220, 0), "rocker": (0, 160, 255), "flat print": (150, 150, 150)}
    for i, (m, c) in enumerate(sorted(parts, key=lambda p: (p[1]["centre_mm"][1], p[1]["centre_mm"][0])), 1):
        cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, cnts, -1, colours[c["kind"]], 3 if c["kind"] != "flat print" else 1)
        if c["kind"] != "flat print":
            yy, xx = np.nonzero(m)
            label, org = f"{c['rise_mm']:.1f}", (int(xx.mean()) - 22, int(yy.mean()) + 10)
            cv2.putText(out, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
            cv2.putText(out, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            print(f"   {i:2d}. {c['kind']:10s} {c['rise_mm']:5.2f} mm high, {c['size_mm'][0]:4.1f} x {c['size_mm'][1]:4.1f} mm, "
                  f"at ({c['centre_mm'][0]:5.1f}, {c['centre_mm'][1]:5.1f}) mm")
    counts = {k: sum(c["kind"] == k for _, c in parts) for k in colours}
    print(f"   {counts['button']} buttons, {counts['rocker']} rockers, {counts['flat print']} flat (printing or glare)")
    cv2.imwrite(os.path.join(ht.DIR, f"scan_map{TAG}.jpg"), out)
    vis = cv2.applyColorMap(np.clip((height - heights[0]) / (heights[-1] - heights[0]) * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    vis[~good] = (vis[~good] * 0.25).astype(np.uint8)
    cv2.imwrite(os.path.join(ht.DIR, f"scan_heights{TAG}.png"), vis)
    np.save(os.path.join(ht.DIR, f"scan_heights{TAG}.npy"), height)
    print(f"Saved scan_map{TAG}.jpg (green button, orange rocker, grey flat; numbers are heights in mm) and scan_heights{TAG}.png "
          f"in {ht.DIR}. Total {time.time() - t0:.0f} s.")


if __name__ == "__main__":
    cmd = "capture" if "capture" in sys.argv[1:] else "scan"
    if cmd == "capture":
        print("Lay the remote on the board so at least half the board's squares stay visible. Hold the camera 15-20 cm up, "
              "pointing down, so it sees the remote and plenty of board. Move a few cm and tilt a little between beeps.")
        ht.cmd_capture()
    else:
        cmd_scan()
