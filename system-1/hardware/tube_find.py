"""Finding a tube in its rack with the wrist camera, for centrifuge_skills' tube_pick. The rack is its own box beside the
centrifuge, not on the panel's plane, so the panel scan never sees it. The tubes' collars are the only green and red
things there: the arm pans right from home over FIND_DQ (as the scan's survey does, further round), each photo's
collar of that colour is found by its hue, and the rays through them are triangulated with the photos' poses.

    top, why = tube_find.find(arm, wrist, "green")   # collar top in the arm's frame (m), or None and why
"""
import os
import time

import cv2
import mujoco
import numpy as np

import perceive
import rgbperceive
import skills

# joint offsets from home (pan, lift, elbow, wrist flex, roll): + pan turns the arm to its right (-y), where the rack
# stands. The survey's +0.3 had the rack at the photo's edge (Nov 8 9:33 scan, green collar at (397, -151, 65) mm); the
# wrist raised 0.25 rad looks further out, and these pans then put it low, middle and high in the photo (on the model)
# (each view's partner photo is only 15 mm over, too short a baseline for the red tube's loop: lift in and out adds 40)
# With the rack moved ~6 cm nearer (Nov 8 9:53), the raised wrist put it at the photos' bottom edge behind the jaw: the
# wrist now tips down 0.2 instead (at 0.05 the near, green tube was still at the bottom edge)
FIND_DQ = [(p, 0.0, 0.0, 0.2, 0.0) for p in (0.25, 0.4, 0.55)] + [(0.4, d, 0.0, 0.2, 0.0) for d in (-0.15, 0.15)]
# OpenCV HSV ranges (hue 0-180). The near tube's collar ring is teal-green; the far one's is red (pinkish in the
# camera). STOP's cap is red too: the blob whose ray passes nearest the others' point wins
COLOURS = {"green": [((70, 90, 50), (100, 255, 255))],
           # the red collar reads hue 170-175; the rack flap's orange tape 2-4 at lower saturation, and hue 0-8 took it
           "red": [((160, 110, 50), (180, 255, 255))]}
MIN_PX = 400               # at 1920 wide: a collar from 20 cm is 2000+
MAX_SPREAD = 0.006         # m: the rays must pass this close to the point they give, on average
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "last_looks")


def blobs(frame, colour):
    """[(area px, (u, v))] of colour's blobs in frame (rig.Frame, BGR), biggest first. Closing joins a ring's halves."""
    hsv = cv2.cvtColor(frame.rgb, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in COLOURS[colour]:
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    h, w = m.shape
    whole = lambda x, y, bw, bh: x > 0 and y > 0 and x + bw < w and y + bh < h  # cut by the edge: its centre is off
    return sorted([(int(st[k, 4]), tuple(cen[k])) for k in range(1, n)
                   if st[k, 4] > MIN_PX * (w / 1920) ** 2 and whole(*st[k, :4])], reverse=True)


def ray(frame, uv):
    """The camera's centre and the unit ray through pixel uv, in the arm's frame."""
    T = frame.T_base_cam
    d = T[:3, :3] @ np.linalg.solve(frame.K, [uv[0], uv[1], 1.0])
    return T[:3, 3], d / np.linalg.norm(d)


def nearest(rays):
    """The point nearest all the rays (least squares) and its mean distance from them."""
    A, b = np.zeros((3, 3)), np.zeros(3)
    for o, d in rays:
        P = np.eye(3) - np.outer(d, d)
        A, b = A + P, b + P @ o
    x = np.linalg.solve(A, b)
    return x, float(np.mean([np.linalg.norm((np.eye(3) - np.outer(d, d)) @ (x - o)) for o, d in rays]))


def locate(frames, colour):
    """The collar's point from frames (each with T_base_cam and K), and how far the rays spread about it, or None and
    why. Each frame offers its blobs; the frame's blob nearest the point the others' biggest give is kept, and the
    worst ray is dropped while the spread is over MAX_SPREAD and three would be left."""
    seen = [(f, b) for f in frames for b in [blobs(f, colour)] if b]
    if len(seen) < 2:
        return None, None, f"{colour} collar in {len(seen)} of {len(frames)} photos: it needs two"
    x, _ = nearest([ray(f, b[0][1]) for f, b in seen])
    rays = []
    for f, b in seen:  # each photo's blob nearest that first guess
        cand = [ray(f, uv) for _, uv in b]
        rays.append(min(cand, key=lambda r: np.linalg.norm((np.eye(3) - np.outer(r[1], r[1])) @ (x - r[0]))))
    x, spread = nearest(rays)
    while spread > MAX_SPREAD and len(rays) > 3:
        rays.pop(min(range(len(rays)), key=lambda i: nearest(rays[:i] + rays[i + 1:])[1]))
        x, spread = nearest(rays)
    if spread > MAX_SPREAD:
        return None, None, f"the {colour} collar's rays spread {spread * 1000:.0f} mm over {len(rays)} photos"
    return x, spread, ""


def find(arm, wrist, colour="green"):
    """Pan over FIND_DQ from home, photographing (the scan's views: each settled, and a partner photo beside it), then
    home. Returns the collar's top in the arm's frame, or None, and a line saying how it went. The photos with the
    blobs drawn go to OUT_DIR."""
    fk, cam = mujoco.MjData(arm.m), arm.m.camera("wrist_cam").id
    views = []
    for dq in FIND_DQ:  # as rgbperceive.survey_wrist's
        q = np.clip(arm.home_q + dq, arm.ik.lo, arm.ik.hi)
        views.append(dict(q=q, T=perceive._camera_pose(arm, fk, cam, q), ok=True, why=""))
    skills.go_home(arm)
    caps = rgbperceive.scan(arm, wrist, views)  # ends at home
    frames = [c.frame for c in caps]
    x, spread, why = locate(frames, colour)
    _save(frames, colour, x)
    if x is None:
        return None, why
    return x, f"{colour} collar at {np.round(x * 1000).astype(int).tolist()} mm from {len(frames)} photos, rays within {spread * 1000:.1f} mm"


def _save(frames, colour, x):
    """Each photo with its blobs ringed and the found point (if any) as a cross, for checking by eye."""
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        for i, f in enumerate(frames):
            img = f.rgb.copy()
            for _, (u, v) in blobs(f, colour):
                cv2.circle(img, (int(u), int(v)), 30, (255, 255, 255), 3)
            if x is not None:
                P = np.linalg.inv(f.T_base_cam) @ np.r_[x, 1.0]
                if P[2] > 0:
                    u, v = (f.K @ (P[:3] / P[2]))[:2]
                    cv2.drawMarker(img, (int(u), int(v)), (0, 0, 255), cv2.MARKER_CROSS, 60, 4)
            cv2.imwrite(os.path.join(OUT_DIR, f"{stamp}_tube_{colour}_{i}.jpg"), cv2.resize(img, None, fx=0.5, fy=0.5))
    except Exception as e:  # noqa: BLE001 - photos are evidence, never a reason to stop
        print(f"couldn't save the tube photos: {type(e).__name__}: {e}")
