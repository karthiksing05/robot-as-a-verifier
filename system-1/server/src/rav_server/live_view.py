"""The real rig's live window, for people watching: the wrist camera's newest frame, undistorted and at half size, with
each part from the last scan outlined and named where the arm's last joint reading puts it, nudged onto the frame by
the scan's orthophoto (ortho_offset; the current step's target in green), the gripper's mask, and the status line. During a step, its last look is inset as touch._save_look drew it
(the part as believed in white, SAM's outline yellow, the fitted circle green), with a red cross where the press aims.

It reads camera frames and state other threads keep (arm.q, arm.status, backend.parts), never the servo bus, so it runs
beside the scan and the presses. A drawing error is printed once and the window carries on with less on it."""
from __future__ import annotations

import glob
import os
import time

import cv2
import numpy as np

SCALE = 0.5    # of the camera's frame
INSET = 0.42   # the look's width, of the window's
PERIOD_MS = 80
SEARCH = 60    # px each way the scan's orthophoto is looked for round where the joints' pose puts it
PART, TARGET, PRESS = (255, 255, 0), (0, 255, 0), (0, 0, 255)  # BGR


def run(backend):
    """The window's loop, on a daemon thread: real_backend starts it with the RealBackend."""
    import mujoco
    import rig
    import touch

    wrist, arm = backend.rig.wrist, backend.arm
    fk, K = mujoco.MjData(wrist.m), wrist.K * [[SCALE], [SCALE], [1]]  # its own MjData: believed_pose's is the scan's
    looks, errors = {}, set()
    _watch_looks(touch, looks)
    label, since, before, shown = None, 0.0, 0.0, (None, None)
    while True:
        try:
            now, s = time.monotonic(), arm.status
            img = cv2.resize(cv2.remap(wrist.grab.read()[0], *wrist.maps, cv2.INTER_LINEAR), None, fx=SCALE, fy=SCALE)
            status = f"{backend.stage} | {s}"
            if s.split(":")[0] != label:  # a new step (or stage): only looks since the last frame are this step's
                label, since = s.split(":")[0], before
            before = now
            parts = list(backend.parts or [])
            target = next((p.id for p in parts if p.id in label.split()), None)
            fk.qpos[arm.qadr] = arm.q
            mujoco.mj_kinematics(wrist.m, fk)
            mujoco.mj_camlight(wrist.m, fk)
            T = rig._cv_pose(fk, wrist.cam) @ wrist.T_hand_eye
            Kd = K.copy()
            if backend.scene is not None:
                Kd[:2, 2] += ortho_offset(img, K, T, backend.scene)
            look = looks.get("last")
            if look and look[1] == target and look[0] >= since:
                if shown[0] is not look:
                    shown = (look, inset_image(touch.LOOK_DIR, look, int(img.shape[1] * INSET)))
                inset = shown[1]
            else:
                inset = None
            compose(img, Kd, T, parts, getattr(arm, "part_shift", None), target, status, inset, errors)
            cv2.imshow("System 1: wrist camera", img)
            cv2.waitKey(PERIOD_MS)
        except Exception as e:  # noqa: BLE001 - the window must never stop the robot
            _once(errors, "live view", e)
            time.sleep(1)


def compose(img, K, T, parts, shift, target, status, inset=None, errors=None):
    """Draws on img (an undistorted frame, K its intrinsics, T the camera's pose in the arm frame) in place. parts are
    the backend's, moved by shift (RealArm.part_shift) for the arm; they are drawn where the camera saw them."""
    import rgbperceive

    errors = set() if errors is None else errors
    try:
        cv2.polylines(img, [rgbperceive._gripper(img.shape[1])], True, (0, 200, 255), 2)
    except Exception as e:  # noqa: BLE001
        _once(errors, "gripper", e)
    th = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    for p in sorted(parts, key=lambda p: p.id == target):  # the target last, on top
        try:
            n, m = p.normal, p.meta
            u = p.x - (p.x @ n) * n
            u /= np.linalg.norm(u)
            c = p.pos if shift is None else p.pos - (shift - (shift @ n) * n)
            r = m.get("radius") or m.get("pad_radius") or m.get("knob_radius") or max(p.size[:2]) / 2
            px, z = rgbperceive._project(K, T, c + r * (np.outer(np.cos(th), u) + np.outer(np.sin(th), np.cross(n, u))))
            if (z < 0.02).any():  # behind the camera, or right at the lens
                continue
            on = p.id == target
            cv2.polylines(img, [px.astype(np.int32)], True, TARGET if on else PART, 3 if on else 2, cv2.LINE_AA)
            name = f"> {p.id}" if on else p.id
            at = (int(px[:, 0].min()), int(px[:, 1].min()) - 8)
            _text(img, name, at, 0.8 if on else 0.6, TARGET if on else PART)
        except Exception as e:  # noqa: BLE001
            _once(errors, f"part {getattr(p, 'id', '?')}", e)
    if inset is not None:
        try:
            h, w = inset.shape[:2]
            y0, x0 = 50, img.shape[1] - w - 8
            img[y0:y0 + h, x0:x0 + w] = inset
            cv2.rectangle(img, (x0 - 1, y0 - 1), (x0 + w, y0 + h), (255, 255, 255), 2)
            _text(img, "last look", (x0 + 8, y0 + 24), 0.6, (255, 255, 255))
        except Exception as e:  # noqa: BLE001
            _once(errors, "look", e)
    _text(img, status, (12, 34), 0.8, (255, 255, 255))
    return img


