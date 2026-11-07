"""Can noisy arm poses be corrected from the photos alone (no board markers)?

    python experiments/pose_refine/pose_refine.py coins|remote   (cwd system-1/arm/camera, PYTHONPATH=.)

Board poses -> per-view noise (stand-in for arm readings) -> SIFT matches across views (ArUco markers masked, or kept)
-> tracks -> triangulate -> bundle adjustment with a prior on every pose (fixes scale and gauge, as the arm would) -> sweep.
"""
import json
import os
import sys
import time

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation

import camera_test as ct
import height_test as ht
import scan_test as st

NFEV, LOSS, FS = 1000, "linear", 1.0  # outliers already dropped by RANSAC and the reprojection gate
HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    if name == "coins":
        d = os.path.join(ct.OUT, "height")
        c = json.load(open(os.path.join(ct.OUT, "calib_720p_before_refocus", "calib.json")))
        K, dist = ct.scaled(c["K"], 1280, c["size"][0]), np.array(c["dist"])
        heights = ht.HEIGHTS
    else:
        d = os.path.join(ct.OUT, "scan_1080")
        K, dist = ct.load_calib(1920)
        heights = st.HEIGHTS
    poses = json.load(open(os.path.join(d, "poses.json")))
    gray8 = [cv2.cvtColor(cv2.imread(os.path.join(d, p["file"])), cv2.COLOR_BGR2GRAY) for p in poses]
    return gray8, poses, K, dist, heights


def to_rt(poses):
    return [(np.array(p["rvec"], float), np.array(p["tvec"], float)) for p in poses]


def to_poses(rts):
    return [{"rvec": r.tolist(), "tvec": t.tolist()} for r, t in rts]


def corrupt(rts, mm, deg, seed):
    """Move each camera centre by `mm` and turn it by `deg`, each in a random direction."""
    rng = np.random.default_rng(seed)
    out = []
    for r, t in rts:
        R = Rotation.from_rotvec(r)
        C = -R.inv().apply(t)
        u = rng.normal(size=3); u /= np.linalg.norm(u)
        a = rng.normal(size=3); a /= np.linalg.norm(a)
        R2 = Rotation.from_rotvec(np.radians(deg) * a) * R
        out.append((R2.as_rotvec(), -R2.apply(C + u * mm / 1000)))
    return out


def pose_err(a, b):
    """Mean camera-centre error (mm) and rotation error (deg) between two pose lists."""
    dc, dr = [], []
    for (r1, t1), (r2, t2) in zip(a, b):
        R1, R2 = Rotation.from_rotvec(r1), Rotation.from_rotvec(r2)
        dc.append(np.linalg.norm(R1.inv().apply(t1) - R2.inv().apply(t2)) * 1000)
        dr.append(np.degrees((R1 * R2.inv()).magnitude()))
    return float(np.mean(dc)), float(np.mean(dr))


def marker_mask(g):
    """255 except on the ArUco markers (grown a little), found by the marker detector alone."""
    m = np.full(g.shape, 255, np.uint8)
    corners, _, _ = cv2.aruco.ArucoDetector(ct.DICT).detectMarkers(g)
    for c in corners:
        cv2.fillConvexPoly(m, c.reshape(-1, 2).astype(np.int32), 0)
    return cv2.erode(m, np.ones((15, 15), np.uint8))


