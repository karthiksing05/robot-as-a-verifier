"""Bench test of the Innomaker U20CAM-1080P wrist camera against the sim's assumptions (system-1/sim/sensors.py, USB_*).
Windows only (DirectShow through ffmpeg). Run with the repo's environment, `uv sync --extra sim`:

    python camera_test.py info     # modes, real frame rate, MJPEG quality, which controls exist
    python camera_test.py crop     # is 1280x720 the whole view scaled down, or a crop of 1920x1080?
    python camera_test.py calib    # ChArUco on the tablet, guided by a live coverage preview: lens, centre, distortion
    python camera_test.py report   # plots of the calibration: coverage, errors, distortion against the sim, uncertainty
    python camera_test.py focus    # same board, camera moved from far to near: blur against distance
    python camera_test.py noise    # camera propped still facing grey bars on the laptop screen: noise against brightness
    python camera_test.py exposure auto   # or `exposure -4`: auto, or a fixed 2^N s exposure
    python camera_test.py snap     # live preview; space saves a frame (a TV remote, a thermostat), q quits
    python camera_test.py seg      # OWLv2 boxes and SAM outlines on the saved snaps

The board is shown on a Samsung Galaxy Tab S9 FE (`--target tab`, the default; its image is calib_board_tab_s9fe.png)
or on this laptop's screen (`--target laptop`). Frames come through ffmpeg by camera name: the module's own MJPEG at
30 fps. Results go to camera_out/ next to this file.
"""
import ctypes
import glob
import json
import math
import os
import re
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "camera_out")
CORE = os.path.join(HERE, "..", "..", "core")  # segmodels.py, the robot's image models
# where the board is shown: screen pixels, mm per pixel, squares
TARGETS = {
    "tab": dict(px=(2304, 1440), mm_per_px=10.9 * 25.4 / math.hypot(2304, 1440), squares=(9, 6)),  # 10.9" 2304x1440
    "laptop": dict(px=(2048, 1280), mm_per_px=345 / 2048, squares=(11, 7)),  # Lenovo IdeaPad Pro 5 16IMH9
}
TARGET = next((a.split("=")[1] for a in sys.argv if a.startswith("--target=")), "tab")
T = TARGETS[TARGET]
# the sim's values (system-1/sim/sensors.py)
SIM_K = np.array([[621.096, 0, 650.034], [0, 621.117, 355.169], [0, 0, 1]])
SIM_DIST = np.array([-0.1829, 0.05501, 1.204e-05, 1.301e-05, -0.009697])
SIM_FOCUS_MM, SIM_F_MM, SIM_FNUM, SIM_PX_MM, SIM_SOFT_PX = 120.0, 2.8, 2.3, 0.0045, 0.6
SIM_WHITE_E, SIM_READ_E, SIM_JPEG_Q = 11000, 4.0, 80
SIZE = (1280, 720) if "--720" in sys.argv else (1920, 1080)  # 720p is the same view scaled down (the crop check)
METRIC_FLOOR_PX = 0.75  # blur_sigma reads a perfect edge as ~0.75 px (Sobel and pixel sampling); found on blurred boards

os.makedirs(OUT, exist_ok=True)
sys.path[:0] = [CORE, os.path.join(HERE, "..", "..", "hardware")]
from real_wrist import FFMPEG, Capture, find_camera, load_calib  # noqa: E402  the driver the pipeline uses


def Cam(size=SIZE):
    return Capture(size)


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # one image pixel = one screen pixel
except Exception:
    pass


def scaled(K, width, from_width):
    """A camera matrix for another of the camera's sizes: focal length and centre scale, distortion doesn't."""
    K = np.array(K, float)
    K[:2] *= width / from_width
    return K


def lock_controls(exposure=-6, wb=4600):
    """Fix exposure and white balance through DirectShow. UVC controls stay set on the device."""
    idx, _ = find_camera()
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25), cap.set(cv2.CAP_PROP_EXPOSURE, exposure), \
        cap.set(cv2.CAP_PROP_AUTO_WB, 0), cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb)
    cap.release()
    return all(ok)


def beep():
    try:
        import winsound
        winsound.Beep(1200, 80)
    except Exception:
        pass


