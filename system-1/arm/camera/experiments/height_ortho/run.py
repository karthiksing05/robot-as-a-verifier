"""Does a height-aware straight-on picture beat the single-plane one? Run from system-1/arm/camera/ with PYTHONPATH=. :
    python experiments/height_ortho/run.py
(c) plane: scan_test.orthophoto at the top height. (a) per-pixel: each picture pixel projected at the smoothed height map.
(b) per-region: (c), then each SAM region re-rendered at its own median height and pasted back."""
import json
import os
import sys

sys.argv = [sys.argv[0], "--dir", "scan_1080"]
import cv2
import numpy as np
import torch

import scan_test as st

ht, ct = st.ht, st.ct
OUT = os.path.dirname(os.path.abspath(__file__))
MMP = st.ORTHO_MM_PX


def render(bgr, poses, K, dist, hgrid, region):
    """Median of the photos, each picture pixel projected at its own height hgrid (mm). Also returns the per-pixel
    spread across views (median absolute deviation of grey, 0-255)."""
    x0, y0, _, _ = region
    hh, ww = hgrid.shape
    xs, ys = np.meshgrid(x0 + np.arange(ww) * MMP, y0 + np.arange(hh) * MMP)
    P = np.c_[xs.ravel(), ys.ravel(), -hgrid.ravel()].astype(np.float64) / 1000
    stack = []
    for f, p in zip(bgr, poses):
        uv = cv2.projectPoints(P, np.array(p["rvec"]), np.array(p["tvec"]), K, dist)[0].reshape(hh, ww, 2).astype(np.float32)
        w = cv2.remap(f, uv[..., 0], uv[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        ok = (uv[..., 0] >= 1) & (uv[..., 1] >= 1) & (uv[..., 0] < f.shape[1] - 2) & (uv[..., 1] < f.shape[0] - 2)
        w = w.astype(np.float32)
        w[~ok] = np.nan
        stack.append(w)
    s = torch.from_numpy(np.stack(stack)).to(ht.DEV)
    del stack
    med = s.nanmedian(0).values
    g = s @ torch.tensor([0.114, 0.587, 0.299], device=s.device)
    spread = (g - g.nanmedian(0, keepdim=True).values).abs().nanmedian(0).values
    out = np.nan_to_num(med.cpu().numpy(), nan=0).astype(np.uint8), spread.cpu().numpy()
    del s, g, med
    torch.cuda.empty_cache()
    return out


def sharpness(img, mask):
    """Mean gradient energy over the strongest 5% of edges (labels, key borders), and Laplacian variance."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gm = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))[mask]
    lap = cv2.Laplacian(g, cv2.CV_32F)[mask]
    return float(gm[gm >= np.percentile(gm, 95)].mean()), float(lap.var())


def main():
    poses = json.load(open(os.path.join(ht.DIR, "poses.json")))
    bgr = [cv2.imread(os.path.join(ht.DIR, p["file"])) for p in poses]
    K, dist = ct.load_calib(bgr[0].shape[1])
    d = np.load(os.path.join(ht.DIR, "scan_sweep.npz"))
    height, conf = d["height"], d["conf"]
    good = conf > 0.5
    top = float(np.median(height[good & (height > 3)]))
    # the object and region, as scan_test.cmd_scan finds them
    obj = (good & (height > max(top - 6, 1.0))).astype(np.uint8)
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, lab, sts, _ = cv2.connectedComponentsWithStats(obj)
    obj = lab == 1 + int(np.argmax(sts[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(obj)
    m = int(3 / ht.MM_PX)
    c0, r0 = max(xs.min() - m, 0), max(ys.min() - m, 0)
    c1, r1 = min(xs.max() + m, obj.shape[1] - 1), min(ys.max() + m, obj.shape[0] - 1)
    region = (c0 * ht.MM_PX, r0 * ht.MM_PX, (c1 + 1) * ht.MM_PX, (r1 + 1) * ht.MM_PX)
    size = (int((region[2] - region[0]) / MMP), int((region[3] - region[1]) / MMP))
    print(f"top {top:.2f} mm, region {region}, picture {size}")

    # smoothed, hole-filled height map: unconfident cells filled by normalised convolution, then a median filter;
    # off the object, the top height (that area is greyed out anyway)
    hm = np.where(good & obj, height, 0).astype(np.float32)
    wgt = (good & obj).astype(np.float32)
    filled = hm.copy()
    for k in (9, 21, 61):
        num, den = cv2.GaussianBlur(hm, (k, k), 0), cv2.GaussianBlur(wgt, (k, k), 0)
        fill = (filled == 0) & (den > 1e-3)
        filled[fill & (wgt == 0)] = (num / np.maximum(den, 1e-6))[fill & (wgt == 0)]
    filled = np.where(obj, filled, top)
    filled = np.clip(filled, top - 6, top + 4)
    filled = cv2.medianBlur(filled.astype(np.float32), 5)
    crop = filled[r0:r1 + 1, c0:c1 + 1]
    hgrid = cv2.resize(crop, size, interpolation=cv2.INTER_LINEAR)
    cv2.imwrite(os.path.join(OUT, "height_used.png"), cv2.applyColorMap(
        np.clip((hgrid - (top - 6)) / 10 * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO))

    inside = cv2.resize(obj[r0:r1 + 1, c0:c1 + 1].astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
    inside = cv2.dilate(inside, np.ones((15, 15), np.uint8)).astype(bool)
    core = cv2.erode(inside.astype(np.uint8), np.ones((61, 61), np.uint8)).astype(bool)  # metrics away from the rim

    pics, spreads = {}, {}
    pics["c_plane"], spreads["c_plane"] = render(bgr, poses, K, dist, np.full(size[::-1], top, np.float32), region)
    ref = st.orthophoto(bgr, poses, K, dist, top, region, MMP)
    print("plane render vs scan_test.orthophoto, mean abs diff:", float(np.abs(ref.astype(int) - pics["c_plane"]).mean()))
    pics["a_perpixel"], spreads["a_perpixel"] = render(bgr, poses, K, dist, hgrid, region)

    st.load_models()
    results = {}

    def downstream(name, img):
        img = img.copy()
        img[~inside] = 128
        masks = st.part_masks(img, MMP)
        grids = []
        for mk in masks:
            gr = np.zeros_like(obj)
            gr[r0:r1 + 1, c0:c1 + 1] = cv2.resize(mk.astype(np.uint8), (c1 - c0 + 1, r1 - r0 + 1), interpolation=cv2.INTER_NEAREST) > 0
            grids.append(gr)
        others = cv2.dilate(np.any(grids, axis=0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) if grids else np.zeros_like(obj)
        obj_wide = cv2.dilate(obj.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (height > top - 8)
        parts = [(mk, gr, c) for mk, gr in zip(masks, grids) if (c := st.classify(gr, height, conf, others, obj_wide))]
        out = img.copy()
        col = {"button": (0, 220, 0), "rocker": (0, 160, 255), "flat print": (150, 150, 150)}
        for mk, _, c in parts:
            cn, _ = cv2.findContours(mk.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(out, cn, -1, col[c["kind"]], 3 if c["kind"] != "flat print" else 1)
        cv2.imwrite(os.path.join(OUT, f"map_{name}.jpg"), out)
        keys = [c for _, _, c in parts if c["kind"] != "flat print"]
        results[name] = {"regions": len(masks), "classified": len(parts), "keys": len(keys),
                         "buttons": sum(c["kind"] == "button" for c in keys), "rockers": sum(c["kind"] == "rocker" for c in keys),
                         "key_rise_mm": sorted(round(c["rise_mm"], 2) for c in keys)}
        print(name, results[name])
        return masks, parts

    masks_c, parts_c = downstream("c_plane", pics["c_plane"])
    downstream("a_perpixel", pics["a_perpixel"])

    # (b): each region from the plane pass re-rendered at its own median height, pasted inside its dilated outline
    comp, comp_spread = pics["c_plane"].copy(), spreads["c_plane"].copy()
    hfull = cv2.resize(height[r0:r1 + 1, c0:c1 + 1], size, interpolation=cv2.INTER_NEAREST)
    gfull = cv2.resize(good[r0:r1 + 1, c0:c1 + 1].astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
    shifts = []
    for mk in sorted(masks_c, key=lambda x: -x.sum()):  # big first, so small regions inside them win
        sel = mk & gfull
        if sel.sum() < 50:
            continue
        h = float(np.median(hfull[sel]))
        if abs(h - top) < 0.2:
            continue
        shifts.append(round(h - top, 2))
        yy, xx = np.nonzero(mk)
        pad = 20
        ya, yb, xa, xb = max(yy.min() - pad, 0), min(yy.max() + pad, size[1]), max(xx.min() - pad, 0), min(xx.max() + pad, size[0])
        sub_region = (region[0] + xa * MMP, region[1] + ya * MMP, 0, 0)
        im, sp = render(bgr, poses, K, dist, np.full((yb - ya, xb - xa), h, np.float32), sub_region)
        paste = cv2.dilate(mk.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)[ya:yb, xa:xb]
        comp[ya:yb, xa:xb][paste], comp_spread[ya:yb, xa:xb][paste] = im[paste], sp[paste]
    print("(b) regions re-rendered, height offsets from the top plane (mm):", sorted(shifts))
    pics["b_perregion"], spreads["b_perregion"] = comp, comp_spread
    downstream("b_perregion", comp)

    key_mask = np.zeros(size[::-1], bool)  # metrics also on the key regions of the plane pass, where it matters
    for mk, _, c in parts_c:
        if c["kind"] != "flat print":
            key_mask |= cv2.dilate(mk.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    for name, img in pics.items():
        cv2.imwrite(os.path.join(OUT, f"ortho_{name}.jpg"), img)
        gs, lv = sharpness(img, core)
        ks, _ = sharpness(img, key_mask & core) if (key_mask & core).any() else (float("nan"), 0)
        sp = spreads[name]
        results[name].update({"grad_top5": round(gs, 1), "lap_var": round(lv, 1), "grad_top5_keys": round(ks, 1),
                              "spread_mean": round(float(np.nanmean(sp[core])), 2),
                              "spread_keys": round(float(np.nanmean(sp[key_mask & core])), 2),
                              "spread_p90": round(float(np.nanpercentile(sp[core], 90)), 2)})
    # side-by-side crops: the three crops at a few key locations, plus spread maps
    crops = []
    centres = [tuple(np.argwhere(mk).mean(0).astype(int)) for mk, _, c in parts_c if c["kind"] != "flat print"][:: max(1, len(parts_c) // 6)][:6]
    for cy, cx in centres:
        row = []
        for name in ("c_plane", "a_perpixel", "b_perregion"):
            p = np.pad(pics[name], ((150, 150), (150, 150), (0, 0)))
            cr = p[cy:cy + 300, cx:cx + 300].copy()
            cv2.putText(cr, name, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            row.append(cr)
        crops.append(np.hstack(row))
    if crops:
        cv2.imwrite(os.path.join(OUT, "crops_side_by_side.jpg"), np.vstack(crops))
    sv = [cv2.applyColorMap(np.clip(np.nan_to_num(spreads[n]) * 6, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
          for n in ("c_plane", "a_perpixel", "b_perregion")]
    cv2.imwrite(os.path.join(OUT, "spread_c_a_b.jpg"), cv2.resize(np.hstack(sv), None, fx=0.5, fy=0.5))
    json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "key_rise_mm"} for k, v in results.items()}, indent=1))


if __name__ == "__main__":
    main()
