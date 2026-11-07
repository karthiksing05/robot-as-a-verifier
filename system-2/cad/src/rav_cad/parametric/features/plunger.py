"""Plunger-type controls: button, push_latch, dial.

Pieces: an insert plate with a bore and a guide sleeve; a cap (glued onto the stem from above); a stem with a
stop lip (put in from below); and, for buttons, a switch holder glued under the sleeve that holds a 6x6 mm
tactile switch. The switch is what tells the microcontroller the button was pressed, and its spring pushes the
button back out.

At rest the lip rests against the holder's ring (or the sleeve, with no switch). Pressing first closes a small
gap, then presses the switch; the switch bottoms out before the cap reaches the plate. The sliding clearance
(stem to bore, per side) is the parameter the demo fault and its fix change. It lives only in the insert, so the
cap the camera sees, the stem and the holder never change when clearance is patched.
"""
from __future__ import annotations

import cadquery as cq

from ..geom import Ctx, FeatureGeom, block, fuse, keyed_outline, prism, xsec

TACT6 = dict(body=6.0, body_h=3.5, act_d=3.5, total_h=5.0, travel=0.25)   # 6x6x5 mm tactile switch

COMMON = dict(clearance=0.40, guide=5.0, lip=2.0, lip_t=1.5, sleeve_wall=2.0, margin=4.0,
              switch="none", switch_gap=0.4, ring_t=1.2, holder_wall=1.6, floor_t=1.2)
BUTTON = dict(shape="round", cap_d=16.0, proud=7.0, travel=1.2, stem_d=6.0, **{**COMMON, "switch": "tact6"})
PUSH_LATCH = dict(shape="rect", cap_u=18.0, cap_v=10.0, proud=6.0, travel=3.0, stem_u=10.0, stem_v=5.0, **COMMON)
DIAL = dict(shape="round", cap_d=24.0, proud=12.0, travel=1.6, stem_d=8.0, notch=True,
            **{**COMMON, "clearance": 0.30, "guide": 6.0})       # travel = axial float for a dial


def build(p: dict, ctx: Ctx) -> FeatureGeom:
    rnd = p["shape"] == "round"
    c, T, t, g = float(p["clearance"]), float(p["travel"]), ctx.t, float(p["guide"])
    if rnd:
        cap = (p["cap_d"] / 2, p["cap_d"] / 2)
        stem = (p["stem_d"] / 2, p["stem_d"] / 2)
    else:
        cap = (p["cap_u"] / 2, p["cap_v"] / 2)
        stem = (p["stem_u"] / 2, p["stem_v"] / 2)
    grow = lambda hs, d: (hs[0] + d, hs[1] + d)                          # noqa: E731
    bore = grow(stem, c)
    sleeve = grow(bore, p["sleeve_wall"])
    lip = grow(stem, p["lip"])                       # from the stem, so a clearance patch reprints only the insert
    half = grow(cap, p["margin"])
    hole = (half[0] - ctx.ledge, half[1] - ctx.ledge)                    # opening in the shell under the insert
    has_switch = p["switch"] == "tact6"
    problems = []

    plate = prism(keyed_outline(*half, ctx.key), -t, 0)
    zb = -t - g                                                          # bottom of the sleeve
    insert = plate.fuse(xsec(rnd, *sleeve, zb, -t + 0.01)).cut(xsec(rnd, *bore, zb - 1, 1)).clean()

    lip_top = zb - (p["ring_t"] if has_switch else 0.0)
    z_sb = lip_top - p["lip_t"]                                          # stem bottom at rest
    cap_s = xsec(rnd, *cap, T, p["proud"])
    if p.get("notch"):                                                   # pointer groove on a dial
        cap_s = cap_s.cut(block(cap[0] / 2, 0.8, p["proud"] - 1.0, p["proud"] + 1, cu=cap[0] / 2))
    stem_s = xsec(rnd, *stem, z_sb, T + 3)                               # 3 mm goes up into the cap
    lip_s = xsec(rnd, *lip, z_sb, lip_top)
    socket = xsec(rnd, *grow(stem, 0.1), T - 0.01, T + 3)
    moving = fuse(cap_s, stem_s, lip_s)                                  # rest pose
    pieces = {"insert": insert, "cap": cap_s.cut(socket), "stem": fuse(stem_s, lip_s)}
    extras, hardware = {}, {}
    contact = p["proud"]
    waypoints = {"approach": (0, 0, contact + 20), "contact": (0, 0, contact), "pressed": (0, 0, contact - T)}
    widest = [sleeve, lip]

    if has_switch:
        sw = TACT6
        z_act = z_sb - p["switch_gap"]                                   # actuator top
        z_bb = z_act - sw["total_h"]                                     # switch body bottom = holder floor top
        z_fb = z_bb - p["floor_t"]
        ring_in = grow(stem, 0.8)                                        # never touched by the stem at any clearance
        tube_in = (max(lip[0] + 0.6, sw["body"] * 0.71 + 0.2), max(lip[1] + 0.6, sw["body"] * 0.71 + 0.2))
        tube_out = grow(tube_in, p["holder_wall"])
        holder = xsec(rnd, *tube_out, z_fb, zb).cut(xsec(rnd, *tube_in, z_bb, lip_top)) \
            .cut(xsec(rnd, *ring_in, lip_top - 0.1, zb + 0.1))
        for su in (-3.25, 3.25):                                         # slots for the switch's legs
            holder = holder.cut(block(0.9, sw["body"] / 2 + 1.5, z_fb - 1, z_bb + 0.01, cu=su))
        extras["holder"] = holder.clean()
        pieces["holder"] = extras["holder"]
        hardware["switch"] = fuse(block(sw["body"] / 2, sw["body"] / 2, z_bb, z_bb + sw["body_h"]),
                                  cq.Workplane().workplane(offset=z_bb + sw["body_h"] - 0.01)
                                  .circle(sw["act_d"] / 2).extrude(sw["total_h"] - sw["body_h"] + 0.01).val())
        actuate = p["switch_gap"] + sw["travel"]
        waypoints["actuate"] = (0, 0, contact - actuate)
        waypoints["pressed"] = (0, 0, contact - actuate)
        widest.append(tube_out)
        if T < actuate + 0.1:
            problems.append(f"travel {T} mm ends before the switch clicks at {actuate:.2f} mm; increase travel")
        if (sleeve[0] - ring_in[0]) < 1.0:
            problems.append("sleeve too thin to glue the switch holder to")

    if p["proud"] < T + 2:
        problems.append(f"cap is only {p['proud'] - T:.1f} mm tall above its travel; make proud >= travel + 2")
    if p["lip"] < c + 0.6:
        problems.append(f"lip ({p['lip']} mm past the stem) is too small to stop at clearance {c}")
    if any(s > h - 0.3 for part in widest for s, h in zip(part, hole)):
        problems.append("sleeve, lip or switch holder is too big to pass through the shell opening; "
                        "enlarge cap or margin")
    if min(half[0] - bore[0], half[1] - bore[1]) < ctx.min_wall:
        problems.append("insert wall around the bore is below min_wall")

    return FeatureGeom(
        insert=insert, half=half, moving=moving, slider=stem_s, clearance=c, pieces=pieces,
        extras=extras, hardware=hardware, waypoints=waypoints, touch=(0, 0, cap[0], cap[1]),
        info={"cap_half_mm": cap, "proud_mm": p["proud"], "travel_mm": T, "bore_half_mm": bore,
              "shape": p["shape"], "switch": p["switch"]},
        problems=problems,
    )