# --- the board ---
DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
SQ = T["squares"]
SQ_PX = min((T["px"][0] - 80) // SQ[0], (T["px"][1] - 40) // SQ[1])
SQ_MM = SQ_PX * T["mm_per_px"]
BOARD = cv2.aruco.CharucoBoard(SQ, SQ_MM / 1000, 0.75 * SQ_MM / 1000, DICT)
DETECTOR = cv2.aruco.CharucoDetector(BOARD)


def board_canvas():
    img = BOARD.generateImage((SQ[0] * SQ_PX, SQ[1] * SQ_PX), marginSize=0, borderBits=1)
    canvas = np.full((T["px"][1], T["px"][0]), 255, np.uint8)
    y, x = (T["px"][1] - img.shape[0]) // 2, (T["px"][0] - img.shape[1]) // 2
    canvas[y:y + img.shape[0], x:x + img.shape[1]] = img
    return canvas


def show(img, fullscreen):
    cv2.namedWindow("screen", cv2.WINDOW_NORMAL)
    if fullscreen:
        cv2.setWindowProperty("screen", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.imshow("screen", img)


def detect(gray):
    corners, ids, _, _ = DETECTOR.detectBoard(gray)
    return (corners, ids) if ids is not None and len(ids) else (None, None)


def fov(K, dist, size):
    """True field of view through the lens (degrees): horizontal, vertical, diagonal."""
    w, h = size
    pts = np.array([[[0, h / 2]], [[w, h / 2]], [[w / 2, 0]], [[w / 2, h]], [[0, 0]], [[w, h]]], np.float64)
    n = cv2.undistortPoints(pts, K, dist).reshape(-1, 2)
    v = np.c_[n, np.ones(len(n))]
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    ang = lambda i, j: math.degrees(math.acos(np.clip(v[i] @ v[j], -1, 1)))
    return ang(0, 1), ang(2, 3), ang(4, 5)


def blur_sigma(gray, corners):
    """Gaussian-equivalent blur (px) at the board's saddle corners: edge contrast over the steepest gradient."""
    g = gray.astype(np.float32)
    mag = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) / 8, cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3) / 8)
    out = []
    for x, y in corners.reshape(-1, 2).astype(int):
        if 14 <= x < g.shape[1] - 14 and 14 <= y < g.shape[0] - 14:
            p, m = g[y - 12:y + 13, x - 12:x + 13], mag[y - 12:y + 13, x - 12:x + 13]
            c = np.percentile(p, 95) - np.percentile(p, 5)
            if c > 40:
                out.append(c / (math.sqrt(2 * math.pi) * np.percentile(m, 99)))
    if not out:
        return None
    m = float(np.median(out))
    return math.sqrt(max(m * m - METRIC_FLOOR_PX ** 2, 0.0))  # take out the measurement's own blur


def sim_sigma(d_mm, focus_mm=SIM_FOCUS_MM):
    c = SIM_F_MM ** 2 * abs(focus_mm - d_mm) / (SIM_FNUM * d_mm * (focus_mm - SIM_F_MM)) / SIM_PX_MM
    return math.hypot(c / 4, SIM_SOFT_PX)  # a disc of diameter c has a standard deviation of c/4


