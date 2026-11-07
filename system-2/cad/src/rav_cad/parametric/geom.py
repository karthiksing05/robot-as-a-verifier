"""Small geometry helpers shared by the feature builders. Local feature frame: x = face u, y = face v,
z = outward normal, z = 0 on the outer face surface. An insert occupies z in [-t, 0]."""
from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq
from OCP.BRepExtrema import BRepExtrema_DistShapeShape


def keyed_outline(hu: float, hv: float, key: float) -> list[tuple[float, float]]:
    """Rectangle with one chamfered corner (+u, +v), so a part only fits its pocket one way round."""
    key = min(key, hu, hv)
    return [(-hu, -hv), (hu, -hv), (hu, hv - key), (hu - key, hv), (-hu, hv)]


def prism(pts, z0: float, z1: float) -> cq.Shape:
    return cq.Workplane("XY").workplane(offset=z0).polyline(pts).close().extrude(z1 - z0).val()


def block(hu: float, hv: float, z0: float, z1: float, cu: float = 0.0, cv: float = 0.0) -> cq.Shape:
    pts = [(cu - hu, cv - hv), (cu + hu, cv - hv), (cu + hu, cv + hv), (cu - hu, cv + hv)]
    return prism(pts, z0, z1)


def cyl(r: float, z0: float, z1: float, cu: float = 0.0, cv: float = 0.0) -> cq.Shape:
    return cq.Workplane("XY").workplane(offset=z0).center(cu, cv).circle(r).extrude(z1 - z0).val()


def xsec(round_: bool, hu: float, hv: float, z0: float, z1: float) -> cq.Shape:
    """A round (radius hu) or rectangular (half sizes hu, hv) prism between z0 and z1."""
    return cyl(hu, z0, z1) if round_ else block(hu, hv, z0, z1)


def distance(a: cq.Shape, b: cq.Shape) -> float:
    d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    d.Perform()
    return d.Value()


def overlap_volume(a: cq.Shape, b: cq.Shape) -> float:
    return abs(a.intersect(b).Volume())


def signature(s: cq.Shape) -> tuple:
    """Cheap geometric fingerprint, used to tell which parts a patch actually changed."""
    bb = s.BoundingBox()
    c = s.Center()                                         # catches a pocket that moved but kept its size
    return tuple(round(x, 4) for x in (s.Volume(), s.Area(), bb.xlen, bb.ylen, bb.zlen, c.x, c.y, c.z))


def fuse(*shapes: cq.Shape) -> cq.Shape:
    out = shapes[0]
    for s in shapes[1:]:
        out = out.fuse(s)
    return out.clean()


@dataclass
class Ctx:
    """Shell settings a feature needs: insert thickness, ledge, wall, fit, and the minimum wall from the limits."""
    t: float
    ledge: float
    key: float
    min_wall: float
    wall: float = 3.5
    fit: float = 0.2
    fingertip_d: float = 12.0


@dataclass
class FeatureGeom:
    insert: cq.Shape                          # local frame, installed position
    half: tuple[float, float]                 # insert half sizes (u, v): its footprint on the face
    moving: cq.Shape | None = None            # local frame, mid-travel pose, all moving pieces fused
    pieces: dict[str, cq.Shape] = field(default_factory=dict)   # printable pieces, local frame
    clearance: float | None = None            # designed sliding clearance, measured by the checks
    waypoints: dict[str, tuple] = field(default_factory=dict)   # local frame, rest pose
    info: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    slider: cq.Shape | None = None            # the part of `moving` that slides in the fit (clearance is measured on it)
    extras: dict[str, cq.Shape] = field(default_factory=dict)    # other fixed printed parts, installed (switch holder)
    hardware: dict[str, cq.Shape] = field(default_factory=dict)  # bought parts, for checks and the viewer only
    pocket: cq.Shape | None = None            # custom cut in the shell (default: keyed recess + opening)
    shell_add: list = field(default_factory=list)   # solids fused onto the shell (hinge knuckles, door stop)
    touch: tuple | None = None                # (cu, cv, hu, hv): the area the fingertip touches, local
    swing: tuple | None = None                # (point, direction, max_deg): moving part rotates about this axis
