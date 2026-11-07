"""CR-600 cuvette photometer, as build.py wants it: one assembly per revision, product frame, mm.

Origin on the base's bottom face, centred; +X toward the arm, +Z up. A grey printed housing: a vertical front panel
with the display, a control face sloped 45 deg toward the arm (POWER, BLANK, READ), and a flat deck with a square pit
in it. The sample slot is in the pit's floor; a cuvette standing in it ends just below the deck, with room round it
for fingers, and a flat black lid hinged at its back closes over the pit, light-tight. A cuvette stands in a holder on
the -Y side.

Every part is a plain convex solid where it collides (plates, boxes, cylinders), so nothing needs CoACD: the deck round
the pit is four plates, and the lid's hook lip two. Parts that differ between revisions carry _revA / _revB and are
tinted (Rev A orange, Rev B green), as the real kits print them. ref_* are electronics placeholders.
"""
import math

import cadquery as cq

S2 = math.sqrt(0.5)
N = (S2, 0.0, S2)                 # the control face's outward normal
FACE_C = 119.24                   # its outer surface: x + z = FACE_C (inner x + z = 115, 3 mm plate)

# revision-dependent dimensions (device.yaml's faults name the same choices)
REVS = {
    "A": {"slot_side": 11.6, "leaf_spacer": 7.0},   # slot printed under size; hinge leaf with a thick knuckle spacer
    "B": {"slot_side": 14.5, "leaf_spacer": 0.0},
}

COL = {
    "housing": (0.86, 0.87, 0.86, 1), "face": (0.24, 0.26, 0.30, 1), "lid": (0.12, 0.12, 0.13, 1),
    "cap_blank": (0.95, 0.95, 0.93, 1), "cap_read": (0.20, 0.40, 0.85, 1), "pla": (0.92, 0.92, 0.90, 1),
    "lcd": (0.08, 0.10, 0.10, 1), "cuvette": (0.85, 0.92, 0.97, 0.55), "steel": (0.6, 0.6, 0.62, 1),
}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

# where things are (device.yaml repeats these)
SLOT = (-9.0, 8.0)                # sample chamber centre, x, y
DECK_TOP = 90.0
PIT = (-31.0, 13.0, -14.0, 30.0, 76.0)          # pit x0, x1, y0, y1, floor top: 44 mm square, 14 deep
FLOOR_TOP = 44.0                  # the cuvette stands on this: its top is then 44 + 45 = 89, 1 mm under the deck
LID = (-34.0, 16.0, -17.0, 33.0, 90.0, 93.0)    # lid plate x0, x1, y0, y1, z0, z1: it rests on the deck
HINGE = (-56.0, 8.0, 104.0)        # lid hinge axis, along y: at the back of the deck, on long leaf arms
HOLDER = (20.0, -66.0)            # side holder centre; the cuvette stands on its base at z 30
HOLDER_FLOOR = 30.0
CUV = 12.5                        # cuvette outside, square
CUV_H = 45.0
BUTTONS = {"cap_1": -12.0, "cap_2": 14.0}          # BLANK, READ (y on the control face)
TOGGLE_Y = -40.0
FACE_S = (42.5, 76.74)            # x, z of the control row on the face's outer surface


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cyl_along(r, p0, d, length):
    return cq.Solid.makeCylinder(r, length, cq.Vector(*p0), cq.Vector(*d))


def xz_prism(pts, y0, y1):
    wire = cq.Wire.makePolygon([cq.Vector(x, y0, z) for x, z in pts], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(0, y1 - y0, 0))


def on_face(y, h):
    """A point on the control row, h mm out along the face's normal."""
    return (FACE_S[0] + h * N[0], y, FACE_S[1] + h * N[2])


