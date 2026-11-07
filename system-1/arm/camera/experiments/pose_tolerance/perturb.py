"""How much camera-pose error the plane sweep tolerates.

Run from system-1/arm/camera/ with PYTHONPATH=. :  python experiments/pose_tolerance/perturb.py coins|remote [seeds]
Each view's pose is perturbed in the board frame: the camera centre moves by up to +-T mm per axis (uniform), and the
camera turns about its own centre by an angle uniform in +-A deg about a random axis.
'random' draws a fresh error per view; 'common' applies one error to every view (like a base or calibration offset).
"""
import json, os, sys, time
import cv2
import numpy as np
import camera_test as ct
import height_test as ht
import scan_test as st

HERE = os.path.dirname(os.path.abspath(__file__))


def rot(axis_angle):
    return cv2.Rodrigues(np.asarray(axis_angle, float))[0]


def perturb(poses, t_mm, a_deg, mode, rng):
    out = []
    common = None
    for p in poses:
        if common is None or mode == "random":
            dc = rng.uniform(-t_mm, t_mm, 3) / 1000
            ax = rng.normal(size=3); ax /= np.linalg.norm(ax)
            dR = rot(ax * np.radians(rng.uniform(-a_deg, a_deg)))
            common = (dc, dR)
        dc, dR = common
        R, t = rot(p["rvec"]), np.array(p["tvec"])
        C = -R.T @ t                     # camera centre, board frame
        R2 = dR @ R                      # turn the camera about its own centre (camera frame)
        t2 = -R2 @ (C + dc)
        q = dict(p); q["rvec"] = cv2.Rodrigues(R2)[0].ravel().tolist(); q["tvec"] = t2.tolist()
        out.append(q)
    return out


def coins_result(height, conf):
    base, coins = ht.find_coins(height, conf)
    hs = [c["height_mm"] for c in coins]
    return {"coins": hs, "diff": (hs[-1] - hs[0]) if len(hs) >= 2 else float("nan"), "n_conf": int((conf > 0.5).sum())}


ROWS = [(0, 0)] + [(t, 0) for t in (0.25, 0.5, 1, 2)] + [(0, a) for a in (0.1, 0.25, 0.5, 1)] + \
       [(0.25, 0.1), (0.5, 0.25), (1, 0.5), (2, 1)]


def main():
    which = sys.argv[1]
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if which == "coins":
        d = os.path.join(ct.OUT, "height")
        c = json.load(open(os.path.join(ct.OUT, "calib_720p_before_refocus", "calib.json")))
        K, dist, heights = np.array(c["K"], float), np.array(c["dist"]), ht.HEIGHTS
    else:
        d = os.path.join(ct.OUT, "scan_1080")
        K, dist = ct.load_calib(1920)
        heights = st.HEIGHTS
    poses = json.load(open(os.path.join(d, "poses.json")))
    frames = [cv2.cvtColor(cv2.imread(os.path.join(d, p["file"])), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for p in poses]
    if which == "coins" and c["size"][0] != frames[0].shape[1]:
        sys.exit("calib size mismatch")
    h0, c0 = ht.sweep(frames, poses, K, dist, heights)
    good0 = c0 > 0.5
    results = []
    for mode in ("random", "common"):
        for t_mm, a_deg in ROWS:
            if (t_mm, a_deg) == (0, 0) and mode == "common":
                continue
            for s in range(seeds if (t_mm, a_deg) != (0, 0) else 1):
                rng = np.random.default_rng(1000 * s + 7)
                pp = perturb(poses, t_mm, a_deg, mode, rng) if (t_mm, a_deg) != (0, 0) else poses
                t0 = time.time()
                h, cf = (h0, c0) if (t_mm, a_deg) == (0, 0) else ht.sweep(frames, pp, K, dist, heights)
                r = {"mode": mode, "t_mm": t_mm, "a_deg": a_deg, "seed": s}
                if which == "coins":
                    r.update(coins_result(h, cf))
                else:
                    both = good0 & (cf > 0.5)
                    dh = np.abs(h[good0] - h0[good0])
                    # also with the best-fit plane removed: a common error mostly tilts/shifts the whole map
                    ys, xs = np.nonzero(good0)
                    A = np.c_[xs, ys, np.ones_like(xs)].astype(float)
                    res = (h - h0)[good0]
                    fit = A @ np.linalg.lstsq(A, res, rcond=None)[0]
                    r.update({"med": float(np.median(dh)), "p95": float(np.percentile(dh, 95)),
                              "p95_detilt": float(np.percentile(np.abs(res - fit), 95)),
                              "n_conf": int((cf > 0.5).sum()), "n_conf_both": int(both.sum())})
                print(json.dumps(r), f"{time.time() - t0:.0f}s", flush=True)
                results.append(r)
    json.dump(results, open(os.path.join(HERE, f"results_{which}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
