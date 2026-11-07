"""Slot-type controls: slider, toggle. An insert plate with a slot; a moving part made of a knob (glued on from
above) and a stem with a retainer plate (put in from below). The toggle is a short-throw slider with a tall
lever, not a pivoting rocker. Sliding clearance (stem to slot side, per side) is the patchable parameter."""
from __future__ import annotations

from ..geom import Ctx, FeatureGeom, block, fuse, keyed_outline, prism

COMMON = dict(axis="u", clearance=0.40, gap=0.8, ret_t=1.5, margin=5.0)
SLIDER = dict(slot_len=30.0, stem_w=4.0, knob_u=10.0, knob_v=8.0, knob_h=6.0, **COMMON)
TOGGLE = dict(slot_len=8.0, stem_w=3.0, knob_u=4.0, knob_v=6.0, knob_h=14.0, **COMMON)


def build(p: dict, ctx: Ctx) -> FeatureGeom:
    c, t, gap = float(p["clearance"]), ctx.t, float(p["gap"])
    L, sw0 = float(p["slot_len"]), float(p["stem_w"])
    sw = sw0 + 2 * c                                      # slot width
    sl = L + sw                                           # slot length, stem included
    ret_u, ret_v = max(p["knob_u"], sw0 + 6), sw0 + 7       # from the stem, so a clearance patch reprints only the insert
    half = ((L + sw0) / 2 + 1 + p["margin"], max(   # outer size never depends on clearance
        p["knob_v"], ret_v) / 2 + p["margin"])
    hole = (half[0] - ctx.ledge, half[1] - ctx.ledge)

    along_v = p["axis"] == "v"
    final_half = (half[1], half[0]) if along_v else half
    slot_cut = block(sw / 2, sl / 2, -t - 1, 1) if along_v else block(sl / 2, sw / 2, -t - 1, 1)
    insert = prism(keyed_outline(*final_half, ctx.key), -t, 0).cut(slot_cut).clean()   # key stays at +u+v
    knob = block(p["knob_u"] / 2, p["knob_v"] / 2, gap, gap + p["knob_h"])
    stem = block(sw0 / 2, sw0 / 2, -t - gap, gap + 2)
    ret = block(ret_u / 2, ret_v / 2, -t - gap - p["ret_t"], -t - gap)
    socket = block(sw0 / 2 + 0.1, sw0 / 2 + 0.1, gap - 0.01, gap + 2)
    moving = fuse(knob, stem, ret)                        # slot centre is already mid-travel

    problems = []
    if gap <= c + 0.05:
        problems.append(f"gap {gap} must exceed clearance {c}, or the knob rubs the plate")
    if L / 2 + ret_u / 2 > hole[0] - 0.3 or ret_v / 2 > hole[1] - 0.3:
        problems.append("retainer can't travel inside the shell opening; increase margin")
    if half[1] - sw / 2 < ctx.min_wall:
        problems.append("insert wall beside the slot is below min_wall")

    h = gap + p["knob_h"] / 2
    wp = {"approach": (-L / 2, 0, gap + p["knob_h"] + 20), "start": (-L / 2, 0, h), "end": (L / 2, 0, h)}
    slider = stem
    touch = (0, 0, L / 2 + p["knob_u"] / 2, p["knob_v"] / 2)       # the knob anywhere along its travel
    if along_v:                                           # moving parts and waypoints turn with the slot
        moving = moving.rotate((0, 0, 0), (0, 0, 1), 90)
        slider = slider.rotate((0, 0, 0), (0, 0, 1), 90)
        wp = {k: (-y, x, z) for k, (x, y, z) in wp.items()}
        touch = (0, 0, touch[3], touch[2])
    return FeatureGeom(insert=insert, half=final_half, moving=moving, slider=slider, clearance=c, touch=touch,
                       pieces={"insert": insert, "knob": knob.cut(socket), "stem": fuse(stem, ret)},
                       waypoints=wp, info={"slot_len_mm": L, "knob_mm": (p["knob_u"], p["knob_v"], p["knob_h"]),
                                           "axis": p["axis"]},
                       problems=problems)
