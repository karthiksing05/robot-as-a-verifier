"""Which CAD control each control the robot found is, from where they are. A run names controls by what perception saw
(button_1, button_1_cad); the CAD's tag file names them by design (button_1, stop, lid). Neither knows the other's
names or the device's pose on the desk, so this finds the pose: the product sits upright, so a turn about vertical and a
shift take the robot's frame to the CAD's. It tries every turn, pins one robot control on one CAD control, and keeps the
pose that lines up the most controls (facing the same way, within TOL_MM), then refines the shift on those.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

TOL_MM = 8.0           # a control lands this close to its CAD contact point
FACING_COS = 0.85      # and faces within about 30 deg of it
KINDS = {"press": {"button"}}   # robot kinds a CAD skill can be


def _rz(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def _cad(tags: Any) -> list[dict]:
    out = []
    for cid, c in (tags.controls.items() if hasattr(tags, "controls") else tags["controls"].items()):
        get = (lambda k, c=c: getattr(c, k)) if hasattr(c, "skill") else c.get
        if get("contact") is None:
            continue
        approach = get("approach")
        out.append({"id": cid, "skill": get("skill"), "p": np.asarray(get("contact"), float),
                    "n": -np.asarray(approach, float) if approach is not None else None})
    return out


def register(scene: list[dict], tags: Any, step_deg: float = 1.0) -> dict:
    """{"matches": {robot id: CAD id}, "yaw_deg", "shift_mm", "residual_mm"}. Robot controls without a CAD control near
    them (a display, a toggle the tags don't cover, a false detection) are left out."""
    cad = _cad(tags)
    seen = [{"id": c["id"], "kind": c.get("kind"), "p": np.asarray(c["pos_mm"], float),
             "n": np.asarray(c["normal"], float) if c.get("normal") is not None else None} for c in scene if c.get("pos_mm") is not None]
    if not cad or not seen:
        return {"matches": {}, "yaw_deg": None, "shift_mm": None, "residual_mm": None}

    def ok_kind(s, c):
        return s["kind"] in KINDS.get(c["skill"], {s["kind"]})

    def ok_face(R, s, c):
        return s["n"] is None or c["n"] is None or float((R @ s["n"]) @ c["n"]) >= FACING_COS

    def assign(R, t):
        pairs, used = [], set()
        cand = sorted(((float(np.linalg.norm(R @ s["p"] + t - c["p"])), i, j) for i, s in enumerate(seen) for j, c in enumerate(cad)
                       if ok_kind(s, c) and ok_face(R, s, c)))
        taken_s = set()
        for d, i, j in cand:
            if d > TOL_MM or i in taken_s or j in used:
                continue
            pairs.append((i, j, d))
            taken_s.add(i)
            used.add(j)
        return pairs

    best = None
    for k in range(int(round(360 / step_deg))):
        yaw = k * step_deg
        R = _rz(yaw)
        for s in seen:
            for c in cad:
                if not (ok_kind(s, c) and ok_face(R, s, c)):
                    continue
                t = c["p"] - R @ s["p"]
                pairs = assign(R, t)
                score = (len(pairs), -sum(d for _, _, d in pairs))
                if best is None or score > best[0]:
                    best = (score, yaw, R, t, pairs)
    _, yaw, R, t, pairs = best
    if len(pairs) >= 2:   # refine the shift on everything that lined up
        t = np.mean([cad[j]["p"] - R @ seen[i]["p"] for i, j, _ in pairs], axis=0)
        pairs = assign(R, t)
    res = [float(np.linalg.norm(R @ seen[i]["p"] + t - cad[j]["p"])) for i, j, _ in pairs]
    return {"matches": {seen[i]["id"]: cad[j]["id"] for i, j, _ in pairs}, "yaw_deg": yaw,
            "shift_mm": [round(float(v), 2) for v in t], "residual_mm": round(max(res), 2) if res else None}
