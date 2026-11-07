"""Bring-up checks for the real cameras (real_cameras.py): the iPhone on its tripod, and any camera as an index.

  python tools/cam_check.py list                      # snapshot each camera index -> cam_<i>.jpg
  python tools/cam_check.py preview --index 1         # live view with resolution + fps (q quit, s save)
  python tools/cam_check.py fps --index 1 --seconds 600 [--width 1280 --height 720]
  python tools/cam_check.py latency --index 1         # point the phone at the stimulus window first
  python tools/cam_check.py board                     # board.png: the desk board at 300 dpi, print at 100%
  python tools/cam_check.py calibrate --index 1 --width 1280 --height 720 --out phone_cam.json
  python tools/cam_check.py lidar                     # Record3D over USB: RGB, LiDAR depth, confidence, fps

Continuity Camera indexes on macOS: run list, the iPhone is usually 1 (0 is the laptop's own). The USB wrist module
appears as another index. calibrate is for the phone over Continuity (PhoneCamera(source="continuity", calib=...)); Record3D sends its own
intrinsics. To calibrate the wrist camera, use arm/camera/camera_test.py calib.
Run from system-1/hardware, with `uv run` (lidar needs `uv sync --extra phone`).
"""
import argparse
import csv
import os
import sys
import time

import cv2
import numpy as np

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE] + [os.path.join(HARDWARE, "..", d) for d in ("core", "sim")]  # sim: the desk board, vision.py


def open_cam(index, width, height, mjpeg=False):
    import real_cameras
    try:
        cap = real_cameras.open_capture(index, (width, height), mjpeg)
    except real_cameras.CameraError as e:
        sys.exit(str(e))
    ok, frame = cap.read()
    if not ok:
        sys.exit(f"Camera {index} opened but returned no frame.")
    print(f"camera {index}: requested {width}x{height}, got {frame.shape[1]}x{frame.shape[0]}")
    return cap


def cmd_list(args):
    found = False
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    for i in range(args.max_index):
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            for _ in range(5):  # let exposure settle
                ok, frame = cap.read()
            if ok:
                cv2.imwrite(f"cam_{i}.jpg", frame)
                print(f"index {i}: {frame.shape[1]}x{frame.shape[0]} -> saved cam_{i}.jpg")
                found = True
        cap.release()
    if not found:
        print("No cameras returned frames. Check the Camera permission for your terminal.")


