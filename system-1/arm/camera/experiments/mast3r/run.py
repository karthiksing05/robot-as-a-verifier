"""MASt3R poses from the photos alone, compared with the ChArUco board poses, then fed to our plane sweep.

    .venv/Scripts/python.exe run.py height 10      # coins, 720p
    .venv/Scripts/python.exe run.py scan_1080 10   # TV remote, 1080p
"""
import json
import os
import sys
import time

import cv2
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [HW, os.path.join(HERE, "mast3r")]
import height_test as ht  # noqa: E402
import camera_test as ct  # noqa: E402
from mast3r.model import AsymmetricMASt3R  # noqa: E402
from mast3r.cloud_opt.sparse_ga import sparse_global_alignment  # noqa: E402
from dust3r.image_pairs import make_pairs  # noqa: E402
from dust3r.utils.image import load_images  # noqa: E402

name, n = sys.argv[1], int(sys.argv[2])
src = os.path.join(ct.OUT, name)
out = os.path.join(HERE, "out", name)
os.makedirs(out, exist_ok=True)
poses = json.load(open(os.path.join(src, "poses.json")))
sel = [poses[i] for i in np.linspace(0, len(poses) - 1, n).round().astype(int)]
gray = [cv2.imread(os.path.join(src, p["file"])) for p in sel]
W = gray[0].shape[1]
if name == "height":
    c = json.load(open(os.path.join(ct.OUT, "calib_720p_before_refocus", "calib.json")))
    K, dist = ct.scaled(c["K"], W, c["size"][0]), np.array(c["dist"])
else:
    K, dist = ct.load_calib(W)

# MASt3R assumes a pinhole camera, so give it straightened photos (same K, distortion removed)
files = []
for p, im in zip(sel, gray):
    f = os.path.join(out, "u_" + p["file"])
    cv2.imwrite(f, cv2.undistort(im, K, dist))
    files.append(f)

t0 = time.time()
ckpt = os.path.join(HERE, "hf", "hub", "models--naver--MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric", "snapshots")
ckpt = os.path.join(ckpt, os.listdir(ckpt)[0])
model = AsymmetricMASt3R.from_pretrained(ckpt).to("cuda").eval()
t_load = time.time() - t0
imgs = load_images(files, size=512, verbose=False)
pairs = make_pairs(imgs, scene_graph="complete", prefilter=None, symmetrize=True)
scene = sparse_global_alignment(files, pairs, os.path.join(out, "cache"), model, lr1=0.07, niter1=300, lr2=0.014,
                                niter2=300, device="cuda", opt_depth=True, shared_intrinsics=True, matching_conf_thr=5.0)
t_run = time.time() - t0 - t_load
print(f"load {t_load:.0f} s, MASt3R {t_run:.0f} s, peak VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GB")

c2w = scene.get_im_poses().detach().cpu().numpy()
focal512 = float(scene.get_focals()[0])
print(f"focal: MASt3R {focal512 * W / 512:.0f} px vs calibrated {K[0, 0]:.0f} px (at {W} px wide)")

# board poses: x_cam = R x_board + t, so the camera centre is -R^T t and camera-to-board rotation is R^T
Rb = [cv2.Rodrigues(np.array(p["rvec"]))[0] for p in sel]
Cb = np.array([-R.T @ np.array(p["tvec"]) for R, p in zip(Rb, sel)])
Cm = c2w[:, :3, 3]

# Umeyama: board = s A mast + b, fitted on camera centres
mm, mb = Cm.mean(0), Cb.mean(0)
U, S, Vt = np.linalg.svd((Cb - mb).T @ (Cm - mm) / n)
D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
A = U @ D @ Vt
s = np.trace(np.diag(S) @ D) / ((Cm - mm) ** 2).sum(1).mean()
b = mb - s * A @ mm

rows, new = [], []
for i, p in enumerate(sel):
    Rc2b = A @ c2w[i, :3, :3]
    C = s * A @ Cm[i] + b
    dR = Rc2b @ Rb[i]  # (board's cam-to-board)^-1 composed: identity if they agree
    ang = np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))
    rows.append((p["file"], ang, 1000 * np.linalg.norm(C - Cb[i])))
    R = Rc2b.T
    new.append({"file": p["file"], "rvec": cv2.Rodrigues(R)[0].ravel().tolist(), "tvec": (-R @ C).tolist()})
spread = 1000 * np.linalg.norm(Cb - mb, axis=1).mean()
print(f"scale {s:.4f} (MASt3R units -> m; its 'metric' output would make this ~1); camera spread {spread:.0f} mm")
print("view          rot err (deg)  centre err (mm)")
for f, a, d in rows:
    print(f"{f:14s} {a:8.2f}  {d:10.2f}")
r = np.array([[a, d] for _, a, d in rows])
print(f"mean           {r[:, 0].mean():8.2f}  {r[:, 1].mean():10.2f}   (max {r[:, 0].max():.2f} deg, {r[:, 1].max():.2f} mm)")
json.dump(new, open(os.path.join(out, "mast3r_poses.json"), "w"), indent=1)

# our sweep on the same views: board poses vs MASt3R poses
frames = [cv2.cvtColor(g, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for g in gray]
del model
torch.cuda.empty_cache()
for label, P in (("board", sel), ("mast3r", new)):
    h, conf = ht.sweep(frames, P, K, dist)
    np.save(os.path.join(out, f"sweep_{label}.npy"), h)
    vis = cv2.applyColorMap(np.clip((h + 1) / 10 * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    vis[conf <= 0.5] = (vis[conf <= 0.5] * 0.25).astype(np.uint8)
    cv2.imwrite(os.path.join(out, f"sweep_{label}.png"), vis)
    if name == "height":
        base, coins = ht.find_coins(h, conf)
        txt = ", ".join(f"{c['height_mm']:.2f} (d {c['diameter_mm']:.0f})" for c in coins)
        diff = f"; stack-single {coins[-1]['height_mm'] - coins[0]['height_mm']:.2f} mm" if len(coins) >= 2 else ""
        print(f"sweep with {label} poses: confident {100 * (conf > 0.5).mean():.0f}% of cells; coins {txt}{diff}")
    else:
        g = conf > 0.5
        print(f"sweep with {label} poses: confident {100 * g.mean():.0f}% of cells, heights p5/p50/p95 "
              f"{np.percentile(h[g], [5, 50, 95]).round(2).tolist()} mm")

# MASt3R's own dense depth, view 0, put in the board frame: height above the board = -z
pts, depths, confs = scene.get_dense_pts3d(clean_depth=True)
H0, W0 = confs[0].shape
P0 = pts[0].detach().cpu().numpy().reshape(-1, 3)
hb = -((s * (A @ P0.T)).T + b)[:, 2].reshape(H0, W0) * 1000
cf = confs[0].detach().cpu().numpy()
np.save(os.path.join(out, "mast3r_height_view0.npy"), hb)
good = cf > 1.5
print(f"MASt3R dense height above board, view 0 ({W0}x{H0}, {100 * good.mean():.0f}% conf>1.5): "
      f"p5/p50/p95 {np.percentile(hb[good], [5, 50, 95]).round(2).tolist()} mm")
vis = cv2.applyColorMap(np.clip((hb + 2) / 22 * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
vis[~good] = (vis[~good] * 0.25).astype(np.uint8)
cv2.imwrite(os.path.join(out, "mast3r_height_view0.png"),
            np.hstack([cv2.resize(cv2.imread(files[0]), (W0, H0)), vis]))
