"""Face frames on the shell. Device frame: x across (left to right seen from the front), y from front to back,
z up, origin at the bottom front left corner. Each face has an origin at its centre and axes u (right, seen
from outside), v (up the face) and n (outward normal), with u x v = n."""
from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq
import numpy as np

from .spec import Shell

SIDE_AXES = {                     # outward normal, u axis
    "front": ((0, -1, 0), (1, 0, 0)),
    "back": ((0, 1, 0), (-1, 0, 0)),
    "left": ((-1, 0, 0), (0, -1, 0)),
    "right": ((1, 0, 0), (0, 1, 0)),
}


@dataclass
class Frame:
    name: str
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    n: np.ndarray
    half: tuple = (0.0, 0.0)          # approximate half sizes of the flat face (u, v)

    def plane(self, du: float = 0.0, dv: float = 0.0) -> cq.Plane:
        o = self.origin + self.u * du + self.v * dv
        return cq.Plane(origin=tuple(o), xDir=tuple(self.u), normal=tuple(self.n))


def slope_drop(shell: Shell) -> float:
    s = shell.slope
    return s.run * math.tan(math.radians(s.angle)) if s else 0.0


def frames(shell: Shell) -> dict[str, Frame]:
    W, D, H = shell.size
    side_mid = {"front": (W / 2, 0, H / 2), "back": (W / 2, D, H / 2),
                "left": (0, D / 2, H / 2), "right": (W, D / 2, H / 2)}
    out = {}
    side_half = {"front": W / 2, "back": W / 2, "left": D / 2, "right": D / 2}
    for name, (n, u) in SIDE_AXES.items():
        n, u = np.array(n, float), np.array(u, float)
        out[name] = Frame(name, np.array(side_mid[name], float), u, np.cross(n, u), n, (side_half[name], H / 2))
    out["top"] = Frame("top", np.array((W / 2, D / 2, H), float), np.array((1.0, 0, 0)), np.array((0, 1.0, 0)),
                       np.array((0, 0, 1.0)), (W / 2, D / 2))
    s = shell.slope
    if s:
        drop = slope_drop(shell)
        side = out[s.side]
        ns = side.n
        z = np.array((0, 0, 1.0))
        top_edge_mid = side.origin.copy()
        top_edge_mid[2] = H
        a = math.radians(s.angle)
        n = ns * math.sin(a) + z * math.cos(a)
        origin = top_edge_mid - ns * (s.run / 2) - z * (drop / 2)
        out["slope"] = Frame("slope", origin, side.u.copy(), np.cross(n, side.u), n,
                             (side.half[0], math.hypot(s.run, drop) / 2))
        side.origin = side.origin.copy()
        side.origin[2] = (H - drop) / 2                       # the side face is shorter now
        side.half = (side.half[0], (H - drop) / 2)
        top = out["top"]
        top.origin = top.origin - ns * (s.run / 2)            # and the top face shallower
        top.half = (top.half[0] - s.run / 2, top.half[1]) if s.side in ("left", "right") else \
            (top.half[0], top.half[1] - s.run / 2)
    return out


def make_shell(shell: Shell, fr: dict[str, Frame]) -> cq.Shape:
    """Hollow box, open at the bottom (for assembly), with the optional slope cut off."""
    W, D, H = shell.size
    w = shell.wall
    big = 4 * max(W, D, H)
    outer = cq.Workplane("XY").box(W, D, H, centered=False).val()
    inner = cq.Workplane("XY").transformed(offset=(w, w, -1)).box(W - 2 * w, D - 2 * w, H - w + 1,
                                                                    centered=False).val()
    if shell.slope:
        f = fr["slope"]
        cut = cq.Workplane(f.plane()).box(big, big, big, centered=(True, True, False)).val()
        inner_plane = cq.Plane(origin=tuple(f.origin - f.n * w), xDir=tuple(f.u), normal=tuple(f.n))
        cut_in = cq.Workplane(inner_plane).box(big, big, big, centered=(True, True, False)).val()
        outer = outer.cut(cut)
        inner = inner.cut(cut_in)
    return outer.cut(inner).clean()


PICO_HOLES = (47.0, 11.4)


def make_base(shell: Shell) -> tuple[cq.Shape, dict[str, cq.Shape]]:
    """Base plate (device frame, under the shell) and the desk fixture corners. Returns (base, fixture parts)."""
    from .geom import block, cyl
    b = shell.base
    W, D, _ = shell.size
    w = shell.wall
    base = cq.Workplane("XY").box(W, D, b.flange, centered=False).translate((0, 0, -b.flange)).val()
    plug = block((W - 2 * w) / 2 - b.fit, (D - 2 * w) / 2 - b.fit, 0, b.plug, cu=W / 2, cv=D / 2)
    plug = plug.cut(block((W - 2 * w) / 2 - b.fit - 2.4, (D - 2 * w) / 2 - b.fit - 2.4, 0.01, b.plug + 1,
                          cu=W / 2, cv=D / 2))                      # a rim, not a solid block
    base = base.fuse(plug)
    if b.board == "pico":
        hx, hy = (PICO_HOLES[1], PICO_HOLES[0]) if b.board_rot else PICO_HOLES
        for sx in (-hx / 2, hx / 2):
            for sy in (-hy / 2, hy / 2):
                cx, cy = W / 2 + b.board_u + sx, D / 2 + b.board_v + sy
                base = base.fuse(cyl(2.5, -0.01, 5.0, cx, cy)).cut(cyl(0.9, -1.0, 5.1, cx, cy))
    peg_at = [(15.0, 15.0), (W - 15.0, D - 15.0)]
    fixture = {}
    if b.fixture:
        for i, (px, py) in enumerate(peg_at):
            base = base.cut(cyl(3.2, -b.flange - 0.1, -b.flange + 3.0, px, py))
            # corner piece: plate under the base corner, fence outside the box, peg up into the base
            sx, sy = (1, 1) if i == 0 else (-1, -1)
            cx, cy = (0.0, 0.0) if i == 0 else (W, D)
            plate = block(19, 19, -b.flange - 3, -b.flange, cu=cx + sx * 13, cv=cy + sy * 13)
            fence = fuse_all([block(3, 19, -b.flange - 3, -b.flange + 6, cu=cx - sx * 3.5, cv=cy + sy * 13),
                              block(19, 3, -b.flange - 3, -b.flange + 6, cu=cx + sx * 13, cv=cy - sy * 3.5)])
            peg = cyl(3.0, -b.flange - 0.01, -b.flange + 2.5, px, py)
            fixture[f"fixture_{i + 1}"] = fuse_all([plate, fence, peg])
    return base.clean(), fixture


def fuse_all(shapes):
    out = shapes[0]
    for s in shapes[1:]:
        out = out.fuse(s)
    return out.clean()
