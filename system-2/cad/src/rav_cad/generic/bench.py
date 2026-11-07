"""Our CadQuery appliance as a generic product: named parts in the device frame, and the Tags its build implies.

This is the offline bench for the generic checks (no Onshape, no network), and it lets the CadQuery fallback be
judged by the same checks as an Onshape model.
"""
from __future__ import annotations

import cadquery as cq
import numpy as np

from ..parametric.build import Built
from .tags import Tags


def parts(b: Built) -> dict[str, cq.Shape]:
    """Named solids in the device frame at rest: 'shell', 'base', '<id> insert', '<id> moving', '<id> <extra>'."""
    out = {"shell": b.shell}
    if b.base is not None:
        out["base"] = b.base
    for fid, p in b.placed.items():
        out[f"{fid} insert"] = p.insert
        if p.moving is not None:
            out[f"{fid} moving"] = p.moving
        for k, s in p.extras.items():
            out[f"{fid} {k}"] = s
    return out


def tags(b: Built, **overrides) -> Tags:
    """The tag file a person would write for this build: controls, motion, contact and approach from its waypoints."""
    return Tags.from_dict(tags_dict(b, **overrides))


def tags_dict(b: Built, **overrides) -> dict:
    """tags() as the plain data a YAML tag file holds."""
    controls = {}
    for fid, p in b.placed.items():
        world = lambda xyz: [float(c) for c in p.plane.toWorldCoords(tuple(xyz)).toTuple()]   # noqa: E731
        wp = {k: np.array(world(v)) for k, v in p.geom.waypoints.items()}
        plain = lambda v: [round(float(c), 6) for c in v]   # noqa: E731
        names = [f"{fid} insert"] + ([f"{fid} moving"] if p.moving is not None else []) + [f"{fid} {k}" for k in p.extras]
        normal = np.array(p.plane.zDir.toTuple())
        if p.geom.swing:                                          # a door: pulled open about its hinge
            pt, d, deg = p.geom.swing
            o = np.array(world((0, 0, 0)))
            controls[fid] = {
                "skill": "pull", "parts": names, "moving": [f"{fid} insert", f"{fid} moving"],
                "motion": {"type": "revolve", "point": plain(world(pt)), "axis": plain(np.array(world(d)) - o), "degrees": float(deg)},
                "contact": plain(wp["grasp"]), "approach": plain(wp["grasp"] - wp["approach"]), "pull": plain(normal)}
        elif "contact" in wp and p.moving is not None:            # pressed, slid or turned along the face normal
            travel = float(p.geom.info.get("travel_mm", 0.0))
            controls[fid] = {
                "skill": "press", "parts": names, "moving": [f"{fid} moving"],
                "motion": {"type": "slide", "axis": plain(-normal), "travel": travel},
                "contact": plain(wp["contact"]), "approach": plain(wp["contact"] - wp["approach"]),
                "fit": [f"{fid} moving", f"{fid} insert"] if p.geom.clearance is not None else None}
    d = {"fixed": ["shell", "base"] if b.base is not None else ["shell"], "fingertip_d": float(b.spec.limits.fingertip_d),
         "min_clearance": 0.3, "min_wall": float(b.spec.limits.min_wall), "controls": controls}
    d.update(overrides)
    return d