def housing():
    p = {}
    p["base_plate"] = box(-62, 62, -54, 54, 0, 3)
    p["front_panel"] = box(57, 60, -52, 52, 3, 55)
    side = [(-60, 3), (60, 3), (60, 55), (28, 87), (-60, 87)]
    p["side_panel_L"] = xz_prism(side, -52, -49)
    p["side_panel_R"] = xz_prism(side, 49, 52)
    p["back_panel"] = box(-60, -57, -49, 49, 3, 87)
    face = xz_prism([(60, 55), (60 + 3 * S2, 55 + 3 * S2), (30.12, 89.12), (28, 87)], -52, 52)
    for y in BUTTONS.values():
        face = face.cut(cyl_along(5.6, on_face(y, -5), N, 10))
    face = face.cut(cyl_along(3.0, on_face(TOGGLE_Y, -5), N, 10))
    p["control_face"] = face
    x0, x1, y0, y1, pf = PIT
    p["deck_rear"] = box(-60, x0, -52, 52, 87, DECK_TOP)
    p["deck_front"] = box(x1, 29, -52, 52, 87, DECK_TOP)
    p["deck_left"] = box(x0, x1, -52, y0, 87, DECK_TOP)
    p["deck_right"] = box(x0, x1, y1, 52, 87, DECK_TOP)
    t = 3.0
    p["pit_wall_back"] = box(x0 - t, x0, y0 - t, y1 + t, pf, 87)
    p["pit_wall_front"] = box(x1, x1 + t, y0 - t, y1 + t, pf, 87)
    p["pit_wall_left"] = box(x0, x1, y0 - t, y0, pf, 87)
    p["pit_wall_right"] = box(x0, x1, y1, y1 + t, pf, 87)
    s = REVS["B"]["slot_side"] + 1.0
    p["pit_floor"] = box(x0 - t, x1 + t, y0 - t, y1 + t, pf - t, pf).cut(
        box(SLOT[0] - s / 2, SLOT[0] + s / 2, SLOT[1] - s / 2, SLOT[1] + s / 2, pf - 5, pf + 1))
    p["slot_floor"] = box(SLOT[0] - 12, SLOT[0] + 12, SLOT[1] - 12, SLOT[1] + 12, FLOOR_TOP - 3, FLOOR_TOP)
    p["slot_post"] = box(SLOT[0] - 5, SLOT[0] + 5, SLOT[1] - 5, SLOT[1] + 5, 3, FLOOR_TOP - 3)
    # bezels round the two caps and the toggle's bushing, on the face
    for name, y in (("bezel_blank", BUTTONS["cap_1"]), ("bezel_read", BUTTONS["cap_2"])):
        p[name] = cyl_along(7.5, on_face(y, 0), N, 1.2).cut(cyl_along(5.4, on_face(y, -1), N, 4))
    p["toggle_bushing"] = cyl_along(4.5, on_face(TOGGLE_Y, 0), N, 4.5)
    # display window frame on the front panel
    p["lcd_frame"] = box(60, 60.5, -22, 22, 23, 41)
    p["led_bezel"] = cq.Solid.makeCylinder(4.5, 0.6, cq.Vector(18, 42, DECK_TOP), cq.Vector(0, 0, 1))
    # lid hinge base, on the deck behind the lid
    hx, hy, hz = HINGE
    hb = box(hx - 4, hx + 2.5, hy - 12, hy + 12, DECK_TOP, hz)
    p["hinge_base"] = hb.fuse(cyl_along(4.0, (hx, hy - 12, hz), (0, 1, 0), 24)).clean()
    # side holder: a solid base the cuvette stands on, and a sleeve with a square bore above it
    cx, cy = HOLDER
    p["holder_base"] = box(cx - 12, cx + 12, cy - 12, -52, 0, HOLDER_FLOOR)
    p["holder_sleeve"] = box(cx - 12, cx + 12, cy - 12, cy + 12, HOLDER_FLOOR, 48).cut(
        box(cx - 7.25, cx + 7.25, cy - 7.25, cy + 7.25, HOLDER_FLOOR - 1, 50))
    return p


