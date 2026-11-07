"""Coin heights when each view's pose comes from only a few ArUco markers near the coins (a small sticker), not the board.

Run from system-1/arm/camera/ with PYTHONPATH=. :  python experiments/pose_tolerance/small_marker.py
"""
import json, os
import cv2
import numpy as np
import camera_test as ct
import height_test as ht

HERE = os.path.dirname(os.path.abspath(__file__))
d = os.path.join(ct.OUT, "height")
c = json.load(open(os.path.join(ct.OUT, "calib_720p_before_refocus", "calib.json")))
K, dist = np.array(c["K"], float), np.array(c["dist"])
poses = json.load(open(os.path.join(d, "poses.json")))
frames = [cv2.cvtColor(cv2.imread(os.path.join(d, p["file"])), cv2.COLOR_BGR2GRAY) for p in poses]
f32 = [f.astype(np.float32) / 255 for f in frames]

h0, c0 = ht.sweep(f32, poses, K, dist)
base, coins = ht.find_coins(h0, c0)
mid = np.mean([cc["centre_mm"] for cc in coins], axis=0) / 1000  # board metres, between the coins
print("full board:", [round(cc["height_mm"], 2) for cc in coins], "coin centres mm", [cc["centre_mm"] for cc in coins])

obj_pts = {int(i): np.array(o, float).reshape(4, 3) for i, o in zip(ct.BOARD.getIds(), ct.BOARD.getObjPoints())}
det = [ct.DETECTOR.detectBoard(f) for f in frames]
markers = []  # per view: {id: 4x2 image corners}
for _, _, mc, mi in det:
    markers.append({int(i): m.reshape(4, 2) for i, m in zip(mi.ravel(), mc)} if mi is not None else {})
seen_all = set.intersection(*[set(m) for m in markers])
# markers seen in every view, nearest to the coins first
order = sorted(seen_all, key=lambda i: np.linalg.norm(obj_pts[i].mean(0)[:2] - mid))
print(f"{len(seen_all)} markers seen in all {len(frames)} views; nearest to the coins:",
      [(i, np.round(obj_pts[i].mean(0)[:2] * 1000).tolist()) for i in order[:4]])

results = []
for n in (1, 2, 4, 5):
    ids = order[:n]
    new, rot_err, pos_err = [], [], []
    for p, m in zip(poses, markers):
        op = np.concatenate([obj_pts[i] for i in ids]).astype(np.float32)
        ip = np.concatenate([m[i] for i in ids]).astype(np.float32)
        flag = cv2.SOLVEPNP_IPPE if n == 1 else cv2.SOLVEPNP_ITERATIVE
        ok, rv, tv = cv2.solvePnP(op, ip, K, dist, flags=flag)
        R, R0 = cv2.Rodrigues(rv)[0], cv2.Rodrigues(np.array(p["rvec"]))[0]
        rot_err.append(np.degrees(np.linalg.norm(cv2.Rodrigues(R @ R0.T)[0])))
        pos_err.append(1000 * np.linalg.norm(-R.T @ tv.ravel() + R0.T @ np.array(p["tvec"])))
        q = dict(p); q["rvec"] = rv.ravel().tolist(); q["tvec"] = tv.ravel().tolist()
        new.append(q)
    h, cf = ht.sweep(f32, new, K, dist)
    b, cs = ht.find_coins(h, cf)
    hs = [cc["height_mm"] for cc in cs]
    r = {"markers": n, "ids": ids, "coins": hs, "diff": hs[-1] - hs[0] if len(hs) >= 2 else None,
         "n_conf": int((cf > 0.5).sum()), "rot_err_deg_median": float(np.median(rot_err)), "rot_err_deg_max": float(np.max(rot_err)),
         "pos_err_mm_median": float(np.median(pos_err)), "pos_err_mm_max": float(np.max(pos_err))}
    print(json.dumps(r), flush=True)
    results.append(r)
json.dump(results, open(os.path.join(HERE, "results_small_marker.json"), "w"), indent=1)
