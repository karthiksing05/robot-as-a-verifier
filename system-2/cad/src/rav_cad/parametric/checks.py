"""Kernel checks, run before anything is printed. Each returns a row: name, ok, detail.

Geometric checks catch geometry mistakes, not functional ones; the robot test is what tells whether a part works.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import numpy as np

from .build import Built
from .features import PRESSABLE
from .geom import distance, overlap_volume

TOUCH_EPS = 0.01        # mm^3 of overlap we treat as touching, not colliding


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _rect_gap(a, b) -> float:
    """Gap between two (cu, cv, hu, hv) rectangles; negative if they overlap."""
    return max(abs(a[0] - b[0]) - a[2] - b[2], abs(a[1] - b[1]) - a[3] - b[3])


def _on_face(f, p):
    """A feature's (cu, cv) on its face, plus a local rect offset."""
    return lambda r: (p.feature.u + r[0], p.feature.v + r[1], r[2], r[3])


def run(b: Built, interference: bool = True) -> list[Check]:
    s, lim = b.spec, b.spec.limits
    rows: list[Check] = []
    add = lambda name, ok, detail="": rows.append(Check(name, bool(ok), detail))   # noqa: E731

    add("spec builds", not b.errors, "; ".join(b.errors))
    for fid, p in b.placed.items():
        add(f"{fid}: design rules", not p.geom.problems, "; ".join(p.geom.problems))

    bad = [n for n, sh in b.pieces().items() if not sh.isValid()]
    add("solids valid", not bad, ", ".join(bad))

    bb = b.assembly().BoundingBox()
    size = (bb.xlen, bb.ylen, bb.zlen)
    add("size within limits", all(a <= m + 1e-6 for a, m in zip(size, lim.max_size)),
        f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm (max {lim.max_size[0]:g} x {lim.max_size[1]:g} x "
        f"{lim.max_size[2]:g})")

    ledge_t = s.shell.wall - s.shell.insert_t
    add("wall thickness", s.shell.wall >= lim.min_wall and ledge_t >= lim.min_wall,
        f"wall {s.shell.wall:g} mm, ledge under inserts {ledge_t:g} mm, min {lim.min_wall:g}")
    if s.shell.slope:
        from .faces import slope_drop
        W, D, H = s.shell.size
        span = D if s.shell.slope.side in ("front", "back") else W
        drop = slope_drop(s.shell)
        add("slope fits the box", s.shell.slope.run < span - 2 * s.shell.wall and drop < H - 2 * s.shell.wall,
            f"run {s.shell.slope.run:g} mm, drop {drop:.1f} mm")

    # every footprint lies on its face, with a margin to the edge (tested against the real solid)
    for fid, p in b.placed.items():
        hu, hv = p.geom.half
        m = lim.edge_margin + s.shell.insert_fit
        off = []
        for cu in (-hu - m, hu + m):
            for cv in (-hv - m, hv + m):
                below = p.plane.toWorldCoords((cu, cv, -0.3))
                above = p.plane.toWorldCoords((cu, cv, 0.3))
                if not b.shell_raw.isInside(below) or b.shell_raw.isInside(above):
                    off.append(f"({cu:+.0f},{cv:+.0f})")
        add(f"{fid}: on its face", not off,
            f"corners off the '{p.feature.face}' face or within {lim.edge_margin:g} mm of its edge: {' '.join(off)}"
            if off else "")

    same_face = [(a, c) for a, c in combinations(b.placed.values(), 2) if a.feature.face == c.feature.face]
    # inserts keep a web between them
    for a, c in same_face:
        web = _rect_gap((a.feature.u, a.feature.v, *a.geom.half), (c.feature.u, c.feature.v, *c.geom.half)) \
            - 2 * s.shell.insert_fit
        if web < lim.min_web:
            add(f"{a.feature.id} / {c.feature.id}: spacing", False, f"{web:.1f} mm between inserts, min {lim.min_web:g}")

    # room for the fingertip: what it touches on one control stays clear of what it touches on the next
    need = lim.fingertip_d / 2 + lim.aim_margin
    for a, c in same_face:
        if a.geom.touch is None or c.geom.touch is None:
            continue
        gap = _rect_gap(_on_face(a.feature, a)(a.geom.touch), _on_face(c.feature, c)(c.geom.touch))
        if gap < need:
            add(f"{a.feature.id} / {c.feature.id}: fingertip room", False,
                f"{gap:.1f} mm between them; a {lim.fingertip_d:g} mm fingertip with {lim.aim_margin:g} mm aim "
                f"error needs {need:g}")

    # a bare flat patch on every face with pressable controls, for the touch taps that locate the panel
    r = lim.bare_patch / 2
    for face in sorted({p.feature.face for p in b.placed.values() if p.feature.type in PRESSABLE}):
        fr = b.frames[face]
        rects = [(p.feature.u, p.feature.v, p.geom.half[0] + s.shell.insert_fit, p.geom.half[1] + s.shell.insert_fit)
                 for p in b.placed.values() if p.feature.face == face]
        lo_u, lo_v = -fr.half[0] + r + lim.edge_margin, -fr.half[1] + r + lim.edge_margin
        found = None
        for u in np.arange(lo_u, -lo_u + 1e-9, 2.0):
            for v in np.arange(lo_v, -lo_v + 1e-9, 2.0):
                if all(_rect_gap((u, v, r, r), q) >= 0 for q in rects):
                    found = (u, v)
                    break
            if found:
                break
        add(f"{face}: bare patch for touch taps", found is not None,
            f"free {lim.bare_patch:g} mm circle at u={found[0]:.0f}, v={found[1]:.0f}" if found else
            f"no free {lim.bare_patch:g} mm circle on the '{face}' face; leave some bare panel")

    # sliding clearance, measured from the geometry, not read back from the parameter
    lo, hi = lim.clearance_range
    for fid, p in b.placed.items():
        if p.geom.clearance is None or p.slider is None:
            continue
        c = p.geom.clearance
        measured = distance(p.slider, p.insert)
        ok = abs(measured - c) <= lim.clearance_tol and lo <= c <= hi
        add(f"{fid}: clearance", ok, f"designed {c:.3f} mm, measured {measured:.3f} mm, allowed {lo:g}-{hi:g}")

    if interference:
        for fid, p in b.placed.items():
            hits = []
            fixed = {"insert": p.insert, **p.extras}
            for name, solid in fixed.items():
                if overlap_volume(solid, b.shell) > TOUCH_EPS:
                    hits.append(f"{name}/shell")
            if p.moving is not None:
                if overlap_volume(p.moving, b.shell) > TOUCH_EPS:
                    hits.append("moving/shell")
                for name, solid in fixed.items():
                    if overlap_volume(p.moving, solid) > TOUCH_EPS:
                        hits.append(f"moving/{name}")
            for name, hw in p.hardware.items():
                for other_name, other in [("shell", b.shell), ("moving", p.moving), *fixed.items()]:
                    if other is not None and overlap_volume(hw, other) > TOUCH_EPS:
                        hits.append(f"{name}/{other_name}")
            if b.base is not None:
                for name, solid in [("insert", p.insert), ("moving", p.moving), *p.extras.items(),
                                    *p.hardware.items()]:
                    if solid is not None and overlap_volume(solid, b.base) > TOUCH_EPS:
                        hits.append(f"{name}/base")
            add(f"{fid}: no interference", not hits, ", ".join(hits))
        if b.base is not None:
            add("base fits the shell", overlap_volume(b.base, b.shell) <= TOUCH_EPS)

        # doors swing open without hitting the shell
        for fid, p in b.placed.items():
            if not p.geom.swing:
                continue
            pt, d, max_deg = p.geom.swing
            a0 = p.plane.toWorldCoords(pt)
            a1 = p.plane.toWorldCoords(tuple(np.add(pt, d)))
            body = p.moving.fuse(p.insert)
            hit = [deg for deg in (15, 35, 60, 90) if deg <= max_deg and
                   overlap_volume(body.rotate(a0, a1, deg), b.shell) > TOUCH_EPS]
            add(f"{fid}: swings open", not hit, f"hits the shell at {hit} degrees" if hit else "clear to 90 degrees")
    return rows


def ok(rows: list[Check]) -> bool:
    return all(r.ok for r in rows)


def table(rows: list[Check]) -> str:
    w = max(len(r.name) for r in rows)
    return "\n".join(f"{'ok  ' if r.ok else 'FAIL'}  {r.name:<{w}}  {r.detail}" for r in rows)


def as_json(rows: list[Check]) -> list[dict]:
    return [asdict(r) for r in rows]