def ortho_offset(img, K, T, scene):
    """Pixels (dx, dy) to move what's drawn through pose T so it lands on img: the scan's orthophoto warped into img
    through T, then found in img within SEARCH. The joints' pose is only good to a degree or two, and off by different
    amounts in different poses: near home it put the scan's parts 15-50 px (at this size) left of where they show.
    (0, 0) if the panel is mostly out of view or the best match is at the search's edge."""
    import rgbperceive

    ortho, h, w = scene.heightmap[1], *img.shape[:2]
    H = rgbperceive._homography(K, T, scene.plane[0], 0, 0, 0.0)
    ref = cv2.warpPerspective(cv2.cvtColor(ortho, cv2.COLOR_BGR2GRAY), H, (w, h))
    mask = cv2.warpPerspective((ortho.max(2) > 0).astype(np.uint8) * 255, H, (w, h), flags=cv2.INTER_NEAREST)
    cv2.fillPoly(mask, [rgbperceive._gripper(w)], 0)
    S = SEARCH
    y, x = np.nonzero(mask[S:-S, S:-S])
    if len(x) < 0.05 * w * h:
        return np.zeros(2)
    x0, x1, y0, y1 = x.min() + S, x.max() + S + 1, y.min() + S, y.max() + S + 1
    res = cv2.matchTemplate(cv2.cvtColor(img[y0 - S:y1 + S, x0 - S:x1 + S], cv2.COLOR_BGR2GRAY), ref[y0:y1, x0:x1],
                            cv2.TM_CCORR_NORMED, mask=mask[y0:y1, x0:x1])
    d = np.array(cv2.minMaxLoc(res)[3], float) - S
    return np.zeros(2) if np.abs(d).max() >= S else d


def inset_image(look_dir, look, width):
    """The look's picture from look_dir (its newest of that part), cropped to a third of its width round where the
    press aims, with a red cross there and what the look said, at width. None if there's none."""
    _, pid, aim, said = look
    paths = glob.glob(os.path.join(look_dir or "", f"*_{glob.escape(pid)}.jpg"))
    img = cv2.imread(max(paths, key=os.path.getmtime)) if paths else None
    if img is None:
        return None
    H, W = img.shape[:2]
    x, y = (W // 2, H // 2) if aim is None else np.round(aim).astype(int)
    if aim is not None:
        cv2.drawMarker(img, (x, y), PRESS, cv2.MARKER_CROSS, 40, 3)
    w, h = W // 3, H // 3
    x0, y0 = int(np.clip(x - w // 2, 0, W - w)), int(np.clip(y - h // 2, 0, H - h))
    img = cv2.resize(img[y0:y0 + h, x0:x0 + w], (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    _text(img, f"{pid}: {said}"[:48], (8, img.shape[0] - 12), 0.55, (255, 255, 255))
    return img


def _watch_looks(touch, looks):
    """Has touch._save_look also put (when, part id, where the press aims in its frame's pixels, what it said) in
    looks["last"]: the aim is the fitted circle's centre if the look moved the part there, else the part as believed."""
    save = touch._save_look

    def save_and_show(f, p, plane, seen, said):
        save(f, p, plane, seen, said)
        try:
            ring = seen.get("circle") if said.startswith("refined") else seen.get("believed")
            looks["last"] = (time.monotonic(), p.id, None if ring is None else np.mean(ring, axis=0), said)
        except Exception as e:  # noqa: BLE001
            print(f"live view: couldn't note the look: {type(e).__name__}: {e}")
    touch._save_look = save_and_show


def _text(img, s, at, size, color, width=2):
    for c, w in (((0, 0, 0), width + 3), (color, width)):
        cv2.putText(img, s, at, cv2.FONT_HERSHEY_SIMPLEX, size, c, w, cv2.LINE_AA)


def _once(errors, what, e):
    key = f"{what}: {type(e).__name__}: {e}"
    if key not in errors:
        errors.add(key)
        print(f"live view: {key}", flush=True)