def moving():
    p = {}
    for name, y in BUTTONS.items():
        cap = cyl_along(5.0, on_face(y, -4.0), N, 7.5)                      # top at 3.5 mm out
        cap = cap.fuse(cyl_along(6.5, on_face(y, -4.5), N, 1.0)).clean()   # retaining flange under the face
        p[name] = cap
    x0, x1, y0, y1, z0, z1 = LID
    p["lid_plate"] = box(x0, x1, y0, y1, z0, z1)
    # hook lip on the lid's front edge: a riser and a lip 10 mm above the lid, reaching 10 mm toward the arm
    yc = (y0 + y1) / 2
    p["lid_lip_riser"] = box(x1 - 3, x1, yc - 8, yc + 8, z1, z1 + 10)
    p["lid_lip"] = box(x1 - 3, x1 + 10, yc - 8, yc + 8, z1 + 10, z1 + 12.2)
    return p


def lid_leaf(rev):
    """The lid's hinge leaf: a plate on the lid round the pin. Rev A's knuckle carries a spacer below it that lands
    on the hinge base before the lid is down."""
    hx, hy, hz = HINGE
    leaf = box(hx, LID[0] + 12, hy - 10, hy + 10, LID[5], LID[5] + 2)
    leaf = leaf.fuse(box(hx - 3, hx + 3, hy - 10, hy + 10, LID[5], hz))      # web up to the knuckle
    leaf = leaf.fuse(cyl_along(3.0, (hx, hy - 10, hz), (0, 1, 0), 20)).clean()
    sp = REVS[rev]["leaf_spacer"]
    if sp:
        leaf = leaf.fuse(box(hx - 3, hx + 3, hy - 10, hy + 10, LID[5] - sp, LID[5])).clean()
    return leaf


def slot_sleeve(rev):
    s = REVS[rev]["slot_side"]
    x, y = SLOT
    pf = PIT[4] - 3
    return box(x - 12, x + 12, y - 12, y + 12, FLOOR_TOP, pf).cut(box(x - s / 2, x + s / 2, y - s / 2, y + s / 2, FLOOR_TOP - 1, pf + 1))


def cuvette():
    cx, cy = HOLDER
    h = CUV / 2
    outer = box(cx - h, cx + h, cy - h, cy + h, HOLDER_FLOOR, HOLDER_FLOOR + CUV_H)
    return outer.cut(box(cx - h + 1.25, cx + h - 1.25, cy - h + 1.25, cy + h - 1.25, HOLDER_FLOOR + 1.5, HOLDER_FLOOR + CUV_H + 1))


def electronics():
    x, y = SLOT
    return {
        "ref_pico": box(-50, -29, -20, 31, 3, 7),
        "ref_lcd": box(54, 57, -18, 18, 22, 42),
        "ref_led": box(15, 21, 39, 45, 84, 87),
        "ref_cuvette_beam": box(x - 6, x + 6, y - 16, y + 16, 47, 55),
        "ref_lid_switch": box(-41.0, -33.0, 34, 40, 80, 87),
        "ref_switch_blank": cyl_along(5.5, on_face(BUTTONS["cap_1"], -11), N, 6),
        "ref_switch_read": cyl_along(5.5, on_face(BUTTONS["cap_2"], -11), N, 6),
    }


CONCAVE = []


def _assembly(rev):
    a = cq.Assembly(name=f"cr600_rev{rev}")
    colours = {"control_face": "face", "bezel_blank": "face", "bezel_read": "face", "toggle_bushing": "steel", "lcd_frame": "lcd",
               "led_bezel": "face", "hinge_base": "pla", "cap_1": "cap_blank", "cap_2": "cap_read"}
    for k, s in housing().items():
        a.add(s, name=k, color=cq.Color(*COL[colours.get(k, "housing")]))
    for k, s in moving().items():
        a.add(s, name=k, color=cq.Color(*COL[colours.get(k, "lid")]))
    a.add(lid_leaf(rev), name=f"lid_leaf_rev{rev}", color=cq.Color(*REV_COLOUR[rev]))
    a.add(slot_sleeve(rev), name=f"slot_sleeve_rev{rev}", color=cq.Color(*REV_COLOUR[rev]))
    a.add(cuvette(), name="cuvette", color=cq.Color(*COL["cuvette"]))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name=k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