def tracks(gray8, K, dist, mask_markers):
    """SIFT matches between every pair of views, checked with RANSAC, chained into tracks {view: normalised xy}."""
    sift = cv2.SIFT_create(nfeatures=4000)
    feats = []
    for g in gray8:
        kp, des = sift.detectAndCompute(g, marker_mask(g) if mask_markers else None)
        xy = np.array([k.pt for k in kp], np.float32)
        und = cv2.undistortPoints(xy.reshape(-1, 1, 2), K, dist).reshape(-1, 2)
        feats.append((xy, und, des))
    off = np.cumsum([0] + [len(f[0]) for f in feats])
    parent = np.arange(off[-1])

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    bf = cv2.BFMatcher(cv2.NORM_L2)
    n = len(gray8)
    for i in range(n):
        for j in range(i + 1, n):
            good = [p[0] for p in bf.knnMatch(feats[i][2], feats[j][2], k=2)
                    if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
            if len(good) < 20:
                continue
            qi = np.array([g.queryIdx for g in good]); tj = np.array([g.trainIdx for g in good])
            _, inl = cv2.findFundamentalMat(feats[i][0][qi], feats[j][0][tj], cv2.FM_RANSAC, 1.5, 0.999)
            if inl is None:
                continue
            for a, b in zip(qi[inl.ravel() == 1], tj[inl.ravel() == 1]):
                ra, rb = find(off[i] + a), find(off[j] + b)
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for v in range(n):
        for k in range(len(feats[v][0])):
            groups.setdefault(find(off[v] + k), {}).setdefault(v, feats[v][1][k])
    return [t for t in groups.values() if len(t) >= 3]


def triangulate(track, rts):
    A = []
    for v, (x, y) in track.items():
        P = np.c_[cv2.Rodrigues(rts[v][0])[0], rts[v][1]]
        A += [x * P[2] - P[0], y * P[2] - P[1]]
    X = np.linalg.svd(np.array(A))[2][-1]
    return X[:3] / X[3]


def refine(rts, trks, f, sig_mm, sig_deg, max_pts=3000):
    """Bundle adjustment: all poses and points free, intrinsics fixed, every pose tied to its arm reading by a prior."""
    n = len(rts)
    Rs = [Rotation.from_rotvec(r) for r, _ in rts]
    pts, keep = [], []
    for t in trks:
        X = triangulate(t, rts)
        ok = True
        for v, xy in t.items():
            Xc = Rs[v].apply(X) + rts[v][1]
            if Xc[2] <= 0 or np.linalg.norm(Xc[:2] / Xc[2] - xy) * f > 50:  # generous: the poses are still off
                ok = False
                break
        if ok:
            keep.append(t); pts.append(X)
    order = np.argsort([-len(t) for t in keep])[:max_pts]
    trks, pts = [keep[i] for i in order], np.array([pts[i] for i in order])
    cam_i, pt_i, obs = [], [], []
    for p, t in enumerate(trks):
        for v, xy in t.items():
            cam_i.append(v); pt_i.append(p); obs.append(xy)
    cam_i, pt_i, obs = np.array(cam_i), np.array(pt_i), np.array(obs)
    prior_R = Rotation.from_rotvec([r for r, _ in rts])
    prior_C = np.array([-R.inv().apply(t) for R, (_, t) in zip(Rs, rts)])
    m = len(obs)

    def resid(x):
        cams, X = x[:6 * n].reshape(n, 6), x[6 * n:].reshape(-1, 3)
        Xc = Rotation.from_rotvec(cams[cam_i, :3]).apply(X[pt_i]) + cams[cam_i, 3:]
        r_img = (Xc[:, :2] / Xc[:, 2:] - obs).ravel() * f  # pixels
        Rc = Rotation.from_rotvec(cams[:, :3])
        r_rot = (Rc * prior_R.inv()).as_rotvec().ravel() / np.radians(sig_deg)
        r_c = (-Rc.inv().apply(cams[:, 3:]) - prior_C).ravel() / (sig_mm / 1000)
        return np.concatenate([r_img, r_rot, r_c])

    A = lil_matrix((2 * m + 6 * n, 6 * n + 3 * len(pts)), dtype=int)
    o = np.arange(m)
    for s in range(6):
        A[2 * o, 6 * cam_i + s] = 1; A[2 * o + 1, 6 * cam_i + s] = 1
    for s in range(3):
        A[2 * o, 6 * n + 3 * pt_i + s] = 1; A[2 * o + 1, 6 * n + 3 * pt_i + s] = 1
    for v in range(n):
        A[2 * m + 3 * v:2 * m + 3 * v + 3, 6 * v:6 * v + 6] = 1
        A[2 * m + 3 * n + 3 * v:2 * m + 3 * n + 3 * v + 3, 6 * v:6 * v + 6] = 1
    x0 = np.concatenate([np.concatenate([r, t]) for r, t in rts] + [pts.ravel()])
    xs = np.concatenate([np.tile([0.01] * 3 + [0.002] * 3, n), np.full(3 * len(pts), 0.002)])  # rad, m
    sol = least_squares(resid, x0, jac_sparsity=A, loss=LOSS, f_scale=FS, x_scale=xs, max_nfev=NFEV)
    print("  BA:", sol.status, sol.nfev, sol.message, round(sol.cost, 1), flush=True)
    cams = sol.x[:6 * n].reshape(n, 6)
    r_img = resid(sol.x)[:2 * m].reshape(-1, 2)
    return [(c[:3], c[3:]) for c in cams], {"points": len(pts), "obs": m,
                                             "rms_px": round(float(np.sqrt(np.mean(np.sum(r_img ** 2, 1)))), 2)}


def sweep_metrics(name, gray8, rts, K, dist, heights, ref=None):
    frames = [g.astype(np.float32) / 255 for g in gray8]
    t0 = time.time()
    h, conf = ht.sweep(frames, to_poses(rts), K, dist, heights)
    good = conf > 0.5
    out = {"sweep_s": round(time.time() - t0, 1), "confident": int(good.sum())}
    if name == "coins":
        _, coins = ht.find_coins(h, conf)
        out["coins"] = [round(c["height_mm"], 2) for c in coins]
        out["stack_minus_single"] = round(coins[-1]["height_mm"] - coins[0]["height_mm"], 2) if len(coins) >= 2 else None
    else:
        raised = h[good & (h > 3)]
        top = float(np.median(raised)) if raised.size > 500 else float("nan")
        out["top_minus_board"] = round(top - float(np.median(h[good & (h < 3)])), 2)
    if ref is not None:
        both = good & ref[1]
        d = h[both] - ref[0][both]
        d = d - np.median(d)  # relative heights only: the arm sets the absolute plane
        out["vs_board_med_abs_mm"] = round(float(np.median(np.abs(d))), 3)
        out["vs_board_within_0.5mm"] = round(float(np.mean(np.abs(d) < 0.5)), 3)
    return out, (h, good)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "coins"
    gray8, poses, K, dist, heights = load(name)
    f = float(K[0, 0])
    board = to_rt(poses)
    t0 = time.time()
    tr = {mask: tracks(gray8, K, dist, mask) for mask in (True, False)}
    t_feat = round(time.time() - t0, 1)
    print(f"features+matching, both variants: {t_feat} s; tracks masked={len(tr[True])}, kept={len(tr[False])}", flush=True)
    configs = [("board", board, {})]
    for mm, deg in ((1, 0.5), (2, 1.0)):
        noisy = corrupt(board, mm, deg, seed=1)
        configs.append((f"noisy {mm}mm/{deg}deg", noisy, {}))
        for mask in (True, False):
            t1 = time.time()
            rts, info = refine(noisy, tr[mask], f, mm, deg)
            info["ba_s"] = round(time.time() - t1, 1)
            configs.append((f"refined {mm}mm/{deg}deg, markers {'masked' if mask else 'kept'}", rts, info))
    results, ref_map = {"_feature_matching_s_both": t_feat}, None
    for label, rts, info in configs:
        dc, dr = pose_err(rts, board)
        m, hm = sweep_metrics(name, gray8, rts, K, dist, heights, ref_map)
        ref_map = ref_map or hm
        results[label] = {"pose_err_mm": round(dc, 2), "pose_err_deg": round(dr, 3), **info, **m}
        print(label, json.dumps(results[label]), flush=True)
    json.dump(results, open(os.path.join(HERE, f"results_{name}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
