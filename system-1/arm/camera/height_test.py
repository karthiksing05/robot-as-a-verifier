"""Heights from photos alone, the trick the robot's scan relies on: quarters on the tablet's calibration board.
Run with the repo's environment, after camera_test.py calib (it uses camera_out/calib.json).

    python height_test.py capture    # handheld, about 12-15 cm above the board: 20 steady views, each a beep
    python height_test.py measure    # plane sweep from 0 to 9 mm; finds the coins and reports their heights

Setup: the board full screen on the tablet, one quarter alone and a stack of three elsewhere on the board, both well
inside it. A quarter is 1.75 mm thick, so 1.75 and 5.25 mm. The board is drawn under the tablet's cover glass, so both
heights read a little high by the same amount; the stack minus the single (3.50 mm) cancels that.

The board gives each photo's camera position, as the arm's joint readings will on the rig. Heights come from how
points shift between photos: for each candidate height, every photo is projected onto that height, and the height
where the photos agree best wins.
"""
import json
import math
import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F

sys.argv.append("--target=tab") if not any(a.startswith("--target") for a in sys.argv) else None
import camera_test as ct  # noqa: E402

DIR = os.path.join(ct.OUT, "height")
os.makedirs(DIR, exist_ok=True)
MM_PX = 0.25                     # the top-down grid, mm per cell
HEIGHTS = np.arange(-1.0, 9.01, 0.25)  # mm above the board image; the sweep refines between planes
WIN = 9                          # matching window, cells (2.25 mm)
STILL_PX, STILL_FRAMES = 1.5, 2  # a view is steady after this many frames moving under this many px
MIN_TEXTURE = 0.02               # brightness spread (0-1 scale) a patch needs before its height is trusted
QUARTER_MM, QUARTER_D_MM = 1.75, 24.26
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def pose(corners, ids, K, dist):
    obj, img = ct.BOARD.matchImagePoints(corners, ids)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist)
    return ok, rvec.ravel(), tvec.ravel()


