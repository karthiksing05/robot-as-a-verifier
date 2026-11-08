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
STAGES = ("survey", "scan", "poses", "orthophoto", "segment", "heights", "classify", "done")
HOLD_S = 20    # the classified parts' panel stays this long after the scan
MAX_MM = 15    # heights shown from blue (the panel) to red (this far up)


def run(backend):
    """The window's loop, on a daemon thread: real_backend starts it with the RealBackend."""
    import mujoco
    import rgbperceive
    import rig
    import touch

    wrist, arm = backend.rig.wrist, backend.arm
    fk, K = mujoco.MjData(wrist.m), wrist.K * [[SCALE], [SCALE], [1]]  # its own MjData: believed_pose's is the scan's
    looks, errors, progress = {}, set(), {}
    _watch_looks(touch, looks)
    rgbperceive.PROGRESS = lambda what, **info: note(progress, what, info)
    label, since, before, shown, drawn = None, 0.0, 0.0, (None, None), (None, None)
    while True:
        try:
            now, s = time.monotonic(), arm.status
            img = cv2.resize(cv2.remap(wrist.grab.read()[0], *wrist.maps, cv2.INTER_LINEAR), None, fx=SCALE, fy=SCALE)
            status = f"{backend.stage} | {s}"
            if s.split(":")[0] != label:  # a new step (or stage): only looks since the last frame are this step's
                label, since = s.split(":")[0], before
            before = now
            scanning = backend.stage.startswith("scan ")
            parts = [] if scanning else list(backend.parts or [])  # the last scan's parts are stale while it rescans
            target = next((p.id for p in parts if p.id in label.split()), None)
            fk.qpos[arm.qadr] = arm.q
            mujoco.mj_kinematics(wrist.m, fk)
            mujoco.mj_camlight(wrist.m, fk)
            T = rig._cv_pose(fk, wrist.cam) @ wrist.T_hand_eye
            Kd = K.copy()
            if backend.scene is not None and not scanning:
                Kd[:2, 2] += ortho_offset(img, K, T, backend.scene)
            look = looks.get("last")
            inset, title = None, "last look"
            if look and look[1] == target and look[0] >= since:
                if shown[0] is not look:
                    shown = (look, inset_image(touch.LOOK_DIR, look, int(img.shape[1] * INSET)))
                inset = shown[1]
            elif scanning or progress.get("stage", ("", 0))[0] == "done" and now - progress["stage"][1] < HOLD_S:
                if drawn[0] != progress.get("n"):  # redrawn only when the scan has news
                    drawn = (progress.get("n"), None)
                    try:
                        drawn = (drawn[0], scan_panel(progress, int(img.shape[1] * INSET), img.shape[0] - 58))
                    except Exception as e:  # noqa: BLE001
                        _once(errors, f"scan panel ({progress.get('show', ('?',))[0]})", e)
                inset, title = drawn[1], ""
            compose(img, Kd, T, parts, getattr(arm, "part_shift", None), target, status, inset, errors, title)
            cv2.imshow("System 1: wrist camera", img)
            if getattr(backend, "live_feed", None):  # main.py's telemetry: the Console shows this same picture
                try:
                    backend.live_feed(img)
                except Exception as e:  # noqa: BLE001
                    _once(errors, "feed", e)
            cv2.waitKey(PERIOD_MS)
        except Exception as e:  # noqa: BLE001 - the window must never stop the robot
            _once(errors, "live view", e)
            time.sleep(1)


def compose(img, K, T, parts, shift, target, status, inset=None, errors=None, title="last look"):
    """Draws on img (an undistorted frame, K its intrinsics, T the camera's pose in the arm frame) in place. parts are
    the backend's, moved by shift (RealArm.part_shift) for the arm; they are drawn where the camera saw them. inset
    goes top right, titled title."""
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
            if title:
                _text(img, title, (x0 + 8, y0 + 24), 0.6, (255, 255, 255))
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


