"""Can the pipeline correct arm-sized camera pose errors on a real object? Uses photos from scan_test.py capture.

    python pose_test.py                     # camera_out/scan, 1 deg and 3 mm of error per photo
    python pose_test.py --dir scan_1080 --error 2,5

The board gives each photo's true pose. Each pose gets a random error the size the arm's joint readings might
have, then rgbperceive.adjust (the pipeline's own bundle adjustment on the object's features, the believed
poses as a prior) corrects it. The board is out of play: only features within 20 mm of the object's top plane
count. Heights from the corrected poses are compared with heights from the board's poses, on the object. A
plain object gives too few features, and adjust then keeps the erroneous poses.
"""
import json
import os
import sys

import cv2
import numpy as np

import height_test as ht
import scan_test as st

ct = ht.ct
import features  # noqa: E402  system-1/core, on the path through scan_test
import rgbperceive  # noqa: E402
import rig  # noqa: E402

ERR = [float(x) for x in (sys.argv[sys.argv.index("--error") + 1] if "--error" in sys.argv else "1,3").split(",")]


def to_T(p):
    """Board-to-camera rvec/tvec as a camera pose in the board frame (OpenCV axes), as the pipeline takes it."""
    R = cv2.Rodrigues(np.array(p["rvec"]))[0]
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R.T, -R.T @ np.array(p["tvec"])
    return T


def from_T(T, p):
    R = T[:3, :3].T
    return {**p, "rvec": cv2.Rodrigues(R)[0].ravel().tolist(), "tvec": (-R @ T[:3, 3]).tolist()}


def perturb(poses, deg, mm, rng):
    out = []
    for p in poses:
        dR = cv2.Rodrigues(rng.normal(0, np.radians(deg) / np.sqrt(3), 3))[0]
        R = dR @ cv2.Rodrigues(np.array(p["rvec"]))[0]
        out.append({**p, "rvec": cv2.Rodrigues(R)[0].ravel().tolist(),
                    "tvec": (np.array(p["tvec"]) + rng.normal(0, mm / 1000 / np.sqrt(3), 3)).tolist()})
    return out


def main():
    poses = json.load(open(os.path.join(ht.DIR, "poses.json")))
    bgr = [cv2.imread(os.path.join(ht.DIR, p["file"])) for p in poses]
    K, dist = ct.load_calib(bgr[0].shape[1])
    gray = [cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for b in bgr]
    h0, c0 = ht.sweep(gray, poses, K, dist, st.HEIGHTS)
    good = c0 > 0.5
    top = float(np.median(h0[good & (h0 > 3)]))
    obj = cv2.morphologyEx((good & (h0 > top - 6)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(obj)
    obj = cv2.erode((lab == 1 + np.argmax(stats[1:, 4])).astype(np.uint8), np.ones((33, 33), np.uint8)).astype(bool)
    print(f"board poses: object top at {top:.1f} mm, {int(obj.sum() * ht.MM_PX ** 2)} mm2 of it to compare")
    # the object's top as the survey gives it: a plane frame facing the cameras (board z points down) and its extent
    xy = np.argwhere(obj)[:, ::-1] * ht.MM_PX / 1000
    Tp = features.frame(np.r_[xy.mean(0), -top / 1000], np.array([0, 0, -1.0]), np.array([1.0, 0, 0]))
    uv = (np.c_[xy, np.full(len(xy), -top / 1000)] - Tp[:3, 3]) @ Tp[:3, :2]
    survey = dict(panel=Tp, extent=(uv[:, 0].min(), uv[:, 0].max(), uv[:, 1].min(), uv[:, 1].max()))
    und = [cv2.undistort(b, K, dist) for b in bgr]  # the pipeline takes pinhole frames that claim K

    def compare(ps):
        h, c = ht.sweep(gray, ps, K, dist, st.HEIGHTS)
        g = obj & good & (c > 0.5)
        e = (h - h0)[g]
        A = np.c_[np.argwhere(g), np.ones(g.sum())]
        e = np.abs(e - A @ np.linalg.lstsq(A, e, rcond=None)[0])  # a tilt of the whole scene doesn't matter here
        return f"{(obj & (c > 0.5)).sum() / obj.sum():.0%} of the object confident, off by median {np.median(e):.2f} mm, " \
               f"{np.mean(e > 1):.1%} over 1 mm"

    bel = perturb(poses, *ERR, np.random.default_rng(0))
    caps = [rgbperceive.Capture(rig.Frame(im, None, K, to_T(p), 0.0, "wrist"), i, False) for i, (im, p) in enumerate(zip(und, bel))]
    fixed, _, how = rgbperceive.adjust(caps, survey)
    print(f"{ERR[0]} deg, {ERR[1]} mm of error per photo")
    print(f"  before: {compare(bel)}")
    print(f"  {how}")
    print(f"  after:  {compare([from_T(T, p) for T, p in zip(fixed, bel)])}")


if __name__ == "__main__":
    main()
