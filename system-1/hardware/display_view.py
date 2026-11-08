"""Reading the MC-6 centrifuge's display with the wrist camera. The scan never finds it (its rule wants a lit green LCD,
and it looks only at the sloped panel), so it's placed from the scan's buttons by the device's CAD, photographed from
above and in front of it, and the photo is cropped to it and turned upright for a model to read.

    part = display_view.display_part(parts, plane_T)   # None if the scan found no button
    qs, why = display_view.view_qs(arm, part, plane_T) # joint moves from home; why: "" if they're clear
    crop = display_view.crop(frame, part)              # BGR, the screen upright in the middle
"""
import math

import cv2
import numpy as np

import features

# appliances/centrifuge/device.yaml: the screen's centre sits 16.2 mm toward the arm from the panel under STOP (the
# middle button) and 46.5 mm below it, on the vertical front face. On the Nov 8 scans this lands on the lit OLED
OFFSET = (0.0162, -0.0465)
SCREEN = (0.022, 0.011)
# The camera 17 cm out on a line this far above the screen's normal, the first that passes view_qs' checks. The window's
# top edge hides the screen's top line more the steeper the view (at 58 deg only the time showed), but the camera looks
# ~27 deg steeper than the jaw points and the wrist can't raise it past ~40: lower lines are out of reach with the
# camera on top (and with it under, the screen falls outside the photo). On 8 saved scans' placements 40 passed on 5,
# 45 on all; the jaw tip then stays 48+ mm off the device
ELEVATIONS, DISTANCE = [math.radians(e) for e in (40, 45, 50)], 0.17
MAX_AIM_ERR_DEG = 20       # how far the camera may point off that line: the screen stays well inside the photo
WAYPOINT_UP = 0.04
TIP_CLEAR = 0.03           # the jaw tip's least distance from the device, on the way and at the view
DESK_CLEAR = 0.02
CROP = (0.06, 0.036)       # the photo cut to this much of the front face around the screen,
CROP_WIDTH = 640           # then scaled to this many pixels across: ~440 from the view, small for a model to read
UP = np.array([0.0, 0.0, 1.0])


def display_part(parts, plane_T):
    """The display as a features.Part (z: out of the front face, toward the arm), or None with no button to place it by.
    STOP is halfway between the outermost buttons, which holds with START or TIME+ missing as long as the other two
    are there."""
    row = sorted([p for p in parts if p.kind == "button"], key=lambda p: p.pos[1])
    if not row:
        return None
    o, n = plane_T[:3, 3], plane_T[:3, 2]
    mid = (row[0].pos + row[-1].pos) / 2
    under = mid - ((mid - o) @ n) * n
    face = np.array([n[0], n[1], 0.0]) / np.linalg.norm(n[:2])
    c = under + OFFSET[0] * face + OFFSET[1] * UP
    T = features.frame(c, face, np.cross(UP, face))
    return features.Part("display", "display", T, np.array([SCREEN[0], SCREEN[1], 0.0005]),
                         meta={"name": "display", "source": "cad"})


def view_qs(arm, part, plane_T):
    """The joint moves from home to the view, and why not ("" if fine), at the first of ELEVATIONS that passes."""
    for elevation in ELEVATIONS:
        qs, why = _view_qs(arm, part, plane_T, elevation)
        if not why:
            break
    return qs, why


def _view_qs(arm, part, plane_T, elevation, steps=60):
    """The camera on the line `elevation` above the screen's normal, DISTANCE out, pointed along it as well as it goes,
    reached through a pose WAYPOINT_UP above (one joint move from home swung the jaw tip to 12 mm off the panel).
    Refused: IK short of a pose, the camera off the line by more than MAX_AIM_ERR_DEG, the wrist rolled off home (the
    camera would be beside the jaw), or the jaw tip within TIP_CLEAR of the device (the wedge of the front face and the
    panel's plane) or DESK_CLEAR of the desk anywhere on skills.move_joints' paths."""
    site, c, face = arm.m.site("wrist_cam").id, part.pos, part.normal
    line = -face * math.cos(elevation) - UP * math.sin(elevation)
    qs = []
    for up in (WAYPOINT_UP, 0.0):
        q, ok, err, ang = arm.ik.solve(c - DISTANCE * line + up * UP, line, arm.home_q, site=site)
        if err > 1e-3:
            return qs, f"camera {err * 1000:.0f} mm short of its pose"
        if ang > MAX_AIM_ERR_DEG or abs(q[4] - arm.home_q[4]) > 1e-3:
            return qs, f"camera points {ang:.0f} deg off the screen, wrist roll {math.degrees(q[4]):.0f} deg"
        qs.append(q)
    for a, b in zip([arm.home_q] + qs, qs):
        for s in 0.5 - 0.5 * np.cos(np.pi * np.linspace(0, 1, steps)):
            tip = arm.ik.fk(a + s * (b - a))[0]
            clear = max((tip - c) @ face, (tip - plane_T[:3, 3]) @ plane_T[:3, 2])
            if clear < TIP_CLEAR:
                return qs, f"jaw tip {clear * 1000:.0f} mm from the device on the way"
            if tip[2] < getattr(arm, "table_z", 0.0) + DESK_CLEAR:
                return qs, f"jaw tip {tip[2] * 1000:.0f} mm over the desk"
    return qs, ""


def crop(frame, part):
    """frame (rig.Frame) cut to CROP around the screen and turned in quarter turns so up on the device is up in the
    picture, or None if the screen is out of it."""
    inv = np.linalg.inv(frame.T_base_cam)
    side = np.cross(UP, part.normal)
    pts = [part.pos + a * CROP[0] / 2 * side + b * CROP[1] / 2 * UP for a in (-1, 1) for b in (-1, 1)] + [part.pos + 0.01 * UP]
    P = (inv @ np.c_[np.array(pts), np.ones(len(pts))].T)[:3]
    px = (frame.K @ (P / P[2]))[:2].T
    h, w = frame.rgb.shape[:2]
    (x0, y0), (x1, y1) = np.clip(px[:4].min(0), 0, [w, h]).astype(int), np.clip(px[:4].max(0), 0, [w, h]).astype(int)
    out = frame.rgb[y0:y1, x0:x1]
    if out.size == 0:
        return None
    du, dv = px[4] - px[:4].mean(0)  # which way device-up points in the picture
    if abs(du) > abs(dv):
        out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE if du < 0 else cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif dv > 0:
        out = cv2.rotate(out, cv2.ROTATE_180)
    return cv2.resize(out, None, fx=CROP_WIDTH / out.shape[1], fy=CROP_WIDTH / out.shape[1], interpolation=cv2.INTER_CUBIC)