def note(progress, what, info):
    """rgbperceive.PROGRESS, on the scan's thread, so it only keeps things: the stage (name, when) and the newest
    thing to show (what, info) in progress, and a count n of the news."""
    if what == "stage":
        if info["name"] == "survey":
            progress.pop("show", None)
        progress["stage"] = (info["name"], time.monotonic())
        if info["name"] in ("views", "done"):  # the survey's features are in; the parts are
            progress["show"] = (info["name"], info)
    else:
        progress["show"] = (what, info)
    progress["n"] = progress.get("n", 0) + 1


def scan_panel(progress, width, height):
    """The scan's newest product (see note) fitted in width x height, between a caption and a strip of the stages
    with the current one lit."""
    band = 30
    stage = progress.get("stage", ("survey", 0))[0]
    what, info = progress.get("show", (None, {}))
    pic, caption = scan_picture(stage, what, info, width, height - 2 * band)
    panel = np.zeros((pic.shape[0] + 2 * band, width, 3), np.uint8)
    x0 = (width - pic.shape[1]) // 2
    panel[band:band + pic.shape[0], x0:x0 + pic.shape[1]] = pic
    _text(panel, caption[:56], (8, 21), 0.55, (255, 255, 255), 1)
    labels = ["survey", "scan", "poses", "ortho", "segment", "heights", "classify"]
    now = STAGES.index({"views": "survey"}.get(stage, stage)) if stage in STAGES + ("views",) else -1
    size = min(0.5, 0.5 * (width - 16) / sum(cv2.getTextSize(s + "  ", cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
                                              for s in labels))
    x, y = 8, panel.shape[0] - 10
    for k, s in enumerate(labels):
        _text(panel, s, (x, y), size, (0, 255, 0) if k == now else (255, 255, 255) if k < now else (110, 110, 110), 1)
        x += cv2.getTextSize(s + "  ", cv2.FONT_HERSHEY_SIMPLEX, size, 1)[0][0]
    return panel


def scan_picture(stage, what, info, width, height):
    """(picture at most width x height, caption) for one of note's things to show."""
    import rgbperceive

    if what == "capture":
        return _fit(info["frame"].rgb, width, height)[0], f"{stage}: photo at view {info['view'] + 1} of {info['views']}"
    if what == "views":
        return _survey_picture(info["scene"].survey, width, height)
    if what == "orthophoto":
        return _fit(info["img"], width, height)[0], f"orthophoto: {info['n']} of {info['of']} views laid on the panel"
    if what == "done":
        return _parts_picture(info["scene"], width, height)
    if what not in ("owl", "sam", "segment", "heights"):
        return np.zeros((height // 3, width, 3), np.uint8), f"{stage}"
    pic, s = _fit(info["img"], width, height)
    size = pic.shape[1::-1]
    shrink = lambda m: cv2.resize(m.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    colors = rgbperceive.CANDIDATE_COLORS
    if what == "owl":
        for (a, b, c, d), sc in zip(np.asarray(info["boxes"]) * s, info["scores"]):
            cv2.rectangle(pic, (int(a), int(b)), (int(c), int(d)), (0, 255, 255), 1)
        return pic, f"segment: OWLv2 proposed {len(info['boxes'])} boxes"
    if what == "sam":
        for k, m in enumerate(info["masks"]):
            m = shrink(m)
            pic[m] = pic[m] // 2 + np.array(colors[k % len(colors)], np.uint8) // 2
        return pic, f"segment: SAM outlined {len(info['masks'])} boxes"
    if what == "segment":
        for k, c in enumerate(info["cands"]):
            m = shrink(c["mask"])
            pic[m] = pic[m] // 2 + np.array(colors[k % len(colors)], np.uint8) // 2
            cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(pic, cs, -1, colors[k % len(colors)], 1)
        return pic, f"segment: {len(info['cands'])} candidates"
    votes = np.full(info["img"].shape[:2], np.nan, np.float32)  # heights: each swept candidate's votes
    for c in info["cands"]:
        i0, i1, j0, j1 = c["roi"]
        votes[i0:i1, j0:j1] = np.where(np.isnan(votes[i0:i1, j0:j1]), c["votes"][i0:i1, j0:j1], votes[i0:i1, j0:j1])
    _heights(pic, cv2.resize(votes, size, interpolation=cv2.INTER_NEAREST), -1.0)
    return pic, f"heights: {len(info['cands'])} of {info['of']} candidates swept"


def _survey_picture(survey, width, height):
    """The survey photo that sees the most of its features, with them on it (green on the panel's plane, orange off
    it) and the panel's outline."""
    import rgbperceive

    pts, T, (u0, u1, v0, v1) = survey["points"], survey["panel"], survey["extent"]

    def seen(f):
        uv, z = rgbperceive._project(f.K, f.T_base_cam, pts)
        h, w = f.rgb.shape[:2]
        return uv, (z > 0) & (uv[:, 0] >= 0) & (uv[:, 1] >= 0) & (uv[:, 0] < w) & (uv[:, 1] < h)
    f = max((c.frame for c in survey["captures"]), key=lambda f: seen(f)[1].sum())
    pic, s = _fit(f.rgb, width, height)
    uv, ok = seen(f)
    on = np.abs((pts - T[:3, 3]) @ T[:3, 2]) < 0.005
    for (u, v), o in zip(uv[ok] * s, on[ok]):
        cv2.circle(pic, (int(u), int(v)), 2, (0, 255, 0) if o else (0, 140, 255), -1)
    corners = np.array([T[:3, 3] + T[:3, :2] @ [u, v] for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))])
    cv2.polylines(pic, [(rgbperceive._project(f.K, f.T_base_cam, corners)[0] * s).astype(np.int32)], True,
                  (0, 255, 255), 2, cv2.LINE_AA)
    return pic, f"survey: {len(pts)} matched features, panel {(u1 - u0) * 1000:.0f} x {(v1 - v0) * 1000:.0f} mm"


def _parts_picture(scene, width, height):
    """The scan's orthophoto with its heights over 1 mm and each part ringed and named with its kind (a rejected
    candidate in grey), names above and below in turn from left to right so neighbours' don't overlap."""
    hm, ortho, cell = scene.heightmap[:3]
    pic, s = _fit(ortho, width, height)
    _heights(pic, cv2.resize(hm, pic.shape[1::-1], interpolation=cv2.INTER_NEAREST), 0.001)
    Tg = scene.plane[0]
    rings = []
    for p, color in [(p, PART) for p in scene.parts] + [(p, (170, 170, 170)) for p in scene.rejected]:
        i, j = (p.pos - Tg[:3, 3]) @ Tg[:3, :2] / cell * s
        m = p.meta
        r = max((m.get("radius") or m.get("pad_radius") or m.get("knob_radius") or max(p.size[:2]) / 2) / cell * s, 3)
        name = p.id if p.kind in p.id or color != PART else f"{p.id} ({p.kind})"
        rings.append((j, i, r, name, color))
    for k, (j, i, r, name, color) in enumerate(sorted(rings, key=lambda x: x[0])):
        cv2.circle(pic, (int(j), int(i)), int(r), color, 2, cv2.LINE_AA)
        w = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0][0]
        _text(pic, name, (int(j - w / 2), int(i - r - 6 if k % 2 == 0 else i + r + 16)), 0.45, color, 1)
    return pic, f"classified: {len(scene.parts)} parts" + (f", {len(scene.rejected)} unsure" if scene.rejected else "")


def _heights(pic, h, above):
    """Colours pic where h (m, NaN unseen) is over above: blue at the panel to red MAX_MM up; dims the rest."""
    on = np.isfinite(h) & (np.nan_to_num(h, nan=-1) > above)
    c = cv2.applyColorMap((np.clip(np.nan_to_num(h) * 1000 / MAX_MM, 0, 1) * 255).astype(np.uint8),
                          cv2.COLORMAP_TURBO)
    pic[~on] = pic[~on] // 2
    pic[on] = c[on] // 4 * 3 + pic[on] // 4
    _text(pic, f"height 0-{MAX_MM} mm: blue to red", (6, pic.shape[0] - 8), 0.45, (255, 255, 255), 1)


def _fit(img, width, height):
    """img shrunk to fit width x height, and the scale."""
    s = min(width / img.shape[1], height / img.shape[0])
    return cv2.resize(img, (max(round(img.shape[1] * s), 1), max(round(img.shape[0] * s), 1)),
                      interpolation=cv2.INTER_AREA), s


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
