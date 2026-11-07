"""Fixed features with no sliding fit: window (a display, optionally with mounting posts for a common module) and
handle (pinch tab or pull bar). They are still inserts, so a shape change (tab -> bar) reprints only the insert."""
from __future__ import annotations

from ..geom import Ctx, FeatureGeom, block, cyl, fuse, keyed_outline, prism

# Common display modules. Sizes are typical datasheet values: measure yours with calipers and override.
#   pcb: board size; holes: mounting-hole spacing (centred); hole_d: pilot for a self-tapping screw;
#   front: the part that sits in the window (LCD frame / OLED glass); front_h: how far it stands off the board.
MODULES = {
    "lcd1602": dict(pcb=(80.0, 36.0), holes=(75.0, 31.0), hole_d=2.6, front=(71.5, 24.5), front_h=7.0),
    "oled096": dict(pcb=(27.5, 28.0), holes=(23.0, 23.5), hole_d=1.8, front=(26.8, 19.5), front_h=1.6),
}
WINDOW = dict(module="none", open_u=60.0, open_v=30.0, margin=5.0, standoff_d=5.0)
HANDLE = dict(style="tab", length=30.0, thick=3.0, height=15.0, bar_gap=18.0, margin=5.0, plate_v=18.0)


def window(p: dict, ctx: Ctx) -> FeatureGeom:
    t = ctx.t
    mod = MODULES.get(p["module"]) if p["module"] != "none" else None
    if p["module"] != "none" and mod is None:
        raise ValueError(f"window module must be one of none, {', '.join(MODULES)}; got {p['module']!r}")
    if mod:
        ou, ov = mod["front"][0] + 0.4, mod["front"][1] + 0.4
        half = (max(ou / 2 + p["margin"], mod["pcb"][0] / 2 + ctx.ledge + 1.5),
                max(ov / 2 + p["margin"], mod["pcb"][1] / 2 + ctx.ledge + 1.5))
    else:
        ou, ov = p["open_u"], p["open_v"]
        half = (ou / 2 + p["margin"], ov / 2 + p["margin"])
    insert = prism(keyed_outline(*half, ctx.key), -t, 0).cut(block(ou / 2, ov / 2, -t - 1, 1))
    info = {"open_mm": (ou, ov), "module": p["module"]}
    hardware = {}
    if mod:
        board_z = -max(mod["front_h"], t)                 # module front flush with the outside of the insert
        post_len = -board_z - t
        hu, hv = mod["holes"][0] / 2, mod["holes"][1] / 2
        for su in (-hu, hu):
            for sv in (-hv, hv):
                if post_len > 0.05:
                    insert = insert.fuse(cyl(p["standoff_d"] / 2, board_z, -t + 0.01, su, sv))
                insert = insert.cut(cyl(mod["hole_d"] / 2, board_z - 1, -t + (0 if post_len > 0.05 else 1.0), su, sv))
        hardware["display"] = fuse(block(mod["pcb"][0] / 2, mod["pcb"][1] / 2, board_z - 1.6, board_z),
                                   block(mod["front"][0] / 2, mod["front"][1] / 2, board_z, board_z + mod["front_h"]))
        info.update(board_depth_mm=-board_z, posts_mm=post_len)
    problems = [] if min(half[0] - ou / 2, half[1] - ov / 2) - ctx.ledge >= 1 else \
        ["window margin must exceed the ledge, or the shell hides the display"]
    return FeatureGeom(insert=insert.clean(), half=half, pieces={"insert": insert.clean()}, hardware=hardware,
                       waypoints={"centre": (0, 0, 0)}, info=info, problems=problems)


def handle(p: dict, ctx: Ctx) -> FeatureGeom:
    L = p["length"]
    half = (L / 2 + p["margin"], p["plate_v"] / 2)        # same pocket for every style, so tab -> bar is insert-only
    problems = []
    if p["style"] == "tab":                               # needs a pinch: the Rev A "no-thumbs" fault
        h = p["height"]
        body = block(L / 2, p["thick"] / 2, -0.01, h)
        grasp = (0, 0, h - 3)
        touch = (0, 0, L / 2, p["thick"] / 2)
        info = {"style": "tab", "height_mm": h, "needs": "pinch"}
    elif p["style"] == "bar":                             # a fingertip hooks behind it: no pinch needed
        post = 3.0
        h = p["bar_gap"] + 2 * post
        body = fuse(block(post, post, -0.01, h, cu=-(L / 2 - post)), block(post, post, -0.01, h, cu=L / 2 - post),
                    block(L / 2, post, h - 2 * post, h))
        grasp = (0, 0, p["bar_gap"] / 2)                  # fingertip centre, behind the bar
        touch = (0, 0, L / 2, post)
        span = L - 4 * post
        info = {"style": "bar", "height_mm": h, "gap_mm": p["bar_gap"], "span_mm": span, "needs": "hook pull"}
        need = ctx.fingertip_d + 4
        if p["bar_gap"] < need or span < need:
            problems.append(f"bar opening {span:.0f} x {p['bar_gap']:.0f} mm is too small for the "
                            f"{ctx.fingertip_d:g} mm fingertip to hook (need {need:g} each way)")
    elif p["style"] == "push_latch":                      # a flat pad: push and the door's push latch releases
        pad_r = min(half[1] - 1.0, L / 2)
        h = 3.0
        body = cyl(pad_r, -0.01, h)
        grasp = (0, 0, h)
        touch = (0, 0, pad_r, pad_r)
        info = {"style": "push_latch", "height_mm": h, "pad_d_mm": 2 * pad_r, "needs": "flat push",
                "note": "needs a push-to-open latch in the frame (bought part) instead of the magnet catch"}
        if 2 * pad_r < ctx.fingertip_d + 2:
            problems.append(f"push pad ({2 * pad_r:.0f} mm) is smaller than the fingertip; raise plate_v")
    else:
        raise ValueError(f"handle style must be 'tab', 'bar' or 'push_latch', got {p['style']!r}")
    if half[1] < max(p["thick"] / 2, 3.0) + ctx.min_wall + 1:
        problems.append("plate_v is too small for the handle body")
    insert = fuse(prism(keyed_outline(*half, ctx.key), -ctx.t, 0), body)
    return FeatureGeom(insert=insert, half=half, pieces={"insert": insert}, touch=touch,
                       waypoints={"approach": (grasp[0], grasp[1] - 25, grasp[2]), "grasp": grasp},
                       info=info, problems=problems)