def jpeg_quality(data):
    """IJG quality whose standard luminance table best matches the frame's first quantization table."""
    std = np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
                    14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
                    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99])
    zz = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14,
          21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53,
          60, 61, 54, 47, 55, 62, 63]
    i = data.find(b"\xff\xdb")
    if i < 0:
        return None
    table = np.zeros(64, int)
    table[zz] = np.frombuffer(data[i + 5:i + 69], np.uint8).astype(int)
    return min(range(1, 101), key=lambda q: np.abs(
        np.clip((std * (5000 / q if q < 50 else 200 - 2 * q) + 50) // 100, 1, 255) - table).sum())


def cmd_info():
    idx, name = find_camera()
    print(f"Camera: '{name}' (DirectShow index {idx})")
    opts = subprocess.run([FFMPEG, "-hide_banner", "-list_options", "true", "-f", "dshow", "-i", f"video={name}"],
                          capture_output=True, text=True, errors="ignore").stderr
    for m in sorted({re.sub(r"\s+", " ", m.strip()) for m in
                     re.findall(r"(?:vcodec|pixel_format)=\S+\s+min s=\S+ fps=\S+ max s=\S+ fps=\S+", opts)}):
        print("  ", m)
    cam = Cam()
    _, n0 = cam.read()
    time.sleep(3)
    _, n1 = cam.read()
    q = jpeg_quality(cam.jpeg)
    cv2.imwrite(os.path.join(OUT, "info_frame.jpg"), cam.read()[0])
    cam.close()
    print(f"MJPEG {SIZE[0]}x{SIZE[1]} through ffmpeg: {(n1 - n0) / 3:.1f} fps, quality about {q} (the sim assumes 30 fps and {SIM_JPEG_Q})")


def cmd_crop():
    print("Aim the camera at a detailed scene (the room, a bookshelf) and keep it still for 10 s.")
    frames = {}
    for size in ((1280, 720), (1920, 1080)):
        cam = Cam(size)
        time.sleep(1.5)
        frames[size[1]] = cam.read()[0]
        cam.close()
        cv2.imwrite(os.path.join(OUT, f"view_{size[1]}.jpg"), frames[size[1]])
    sift = cv2.SIFT_create(3000)
    ka, da = sift.detectAndCompute(cv2.cvtColor(frames[720], cv2.COLOR_BGR2GRAY), None)
    kb, db = sift.detectAndCompute(cv2.cvtColor(frames[1080], cv2.COLOR_BGR2GRAY), None)
    if da is None or db is None or len(ka) < 30:
        sys.exit("Too little detail in view. Aim at something busier and rerun.")
    m = [p[0] for p in cv2.BFMatcher().knnMatch(da, db, k=2) if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    A, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3)
    s = float(np.hypot(A[0, 0], A[0, 1]))
    verdict = "the same view, scaled down" if abs(s - 1.5) < 0.05 else "a centre crop at full detail" if abs(s - 1.0) < 0.05 \
        else f"a {1.5 / s:.2f}x crop of the sensor"
    print(f"720p -> 1080p scale {s:.3f} ({int(inl.sum())}/{len(m)} matches agree): 1280x720 is {verdict}.")
    print("1.500 means 720p shows the whole 1080p view; 1.000 means 720p is a 1:1 centre crop.")


def coverage_overlay(view, hits):
    gh, gw = hits.shape
    h, w = view.shape[:2]
    over = view.copy()
    for j in range(gh):
        for i in range(gw):
            if hits[j, i]:
                cv2.rectangle(over, (i * w // gw, j * h // gh), ((i + 1) * w // gw, (j + 1) * h // gh), (0, 180, 0), -1)
    out = cv2.addWeighted(over, 0.35, view, 0.65, 0)
    for i in range(1, gw):
        cv2.line(out, (i * w // gw, 0), (i * w // gw, h), (200, 200, 200), 1)
    for j in range(1, gh):
        cv2.line(out, (0, j * h // gh), (w, j * h // gh), (200, 200, 200), 1)
    return out


CALIB_STILL_PX, CALIB_STILL_FRAMES = 1.5, 2  # steady: moving under 1.5 px (at 720p scale) for 2 frames in a row
K_GUESS = scaled([[825.0, 0, 640], [0, 825.0, 360], [0, 0, 1]], SIZE[0], 1280)  # first tablet run; only for telling poses apart


def board_pose(corners, ids):
    """(tilt left/right, tilt up/down, roll, distance mm) of the board, from a rough lens guess."""
    obj, img = BOARD.matchImagePoints(corners, ids)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K_GUESS, None)
    R = cv2.Rodrigues(rvec)[0]
    n = R[:, 2]  # the board's normal in the camera frame
    yaw, pitch = math.degrees(math.atan2(n[0], abs(n[2]))), math.degrees(math.atan2(n[1], abs(n[2])))
    roll = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return yaw, pitch, roll, float(np.linalg.norm(tvec)) * 1000


def cmd_calib():
    print(f"Show calib_board_tab_s9fe.png full screen on the tablet ({SQ[0]}x{SQ[1]} squares of {SQ_MM:.1f} mm)."
          if TARGET == "tab" else "The board goes full screen on this laptop.")
    print("Hold the camera 12-40 cm from the board and hold still for each beep. It captures a steady view that is new in "
          "any way: new grid cells, a new tilt (aim for 40-60 deg left, right, up and down), a new roll or a new distance. "
          "Space captures at the next steady moment even if the view isn't new; v captures right away, steady or not "
          "(click the preview window first so it gets the keys). Aim for 50+ views with the grid all green; q finishes (80 max).")
    if TARGET == "laptop":
        show(board_canvas(), True)
    cam = Cam()
    gw, gh = 16, 9
    fs = SIZE[0] / 1280  # text scale: the preview is shown at 1280 wide
    hits = np.zeros((gh, gw), bool)
    views, poses, prev, still, last_t, size = [], [], None, 0, 0.0, None
    space_at = v_at = 0.0  # space: capture at the next steady moment (5 s); v: capture the next frame with the board (1 s)
    while len(views) < 80:
        frame, _ = cam.read()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        corners, ids = detect(gray)
        status, force = "no board", False
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord(" "):
            space_at = time.time()
        if key == ord("v"):
            v_at = time.time()
        if corners is not None and len(ids) >= 12:
            c = corners.reshape(-1, 2)
            pts = dict(zip(ids.ravel().tolist(), c.tolist()))
            if prev is not None:
                common = [k for k in pts if k in prev]
                moved = np.median([np.hypot(*(np.subtract(pts[k], prev[k]))) for k in common]) if common else 99
                still = still + 1 if moved < CALIB_STILL_PX * SIZE[0] / 1280 else 0
            prev = pts
            cells = set(zip((c[:, 1] * gh / size[1]).astype(int).clip(0, gh - 1), (c[:, 0] * gw / size[0]).astype(int).clip(0, gw - 1)))
            new_cells = sum(not hits[j, i] for j, i in cells)
            yaw, pitch, roll, dist = board_pose(corners, ids)
            centre = c.mean(0) / size
            # new if no earlier view is close in tilt, roll, distance and place in the picture all at once
            far = all(abs(yaw - a) > 10 or abs(pitch - b) > 10 or abs(roll - r) > 20 or abs(math.log(dist / d)) > 0.2
                      or np.abs(centre - q).max() > 0.15 for a, b, r, d, q in poses)
            status = f"{len(ids)} corners, tilt {yaw:+.0f}/{pitch:+.0f} deg, {dist / 10:.0f} cm, {'steady' if still >= CALIB_STILL_FRAMES else 'hold still'}"
            force = time.time() - v_at < 1.0 or (time.time() - space_at < 5.0 and still >= CALIB_STILL_FRAMES)
            if force or (still >= CALIB_STILL_FRAMES and time.time() - last_t > 0.8 and (new_cells >= 2 or far)):
                views.append((corners, ids))
                poses.append((yaw, pitch, roll, dist, centre))
                for j, i in cells:
                    hits[j, i] = True
                last_t, still, space_at, v_at = time.time(), 0, 0.0, 0.0
                cv2.imwrite(os.path.join(OUT, f"calib_{TARGET}_{len(views):02d}.jpg"), frame)
                beep()
        else:
            prev, still = None, 0
        view = coverage_overlay(frame, hits)
        if corners is not None:
            for x, y in corners.reshape(-1, 2).astype(int):
                cv2.circle(view, (int(x), int(y)), 4, (0, 0, 255), -1)
        tilts = np.array([p[:2] for p in poses]) if poses else np.zeros((1, 2))
        cv2.putText(view, f"views {len(views)}  coverage {hits.mean():.0%}  tilts reached: left/right {tilts[:, 0].min():+.0f}..{tilts[:, 0].max():+.0f}"
                          f"  up/down {tilts[:, 1].min():+.0f}..{tilts[:, 1].max():+.0f} deg", (15, int(35 * fs)), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * fs, (0, 255, 255), 2)
        cv2.putText(view, status + ("   capture pending..." if time.time() - space_at < 5.0 else "") + "   (space: capture when steady, v: capture now, q: finish)", (15, int(65 * fs)), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * fs, (0, 255, 255), 2)
        cv2.imshow("camera", cv2.resize(view, (1280, 720)))
    cam.close()
    cv2.destroyAllWindows()
    if len(views) < 10:
        sys.exit(f"Only {len(views)} views: too few to calibrate.")
    np.savez(os.path.join(OUT, f"calib_{TARGET}_views.npz"), size=size, target=TARGET,
             corners=np.array([c for c, _ in views], dtype=object), ids=np.array([i for _, i in views], dtype=object))
    calibrate_and_print(views, size)


def calibrate(views, size, flags=cv2.CALIB_RATIONAL_MODEL):
    objs, imgs = zip(*[BOARD.matchImagePoints(c, i) for c, i in views])
    rms, K, dist, rv, tv = cv2.calibrateCamera(list(objs), list(imgs), size, None, None, flags=flags)
    return rms, K, dist.ravel(), objs, imgs, rv, tv


def calibrate_and_print(views, size):
    rms5, K5, d5, *_ = calibrate(views, size, 0)
    rms, K, dist, *_ = calibrate(views, size)
    json.dump({"K": K.tolist(), "dist": dist.tolist(), "rms_px": rms, "views": len(views), "size": list(size),
               "model": "opencv rational (k1-k6, p1, p2)", "target": TARGET},
              open(os.path.join(OUT, "calib.json"), "w"), indent=1)
    h, v, d = fov(K, dist, size)
    sh, sv, sd = fov(SIM_K, SIM_DIST, (1280, 720))
    sim_k = scaled(SIM_K, size[0], 1280)  # the sim's 720p lens at this size
    print(f"\n{len(views)} views. Reprojection error: {rms:.2f} px (rational model), {rms5:.2f} px (standard 5-coefficient)")
    print(f"{'':18s} {'measured':>10s} {'sim':>10s}")
    for label, a, b in (("focal x (px)", K[0, 0], sim_k[0, 0]), ("focal y (px)", K[1, 1], sim_k[1, 1]),
                        ("centre x (px)", K[0, 2], sim_k[0, 2]), ("centre y (px)", K[1, 2], sim_k[1, 2]),
                        ("FOV horiz (deg)", h, sh), ("FOV vert (deg)", v, sv), ("FOV diag (deg)", d, sd)):
        print(f"{label:18s} {a:10.2f} {b:10.2f}")
    print("Saved calib.json. Run `report` for the plots.")


def cmd_report():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    data = np.load(os.path.join(OUT, f"calib_{TARGET}_views.npz"), allow_pickle=True)
    size = tuple(int(x) for x in data["size"])
    views = list(zip(data["corners"], data["ids"]))
    rms, K, dist, objs, imgs, rv, tv = calibrate(views, size)
    w, h = size
    fig, ax = plt.subplots(2, 2, figsize=(15, 9.5))
    fig.suptitle(f"Innomaker U20CAM, {w}x{h}: {len(views)} views, RMS error {rms:.2f} px (rational model)", fontsize=13)
    # 1. coverage and residual arrows
    a = ax[0, 0]
    errs = []
    for o, i, r, t in zip(objs, imgs, rv, tv):
        p = cv2.projectPoints(o, r, t, K, dist)[0].reshape(-1, 2)
        i = i.reshape(-1, 2)
        errs.append(np.hypot(*(p - i).T))
        a.quiver(i[:, 0], i[:, 1], (p - i)[:, 0], (p - i)[:, 1], angles="xy", scale_units="xy", scale=0.02, width=0.002)
    a.set_xlim(0, w); a.set_ylim(h, 0); a.set_aspect("equal")
    a.set_title("Where the board was seen, and each corner's error (arrows 50x)")
    # 2. per-view error
    a = ax[0, 1]
    a.bar(range(1, len(errs) + 1), [math.sqrt(np.mean(e ** 2)) for e in errs], color="#1d4e89")
    a.set_xlabel("view"); a.set_ylabel("RMS error (px)"); a.set_title("Error per view: a tall bar is a blurry or bad view")
    # 3. distortion: how far the lens moves a point, by angle off-axis, measured against the sim
    a = ax[1, 0]
    theta = np.radians(np.linspace(0, 62, 100))
    for KK, dd, lab, st in ((K, dist, "measured", "-"), (scaled(SIM_K, w, 1280), SIM_DIST, "sim", "--")):
        r_pin = KK[0, 0] * np.tan(theta)
        x = np.c_[np.tan(theta), np.zeros_like(theta), np.ones_like(theta)]
        p = cv2.projectPoints(x.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), KK, dd)[0].reshape(-1, 2)
        r = p[:, 0] - KK[0, 2]
        k = int(np.argmax(r)) + 1  # past its peak the model folds back: it means nothing there
        a.plot(np.degrees(theta[:k]), r[:k], st, label=f"{lab}: where it lands (px from centre)")
        a.plot(np.degrees(theta), r_pin, st, alpha=0.35, label=f"{lab}: without distortion")
    a.set_ylim(0, 1100 * w / 1280); a.axhline(w / 2, color="grey", lw=0.8); a.text(1, w / 2 + 10, f"image edge ({w // 2} px)", fontsize=8)
    a.set_xlabel("angle off the optical axis (deg)"); a.set_ylabel("px from centre"); a.legend(fontsize=7)
    a.set_title("Lens projection: measured against the sim")
    # 4. uncertainty: how much a projected point moves when the calibration is redone on resampled views
    a = ax[1, 1]
    gx, gy = np.meshgrid(np.linspace(20, w - 20, 32), np.linspace(20, h - 20, 18))
    pix = np.c_[gx.ravel(), gy.ravel()].reshape(-1, 1, 2).astype(np.float64)
    rays = cv2.undistortPoints(pix, K, dist).reshape(-1, 2)
    rays3 = np.c_[rays, np.ones(len(rays))]
    unit = rays3 / np.linalg.norm(rays3, axis=1, keepdims=True)
    rng = np.random.default_rng(0)
    moved = []
    for _ in range(20):
        pick = rng.integers(0, len(views), len(views))
        try:
            _, Kb, db, *_ = calibrate([views[k] for k in pick], size)
        except cv2.error:
            continue
        # A slightly different image centre is the same as the camera turned slightly, which the board pose (or the
        # arm's pose) absorbs. So first turn the rays to fit this solution best, as mrcal does, then measure what's left.
        rb = np.c_[cv2.undistortPoints(pix, Kb, db).reshape(-1, 2), np.ones(len(pix))]
        u, _, vt = np.linalg.svd((rb / np.linalg.norm(rb, axis=1, keepdims=True)).T @ unit)
        rot = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        moved.append(cv2.projectPoints((unit @ rot.T).reshape(-1, 1, 3), np.zeros(3), np.zeros(3), Kb, db)[0].reshape(-1, 2)
                     - pix.reshape(-1, 2))
    unc = np.std(np.stack(moved), 0)
    unc = np.hypot(unc[:, 0], unc[:, 1]).reshape(gx.shape)
    im = a.imshow(unc, extent=(0, w, h, 0), cmap="magma", vmin=0, vmax=max(1.0, float(np.percentile(unc, 95))))
    fig.colorbar(im, ax=a, label="px")
    a.set_title("Calibration uncertainty: how far a point could be off (bootstrap)")
    plt.tight_layout()
    path = os.path.join(OUT, "calib_report.png")
    plt.savefig(path, dpi=110)
    print(f"Saved {path}. Uncertainty: median {np.median(unc):.2f} px, worst {unc.max():.2f} px.")


def cmd_focus():
    K, dist = load_calib(1280)  # blur in px is compared with the sim's 720p model, so this test stays at 720p
    print("Start with the camera about 50 cm from the board, move it slowly straight in to about 6 cm over 40 s, "
          "then back out. q or 60 s ends it.")
    if TARGET == "laptop":
        show(board_canvas(), True)
    cam = Cam((1280, 720))
    rows, t_end, last_n = [], time.time() + 60, -1
    while time.time() < t_end:
        frame, n = cam.read()
        if n == last_n:
            time.sleep(0.005)
            continue
        last_n = n
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids = detect(gray)
        if corners is not None and len(ids) >= 8:
            obj, img = BOARD.matchImagePoints(corners, ids)
            ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist)
            s = blur_sigma(gray, corners) if ok else None
            if s is not None:
                R = cv2.Rodrigues(rvec)[0]
                rows.append((float(np.mean((obj.reshape(-1, 3) @ R.T + tvec.ravel())[:, 2]) * 1000), s))
        cv2.imshow("camera", cv2.resize(frame, (640, 360)))
        if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
            break
    cam.close()
    cv2.destroyAllWindows()
    json.dump(rows, open(os.path.join(OUT, "focus.json"), "w"))
    if not rows:
        sys.exit("The board was never seen.")
    print(f"\n{len(rows)} frames. Blur (Gaussian-equivalent px) against distance; the sim's column assumes focus at 12 cm:")
    print(f"{'distance':>9s} {'measured':>9s} {'sim':>6s} {'frames':>7s}")
    best = None
    for lo in range(40, 600, 20):
        b = [s for z, s in rows if lo <= z < lo + 20]
        if len(b) >= 3:
            m = float(np.median(b))
            best = (lo + 10, m) if best is None or m < best[1] else best
            print(f"{lo / 10:5.0f}-{(lo + 20) / 10:2.0f} cm {m:9.2f} {sim_sigma(lo + 10):6.2f} {len(b):7d}")
    if best:
        print(f"Sharpest at about {best[0] / 10:.0f} cm (blur {best[1]:.2f} px). The sim assumes the lens is focused at 12 cm.")


def cmd_noise():
    px = TARGETS["laptop"]["px"]
    ramp = np.repeat(np.repeat(np.linspace(0, 255, 16).astype(np.uint8)[None, :], px[1], 0), px[0] // 16, 1)
    print("Grey bars fill the laptop screen. Prop the camera so it can't move, facing them and filled by them. "
          "It settles for 3 s, then records 60 frames.")
    locked = lock_controls()
    show(ramp, True)
    cv2.waitKey(300)
    cam = Cam((1280, 720))  # compared with the sim's 720p noise model
    t0 = time.time()
    while time.time() - t0 < 3:
        cv2.waitKey(20)
    frames, last_n = [], -1
    while len(frames) < 60:
        f, n = cam.read()
        if n != last_n:
            frames.append(f[:, :, 1].astype(np.float32))
            last_n = n
        cv2.waitKey(5)
    cam.close()
    cv2.destroyAllWindows()
    st = np.stack(frames)
    mean, std = st.mean(0), st.std(0)
    print(f"Exposure and white balance locked: {locked}")
    print(f"{'brightness':>10s} {'measured noise':>15s} {'sim':>6s}  (DN, green channel)")
    for lo in range(8, 248, 16):
        m = (mean >= lo) & (mean < lo + 16)
        if m.sum() > 2000:
            x = ((lo + 8) / 255) ** 2.2
            sim = 255 / 2.2 * x ** (1 / 2.2 - 1) / SIM_WHITE_E * math.sqrt(x * SIM_WHITE_E + SIM_READ_E ** 2)
            print(f"{lo:4d}-{lo + 16:<5d} {float(np.median(std[m])):15.2f} {sim:6.2f}")


def cmd_exposure():
    """exposure auto | exposure -4 : auto exposure and white balance, or a fixed exposure of 2^N seconds (-4 = 62 ms)."""
    arg = next((a for a in sys.argv[2:] if not a.startswith("--target")), "auto")
    idx, _ = find_camera()
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if arg == "auto":
        ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75), cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        print(f"Auto exposure and white balance on: {all(ok)}")
    else:
        ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25), cap.set(cv2.CAP_PROP_EXPOSURE, float(arg)), cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        print(f"Exposure fixed at 2^{arg} s = {1000 * 2 ** float(arg):.0f} ms, auto white balance: {all(ok)}")
    cap.release()


def cmd_snap():
    cam = Cam()
    n = len(glob.glob(os.path.join(OUT, "snap_*.jpg")))
    print("Point it at a TV remote, thermostat or light switch about 12 cm away. Space saves a frame, q quits.")
    while True:
        frame, _ = cam.read()
        sharp = cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        view = frame.copy()
        cv2.putText(view, f"sharpness {sharp:.0f}  (space: save, q: quit)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        cv2.imshow("camera", view)
        k = cv2.waitKey(1) & 0xFF
        if k == ord(" "):
            n += 1
            cv2.imwrite(os.path.join(OUT, f"snap_{n:02d}.jpg"), frame)
            print(f"saved snap_{n:02d}.jpg (sharpness {sharp:.0f})")
            beep()
        elif k in (ord("q"), 27):
            break
    cam.close()
    cv2.destroyAllWindows()


def cmd_seg():
    import segmodels
    for path in sorted(glob.glob(os.path.join(OUT, "snap_*.jpg"))):
        img = cv2.imread(path)
        boxes, _, _ = segmodels.owl()(img)
        masks, _ = segmodels.sam_boxes()(img, boxes)
        out = img.copy()
        for b, m in zip(boxes, masks):
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(out, cnts, -1, (0, 255, 255), 2)
            cv2.rectangle(out, tuple(map(int, b[:2])), tuple(map(int, b[2:])), (255, 128, 0), 1)
        # SAM's own search for parts (the pipeline's second source), small-to-medium regions only, in cyan
        amasks, _, _ = segmodels.sam_auto()(img)
        area = img.shape[0] * img.shape[1]
        kept = [m for m in amasks if 0.0002 * area < m.sum() < 0.02 * area]
        for m in kept:
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(out, cnts, -1, (255, 255, 0), 1)
        dst = path.replace("snap_", "seg_")
        cv2.imwrite(dst, out)
        print(f"{os.path.basename(path)}: {len(boxes)} OWLv2 boxes (yellow), {len(kept)} SAM auto regions (cyan) -> {os.path.basename(dst)}")


def cmd_undistort():
    """Raw and straightened views side by side, live, or for saved photos given as arguments."""
    size = SIZE
    K, dist = load_calib(size[0])  # works whichever size calib.json was measured at
    maps = {}
    for alpha in (0, 1):  # 0: crop to pixels that hold real image, 1: keep the whole view (curved black edges)
        newK, _ = cv2.getOptimalNewCameraMatrix(K, dist, size, alpha)
        maps[alpha] = cv2.initUndistortRectifyMap(K, dist, None, newK, size, cv2.CV_16SC2)

    def show(frame, alpha):
        straight = cv2.remap(frame, *maps[alpha], cv2.INTER_LINEAR)
        both = np.hstack([frame, straight])
        for x in range(0, both.shape[1], 160):  # straight lines to judge against
            cv2.line(both, (x, 0), (x, both.shape[0]), (0, 255, 0), 1)
        for y in range(0, both.shape[0], 120):
            cv2.line(both, (0, y), (both.shape[1], y), (0, 255, 0), 1)
        cv2.putText(both, "raw", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2 * size[0] / 1280, (0, 255, 255), 2)
        cv2.putText(both, f"undistorted ({'whole view' if alpha else 'cropped'}; a: toggle, s: save, q: quit)",
                    (size[0] + 20, 40), cv2.FONT_HERSHEY_SIMPLEX, size[0] / 1280, (0, 255, 255), 2)
        return both

    files = [a for a in sys.argv[2:] if not a.startswith("--")]
    if files:
        for path in files:
            for alpha in (0, 1):
                dst = os.path.join(OUT, f"undistort_{alpha}_{os.path.basename(path)}")
                cv2.imwrite(dst, show(cv2.resize(cv2.imread(path), size), alpha))
                print("wrote", dst)
        return
    cam, alpha, n = Cam(size), 1, 0
    while True:
        frame, _ = cam.read()
        both = show(frame, alpha)
        cv2.imshow("undistort", cv2.resize(both, (1600, 450)))
        k = cv2.waitKey(1) & 0xFF
        if k == ord("a"):
            alpha = 1 - alpha
        elif k == ord("s"):
            n += 1
            cv2.imwrite(os.path.join(OUT, f"undistort_live_{n:02d}.jpg"), both)
            print(f"saved undistort_live_{n:02d}.jpg")
        elif k in (ord("q"), 27):
            break
    cam.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    cmd = next((a for a in sys.argv[1:] if not a.startswith("--")), "info")
    {"info": cmd_info, "crop": cmd_crop, "calib": cmd_calib, "report": cmd_report, "focus": cmd_focus,
     "noise": cmd_noise, "exposure": cmd_exposure, "snap": cmd_snap, "seg": cmd_seg, "undistort": cmd_undistort}[cmd]()