def cmd_capture():
    K, dist = ct.load_calib(ct.SIZE[0])
    print("Hold the camera 12-15 cm above the coins, pointing down at the board. Move it around a little between "
          "beeps (a few cm, and tilt a bit); hold still for each. 20 views; q finishes early.")
    cam = ct.Cam()
    poses, prev, still, last_t, v_at = [], None, 0, 0.0, 0.0
    while len(poses) < 20:
        frame, _ = cam.read()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids = ct.detect(gray)
        status = "board not seen"
        if corners is not None and len(ids) >= 10:
            pts = dict(zip(ids.ravel().tolist(), corners.reshape(-1, 2).tolist()))
            if prev is not None:
                common = [k for k in pts if k in prev]
                moved = np.median([np.hypot(*np.subtract(pts[k], prev[k])) for k in common]) if common else 99
                still = still + 1 if moved < STILL_PX * ct.SIZE[0] / 1280 else 0
            prev = pts
            ok, rvec, tvec = pose(corners, ids, K, dist)
            height = -cv2.Rodrigues(rvec)[0].T @ tvec  # camera centre in board coordinates
            new = all(np.linalg.norm(height - np.array(p["centre"])) > 0.008 for p in poses)
            status = f"{len(ids)} corners, {abs(height[2]) * 100:.1f} cm up, {'steady' if still >= STILL_FRAMES else 'hold still'}"
            force = time.time() - v_at < 1.0
            if ok and (force or (still >= STILL_FRAMES and new and time.time() - last_t > 0.7)):
                n = len(poses) + 1
                cv2.imwrite(os.path.join(DIR, f"view_{n:02d}.jpg"), frame)
                poses.append({"file": f"view_{n:02d}.jpg", "rvec": rvec.tolist(), "tvec": tvec.tolist(), "centre": height.tolist()})
                last_t, still, v_at = time.time(), 0, 0.0
                json.dump(poses, open(os.path.join(DIR, "poses.json"), "w"), indent=1)  # kept even if stopped early
                ct.beep()
        else:
            prev, still = None, 0
        view = frame.copy()
        cv2.putText(view, f"views {len(poses)}/20   {status}   (v: capture now, q: finish)", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.imshow("camera", cv2.resize(view, (1280, 720)))
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("v"):
            v_at = time.time()
    cam.close()
    cv2.destroyAllWindows()
    json.dump(poses, open(os.path.join(DIR, "poses.json"), "w"), indent=1)
    print(f"Saved {len(poses)} views. Now run: height_test.py measure")


def box(x):
    """cv2.blur's box filter, with the same edge handling, on a (N, 1, H, W) tensor."""
    r = WIN // 2
    return F.avg_pool2d(F.pad(x, (r, r, r, r), mode="reflect"), WIN, stride=1)


def local_norm(x):
    """Each pixel minus its neighbourhood mean, over its neighbourhood spread: brightness changes between photos cancel."""
    m = box(x)
    return (x - m) / torch.sqrt(torch.clamp(box(x * x) - m * m, min=1e-4))


def sweep(frames, poses, K, dist, heights=HEIGHTS):
    """Height map (mm) and its matching cost on a top-down grid over the board.

    Each photo is straightened once with the calibration; after that, projecting a flat plane at any height into it is
    a single perspective warp (a homography). The warps and matching run on the GPU when there is one."""
    w_mm, h_mm = ct.SQ[0] * ct.SQ_MM, ct.SQ[1] * ct.SQ_MM
    size = (int(w_mm / MM_PX), int(h_mm / MM_PX))
    straight = [cv2.undistort(f, K, dist) for f in frames]
    ones = [cv2.undistort(np.ones_like(f), K, dist) for f in frames]  # which straightened pixels hold real image
    S = np.diag([MM_PX / 1000, MM_PX / 1000, 1.0])  # grid cell -> metres on the board
    # brightness spread around each cell in the first photo, before normalising
    raw = cv2.warpPerspective(straight[0], K @ np.c_[cv2.Rodrigues(np.array(poses[0]['rvec']))[0][:, :2],
                              np.array(poses[0]['tvec'])] @ S, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    m = cv2.blur(raw, (WIN, WIN))
    texture = np.sqrt(np.maximum(cv2.blur(raw * raw, (WIN, WIN)) - m * m, 0))

    src = torch.from_numpy(np.stack([np.stack([s, o]) for s, o in zip(straight, ones)])).to(DEV)  # photo, then coverage
    ih, iw = frames[0].shape
    ys, xs = torch.meshgrid(torch.arange(size[1]), torch.arange(size[0]), indexing="ij")
    cells = torch.stack([xs, ys, torch.ones_like(xs)], -1).reshape(-1, 3).float().to(DEV)  # float32: laptop GPUs are slow at float64
    Rs = [cv2.Rodrigues(np.array(p["rvec"]))[0] for p in poses]
    ts = [np.array(p["tvec"]) for p in poses]
    costs = []
    for h in heights:
        # board coordinates: z points into the board, so a plane h mm above it is z = -h
        Hs = np.stack([K @ np.c_[R[:, 0], R[:, 1], t - (h / 1000) * R[:, 2]] @ S for R, t in zip(Rs, ts)])  # cell -> pixel
        uvw = cells @ torch.from_numpy(Hs).float().to(DEV).transpose(1, 2)
        uv = uvw[..., :2] / uvw[..., 2:]
        grid = torch.stack([uv[..., 0] / (iw - 1) * 2 - 1, uv[..., 1] / (ih - 1) * 2 - 1], -1)
        warped = F.grid_sample(src, grid.reshape(len(poses), size[1], size[0], 2), align_corners=True)
        stack, valid = local_norm(warped[:, :1]), (warped[:, 1:] > 0.99).float()
        n = valid.sum(0)
        mean = (stack * valid).sum(0) / n.clamp(min=1)
        var = ((stack - mean) ** 2 * valid).sum(0) / n.clamp(min=1)
        costs.append(torch.where(n[0] >= 4, box(var[None])[0, 0], torch.inf))
    cost = torch.stack(costs)
    seen = torch.isfinite(cost)
    total, count = torch.where(seen, cost, 0).sum(0), seen.sum(0)
    best, k = cost.min(0)
    # between planes: a parabola through the best plane's cost and its two neighbours puts the minimum between them
    kk = k.clamp(1, len(heights) - 2)
    c0, c1, c2 = (cost.gather(0, (kk + d)[None])[0] for d in (-1, 0, 1))
    curve = c0 - 2 * c1 + c2
    off = torch.where(torch.isfinite(curve) & (curve > 0) & (k == kk), 0.5 * (c0 - c2) / curve, 0).clamp(-0.5, 0.5)
    height = torch.as_tensor(heights, dtype=torch.float32, device=DEV)[k] + off * float(heights[1] - heights[0])
    best, height, total, count = (x.cpu().numpy() for x in (best, height, total, count))
    # confidence: how much better the best height matched than the average height. A plain patch matches every height
    # about equally (near 0); a textured surface at one height stands out (near 1)
    conf = np.where(count > 0, 1 - best / np.maximum(total / np.maximum(count, 1), 1e-6), 0).astype(np.float32)
    # a patch with almost no brightness variation has nothing to match: JPEG flattens it, so every height 'agrees'
    conf[texture < MIN_TEXTURE] = 0
    return height, conf


def find_coins(height, conf, min_conf=0.5):
    """Connected regions standing more than about half a coin above the background, trusting only confident cells."""
    good = conf > min_conf
    base = float(np.median(height[good])) if good.any() else float(np.median(height))
    # confident raised cells, with the gaps between them closed: unsure patches inside a coin would otherwise split it
    mask = ((height - base > 0.8) & good).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    coins = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA] * MM_PX ** 2
        if area > 150:  # a quarter is 462 mm2
            # the middle of each region only: the rim's matching windows straddle the coin and the board
            reg = (lab == i).astype(np.uint8)
            core = cv2.erode(reg, np.ones((15, 15), np.uint8)).astype(bool)
            core &= good
            vals = height[core] if core.sum() > 50 else height[reg.astype(bool) & good]
            if vals.size == 0:
                continue
            coins.append({"height_mm": float(np.median(vals)) - base, "spread_mm": float(np.std(vals)),
                          "diameter_mm": 2 * math.sqrt(area / math.pi), "centre_mm": (cent[i] * MM_PX).tolist()})
    return base, sorted(coins, key=lambda c: c["height_mm"])


def cmd_measure():
    path = os.path.join(DIR, "poses.json")
    if not os.path.exists(path):
        sys.exit("No views yet. Run `height_test.py capture` first: it saves a photo and its camera position at each beep.")
    poses = json.load(open(path))
    if len(poses) < 6:
        sys.exit(f"Only {len(poses)} views: capture at least 6, ideally 20.")
    frames = [cv2.cvtColor(cv2.imread(os.path.join(DIR, p["file"])), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for p in poses]
    K, dist = ct.load_calib(frames[0].shape[1])
    print(f"{len(frames)} views; sweeping {len(HEIGHTS)} heights from {HEIGHTS[0]:.1f} to {HEIGHTS[-1]:.1f} mm...")
    t0 = time.time()
    height, conf = sweep(frames, poses, K, dist)
    base, coins = find_coins(height, conf)
    print(f"done in {time.time() - t0:.0f} s. Board background reads {base:+.2f} mm (the board plane is 0).")
    for c in coins:
        n_q = round(c["height_mm"] / QUARTER_MM)
        print(f"  coin region at ({c['centre_mm'][0]:.0f}, {c['centre_mm'][1]:.0f}) mm: height {c['height_mm']:.2f} mm "
              f"(spread {c['spread_mm']:.2f}), diameter {c['diameter_mm']:.1f} mm  ~ {n_q} quarter(s) = {n_q * QUARTER_MM:.2f} mm, "
              f"diameter {QUARTER_D_MM} mm")
    if len(coins) >= 2:
        d = coins[-1]["height_mm"] - coins[0]["height_mm"]
        print(f"Stack minus single: {d:.2f} mm (two quarters: {2 * QUARTER_MM:.2f} mm). This difference cancels the cover glass.")
    vis = cv2.applyColorMap(np.clip((height - HEIGHTS[0]) / (HEIGHTS[-1] - HEIGHTS[0]) * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    vis[conf <= 0.5] = (vis[conf <= 0.5] * 0.25).astype(np.uint8)  # dim the cells it isn't sure about
    cv2.imwrite(os.path.join(DIR, "height_map.png"), vis)
    np.save(os.path.join(DIR, "height_map.npy"), height)
    print(f"Height map: {os.path.join(DIR, 'height_map.png')} (blue = low, red = high)")


if __name__ == "__main__":
    cmd = next((a for a in sys.argv[1:] if not a.startswith("--")), "measure")
    {"capture": cmd_capture, "measure": cmd_measure}[cmd]()
