"""Hinged door with a swappable handle insert.

- The opening is cut through the face. The door is a plate that sits in it with `gap` all round.
- Hinge: knuckles alternate between shell and door along one vertical edge, outside the face, with a hole for
  a 1.75 mm filament pin (or a pin of `pin_d`). The door swings outward.
- Stop and catch: a tab inside the frame on the free side stops the door from swinging in. A magnet in the tab
  and one in the door keep it shut, and a slot under the tab's magnet holds a reed switch, so the
  microcontroller knows when the door is open.
- Handle: a keyed insert in a recess on the door (`handle_*` params go to the handle builder). Its recess never
  depends on the style, so the tab -> bar fix reprints only the handle.
"""
from __future__ import annotations

import cadquery as cq

from ..geom import Ctx, FeatureGeom, block, cyl, fuse, keyed_outline, prism
from .fixed import HANDLE, handle

DOOR = dict(open_u=70.0, open_v=60.0, hinge="left", gap=0.5, knuckle_r=3.0, knuckles=3, knuckle_gap=0.4,
            pin_d=1.75, magnet_d=6.0, magnet_t=2.0, reed=True, handle_from_edge=8.0, handle_v=0.0,
            **{f"handle_{k}": v for k, v in HANDLE.items()})


def _cyl_v(r: float, v0: float, v1: float, u: float, z: float) -> cq.Shape:
    """Cylinder along the local v axis."""
    return cq.Solid.makeCylinder(r, v1 - v0, cq.Vector(u, v0, z), cq.Vector(0, 1, 0))


def build(p: dict, ctx: Ctx) -> FeatureGeom:
    ou, ov, g, k, w = p["open_u"], p["open_v"], p["gap"], p["knuckle_r"], ctx.wall
    if p["hinge"] not in ("left", "right"):
        raise ValueError(f"door hinge must be 'left' or 'right', got {p['hinge']!r}")
    problems = []

    # Built with the hinge on the left (-u); mirrored at the end for a right hinge.
    au, az = -ou / 2 - k, k                                   # hinge axis
    plate = block(ou / 2 - g, ov / 2 - g, -w, 0)
    n = int(p["knuckles"])
    span = ov - 2 * g
    seg = (span - (n - 1) * p["knuckle_gap"]) / n
    shell_k, door_k = [], []
    for i in range(n):
        v0 = -span / 2 + i * (seg + p["knuckle_gap"])
        kn = _cyl_v(k, v0, v0 + seg, au, az)
        if i % 2 == 0:                                        # shell knuckle, on a pad on the face
            shell_k.append(fuse(kn, block(k / 2, seg / 2, 0, az, cu=au - k / 2, cv=v0 + seg / 2)))
        else:                                                 # door knuckle, with a leaf onto the door plate
            leaf_end = -ou / 2 + g + 8
            door_k.append(fuse(kn, block((leaf_end - au) / 2, seg / 2, 0, az, cu=(au + leaf_end) / 2,
                                         cv=v0 + seg / 2)))
    pin = _cyl_v(p["pin_d"] / 2 + 0.15, -ov, ov, au, az)
    door = fuse(plate, *door_k).cut(pin)
    shell_add = [s.cut(pin) for s in shell_k]

    # stop tab with magnet and reed switch, inside the frame on the free side
    tab_u0, tab_u1, tab_t = ou / 2 - 9, ou / 2 + 3, 5.0
    mu = ou / 2 - 4.5
    tab = block((tab_u1 - tab_u0) / 2, 10, -w - tab_t, -w, cu=(tab_u0 + tab_u1) / 2)
    tab = tab.cut(cyl(p["magnet_d"] / 2 + 0.1, -w - p["magnet_t"] - 0.1, -w + 0.1, mu, 0))
    if p["reed"]:
        tab = tab.cut(block(1.3, 11, -w - tab_t - 0.1, -w - tab_t + 2.4, cu=mu))
    shell_add.append(tab)
    door = door.cut(cyl(p["magnet_d"] / 2 + 0.1, -w - 0.1, -w + p["magnet_t"] + 0.1, mu, 0))
    if w - p["magnet_t"] < 1.0:
        problems.append(f"door ({w} mm) is too thin over a {p['magnet_t']} mm magnet")

    # handle insert in a recess near the free edge
    hp = {key[len("handle_"):]: val for key, val in p.items() if key.startswith("handle_") and key[7:] in HANDLE}
    hg = handle(hp, ctx)
    hu = ou / 2 - g - p["handle_from_edge"] - hg.half[0]
    hv = p["handle_v"]
    recess = prism(keyed_outline(hg.half[0] + ctx.fit, hg.half[1] + ctx.fit, ctx.key), -ctx.t, 1).translate((hu, hv, 0))
    door = door.cut(recess).clean()
    handle_placed = hg.insert.translate((hu, hv, 0))
    problems += hg.problems
    if hu - hg.half[0] - ctx.fit < -ou / 2 + g + 8 + 2 or abs(hv) + hg.half[1] > ov / 2 - g - 2:
        problems.append("handle doesn't fit on the door; make the door bigger or the handle smaller")
    if w - ctx.t < 1.0:
        problems.append("door is too thin for the handle recess")

    gx, gy, gz = hg.waypoints["grasp"]
    ax, ay, az2 = hg.waypoints["approach"]
    wp = {"approach": (ax + hu, ay + hv, az2), "grasp": (gx + hu, gy + hv, gz)}
    t_cu, t_cv, t_hu, t_hv = hg.touch
    touch = (t_cu + hu, t_cv + hv, t_hu, t_hv)
    pocket = block(ou / 2, ov / 2, -w - 1, 1)
    half = (ou / 2 + 2 * k + 1, ov / 2 + 1)

    shapes = dict(door=door, handle=handle_placed, pocket=pocket)
    sign = -1.0                                              # rotation sign that swings a left-hinged door outward
    if p["hinge"] == "right":
        mir = lambda s: s.mirror("YZ")                       # noqa: E731
        shapes = {kk: mir(vv) for kk, vv in shapes.items()}
        shell_add = [mir(s) for s in shell_add]
        wp = {kk: (-x, y, z) for kk, (x, y, z) in wp.items()}
        touch = (-touch[0], touch[1], touch[2], touch[3])
        au, sign = -au, 1.0

    return FeatureGeom(
        insert=shapes["handle"], half=half, moving=shapes["door"],          # the swing check turns both
        pieces={"door": shapes["door"], "handle": hg.insert},
        pocket=shapes["pocket"], shell_add=shell_add, touch=touch, waypoints=wp,
        swing=((au, 0.0, az), (0.0, sign, 0.0), 95.0),
        hardware={},
        info={"opening_mm": (ou, ov), "hinge": p["hinge"], "handle": hg.info, "pin": f"{p['pin_d']} mm filament",
              "magnets": f"2 x {p['magnet_d']:g}x{p['magnet_t']:g} mm", "reed_switch": bool(p["reed"])},
        problems=problems,
    )