def cmd_preview(args):
    cap = open_cam(args.index, args.width, args.height, args.mjpeg)
    n, fps, last = 0, 0.0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        n += 1
        now = time.perf_counter()
        if now - last >= 1.0:
            fps, n, last = n / (now - last), 0, now
        label = f"{frame.shape[1]}x{frame.shape[0]}  {fps:.1f} fps   q quit, s save"
        cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imshow("preview", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            name = f"snap_{int(time.time())}.jpg"
            cv2.imwrite(name, frame)
            print("saved", name)
    cap.release()
    cv2.destroyAllWindows()


def cmd_fps(args):
    cap = open_cam(args.index, args.width, args.height, args.mjpeg)
    print(f"logging frames for {args.seconds} s...")
    stamps, failures = [], 0
    end = time.perf_counter() + args.seconds
    while time.perf_counter() < end:
        ok, _ = cap.read()
        if ok:
            stamps.append(time.perf_counter())
        else:
            failures += 1
    cap.release()
    if len(stamps) < 3:
        sys.exit("Too few frames to analyze.")
    gaps = np.diff(stamps)
    med = float(np.median(gaps))
    late = gaps[gaps > 1.5 * med]
    dropped = int(np.sum(np.round(late / med) - 1))
    pauses = int(np.sum(gaps > 1.0))
    print(f"frames: {len(stamps)}   mean fps: {(len(stamps) - 1) / (stamps[-1] - stamps[0]):.2f}")
    print(f"median interval: {med * 1000:.1f} ms   max gap: {gaps.max() * 1000:.0f} ms")
    print(f"estimated dropped frames: {dropped}   pauses over 1 s: {pauses}   read failures: {failures}")
    out = f"fps_{args.width}x{args.height}_{int(time.time())}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "t_seconds"])
        for i, t in enumerate(stamps):
            w.writerow([i, t - stamps[0]])
    print("timestamps saved to", out)


def center_brightness(frame):
    h, w = frame.shape[:2]
    crop = frame[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    return float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean())


def show(level):
    cv2.imshow("stimulus", np.full((700, 1000), level, np.uint8))
    cv2.waitKey(1)


def settle(cap, seconds):
    vals, end = [], time.perf_counter() + seconds
    while time.perf_counter() < end:
        ok, frame = cap.read()
        if ok:
            vals.append(center_brightness(frame))
        cv2.waitKey(1)
    return float(np.median(vals[-10:])) if vals else 0.0


def cmd_latency(args):
    cap = open_cam(args.index, args.width, args.height)
    cv2.namedWindow("stimulus", cv2.WINDOW_NORMAL)
    print("Point the phone at the stimulus window so it fills the middle of the frame.")
    show(0)
    settle(cap, 3)  # time to aim
    dark = settle(cap, 2)
    show(255)
    bright = settle(cap, 2)
    if bright - dark < 30:
        sys.exit(f"Not enough contrast (dark {dark:.0f}, bright {bright:.0f}). Aim closer or dim the room.")
    threshold = (dark + bright) / 2
    results = []
    for i in range(args.trials):
        show(0)
        settle(cap, 1.0)
        show(255)
        t0 = time.perf_counter()
        while True:
            ok, frame = cap.read()
            t = time.perf_counter()
            if ok and center_brightness(frame) > threshold:
                results.append((t - t0) * 1000)
                print(f"trial {i + 1}: {results[-1]:.0f} ms")
                break
            if t - t0 > 2.0:
                print(f"trial {i + 1}: timed out")
                break
    cap.release()
    cv2.destroyAllWindows()
    if results:
        r = np.array(results)
        print(f"\n{len(r)}/{args.trials} trials   median {np.median(r):.0f} ms   "
              f"p90 {np.percentile(r, 90):.0f} ms   max {r.max():.0f} ms")
        print("Includes screen refresh (up to ~16 ms), so true camera latency is a bit lower.")


def cmd_board(args):
    """The desk board vision.py solves poses from, as a PNG to print at 100% scale."""
    import appliance as A
    import vision
    px_per_m = args.dpi / 0.0254
    w, h = (round(n * A.BOARD_SQUARE_M * px_per_m) for n in A.BOARD_SQUARES)
    margin = round(0.01 * px_per_m)
    img = cv2.copyMakeBorder(vision.BOARD.generateImage((w, h)), margin, margin, margin, margin,
                             cv2.BORDER_CONSTANT, value=255)
    cv2.imwrite(args.out, img)
    print(f"{args.out}: {A.BOARD_SQUARES[0]}x{A.BOARD_SQUARES[1]} squares of {A.BOARD_SQUARE_M * 1000:.0f} mm at "
          f"{args.dpi} dpi. Print at 100% and measure one square: it must be {A.BOARD_SQUARE_M * 1000:.1f} mm.")


def cmd_calibrate(args):
    """Intrinsics from views of the printed board: space keeps a view (auto every second with --auto), q solves."""
    import real_cameras
    import vision
    cap = open_cam(args.index, args.width, args.height, args.mjpeg)
    detector = cv2.aruco.CharucoDetector(vision.BOARD)
    obj_pts, img_pts, size, last = [], [], None, 0.0
    print("Hold the board at many angles and distances, filling the corners of the frame too.")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        size = frame.shape[1::-1]
        cc, ci, _, _ = detector.detectBoard(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        n = 0 if ci is None else len(ci)
        show = frame.copy()
        if n:
            cv2.aruco.drawDetectedCornersCharuco(show, cc, ci)
        cv2.putText(show, f"{len(obj_pts)} views   {n} corners   space keep, q solve", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imshow("calibrate", show)
        key = cv2.waitKey(1) & 0xFF
        now = time.perf_counter()
        if n >= 8 and (key == ord(" ") or (args.auto and now - last > 1.0)):
            o, i = vision.BOARD.matchImagePoints(cc, ci)
            obj_pts.append(o)
            img_pts.append(i)
            last = now
            print(f"view {len(obj_pts)}: {n} corners")
        if key == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
    if len(obj_pts) < 10:
        sys.exit(f"Only {len(obj_pts)} views: take at least 10, ideally 25.")
    rms, K, dist, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
    real_cameras.save_calibration(args.out, K, dist, size, rms, views=len(obj_pts))
    print(f"rms {rms:.2f} px over {len(obj_pts)} views -> {args.out}")
    print(f"fx {K[0, 0]:.1f}  fy {K[1, 1]:.1f}  cx {K[0, 2]:.1f}  cy {K[1, 2]:.1f}  dist {np.round(dist.ravel(), 4)}")
    if rms > 1.0:
        print("Over 1 px: some views were blurred or the print isn't flat. Calibrate again.")


def cmd_lidar(args):
    """Record3D's USB stream: RGB and depth side by side, fps, the depth and confidence at the centre."""
    import real_cameras
    try:
        src = real_cameras.Record3DSource(args.device)
    except (real_cameras.CameraError, ImportError) as e:
        sys.exit(f"{e}\n(record3d is in the phone extra: uv sync --extra phone)")
    print("LiDAR" if src.lidar else "TrueDepth (front camera): turn the phone round for the LiDAR")
    n, fps, last, shown = 0, 0.0, time.perf_counter(), False
    while True:
        ok, item = src.read()
        if not ok:
            if src.stopped:
                sys.exit("Stream stopped.")
            continue
        bgr, depth, conf, K = item
        n += 1
        now = time.perf_counter()
        if now - last >= 1.0:
            fps, n, last = n / (now - last), 0, now
        if not shown:
            print(f"rgb {bgr.shape[1]}x{bgr.shape[0]}  depth {depth.shape[1]}x{depth.shape[0]}  "
                  f"fx {K[0, 0]:.1f} fy {K[1, 1]:.1f} cx {K[0, 2]:.1f} cy {K[1, 2]:.1f}")
            shown = True
        h, w = depth.shape
        centre = float(np.nanmedian(depth[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4]))
        good = float(np.mean(conf >= 2)) if conf.size else float("nan")
        vis = cv2.applyColorMap(cv2.convertScaleAbs(np.nan_to_num(depth), alpha=255 / args.max_m), cv2.COLORMAP_TURBO)
        vis = cv2.resize(vis, (round(bgr.shape[0] * w / h), bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        out = np.hstack([bgr, vis])
        out = cv2.resize(out, None, fx=900 / out.shape[1], fy=900 / out.shape[1])
        cv2.putText(out, f"{fps:.1f} fps  centre {centre * 100:.1f} cm  high conf {good:.0%}   q quit, s save",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow("lidar", out)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            name = f"lidar_{int(time.time())}.npz"
            np.savez_compressed(name, bgr=bgr, depth=depth, confidence=conf, K=K)
            print("saved", name)
    src.release()
    cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "preview", "fps", "latency", "calibrate"):
        s = sub.add_parser(name)
        s.add_argument("--index", type=int, default=0)
        s.add_argument("--width", type=int, default=1920)
        s.add_argument("--height", type=int, default=1080)
        s.add_argument("--mjpeg", action="store_true", help="ask for MJPEG: the USB wrist module needs it for 30 fps")
        if name == "list":
            s.add_argument("--max-index", type=int, default=6)
        if name == "fps":
            s.add_argument("--seconds", type=int, default=600)
        if name == "latency":
            s.add_argument("--trials", type=int, default=20)
        if name == "calibrate":
            s.add_argument("--out", default="phone_cam.json")
            s.add_argument("--auto", action="store_true", help="keep a view every second instead of on space")
    s = sub.add_parser("board")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--out", default="board.png")
    s = sub.add_parser("lidar")
    s.add_argument("--device", type=int, default=0)
    s.add_argument("--max-m", type=float, default=1.5, help="depth shown as the far end of the colour map")
    args = p.parse_args()
    {"list": cmd_list, "preview": cmd_preview, "fps": cmd_fps, "latency": cmd_latency, "board": cmd_board,
     "calibrate": cmd_calibrate, "lidar": cmd_lidar}[args.cmd](args)


if __name__ == "__main__":
    main()