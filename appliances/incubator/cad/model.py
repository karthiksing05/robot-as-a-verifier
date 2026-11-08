"""MI-45 mini incubator: CadQuery source, one assembly per revision, product frame in mm.

Origin on the base's bottom face, centred. +X toward the arm, +Z up. 3 mm plywood panels, an acrylic door window, and
printed caps, lip and hinge check. The chamber door is a flat flap on top, hinged near the back: its pivot sits 15 mm
below the door on a drop leaf, so the door's weight is behind the pivot well before 90 deg, and once lifted to 90 deg it
rests open on its stop. It closes under its own weight. Behind the hinge a fixed strip of the top runs to the back panel. The door's
front skirt is the chamber's upper front wall: it lifts with the door, so the fixed cabinet ends at the brow.

Parts that differ between revisions carry _revA / _revB (docs/device-authoring.md):
    door_lip     the pull lip, at the door's front edge (or, as moulded wrong, on its hinge edge)
    hinge_check  the check block that sets how far the door opens
Electronics are ref_* placeholders, drawn only.
"""
import math

import cadquery as cq

T = 3.0                       # panel thickness
W = 62.0                      # half width (y)
X0, X1 = -62.0, 62.0          # back and front faces
FRONT_TOP = 64.0              # front panel top; the 45 deg fascia runs from here up to the brow
BROW_X, BROW_Z = 40.0, 86.0   # fascia's top edge = brow's front edge
WALL_X = 31.0                 # the chamber's upper front wall (outer face)
HINGE = (-41.3, 90.0)         # door's pivot line (x, z), along y, under the front of the fixed rear strip
DROP = 15.0                   # the door's underside is this far above the pivot
DOOR_TILT = 0.0               # deg, the door's slope when shut (flat)
DOOR_LEN = 75.0               # along the door, hinge to front edge
SLOPE = math.tan(math.radians(DOOR_TILT))

FASCIA_N = (math.sqrt(0.5), 0, math.sqrt(0.5))
FASCIA_C = 126.0              # fascia outer plane: x + z = 126
CONTROLS_Y = {"toggle": -38.0, "temp_down": 12.0, "temp_up": 36.0}
FACE_PT = (51.0, 75.0)        # (x, z) on the fascia where the controls sit

COLOURS = {"plywood": (0.83, 0.68, 0.47, 1), "acrylic": (0.70, 0.85, 0.95, 0.4), "pla": (0.92, 0.92, 0.90, 1),
           "dark": (0.15, 0.15, 0.15, 1), "metal": (0.75, 0.75, 0.78, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = []                  # every collision part is a plate, block or cylinder: its hull is right


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def top_z(x):
    """The cabinet's top edge under the door, at x."""
    return HINGE[1] + DROP + (x - HINGE[0]) * SLOPE


def side_panel(y0):
    pts = [(X0, T), (X1, T), (X1, FRONT_TOP), (BROW_X, BROW_Z), (WALL_X, BROW_Z), (WALL_X, top_z(WALL_X)), (X0, top_z(X0))]
    return cq.Workplane("XZ", origin=(0, y0 + T, 0)).polyline(pts).close().extrude(T)


def on_door(shape):
    """A shape drawn with the hinge line at the origin, along +X when shut, placed on the shut door."""
    return shape.rotate((0, 0, 0), (0, -1, 0), DOOR_TILT).translate((HINGE[0], 0, HINGE[1]))


def on_fascia(shape, y):
    """A shape drawn on the XY plane, +Z out of the face, placed at the control point at y."""
    return shape.rotate((0, 0, 0), (0, 1, 0), 45).translate((FACE_PT[0], y, FACE_PT[1]))


def fascia():
    length = math.hypot(X1 - BROW_X, BROW_Z - FRONT_TOP)
    plate = cq.Workplane("XY").box(length, 2 * (W - T), T).translate((0, 0, -T / 2))
    mid = ((X1 + BROW_X) / 2, (FRONT_TOP + BROW_Z) / 2)
    # the face's outer plane is x + z = 126: the plate's centre line sits on it, minus half a thickness
    return plate.rotate((0, 0, 0), (0, 1, 0), 45).translate((mid[0] - 0.0, 0, mid[1]))


def parts_for(rev):
    p = {}
    p["base_plate"] = (box(X0, X1, -W, W, 0, T), "plywood")
    p["back_panel"] = (box(X0, X0 + T, -W + T, W - T, T, top_z(X0)), "plywood")
    p["front_panel"] = (box(X1 - T, X1, -W + T, W - T, T, FRONT_TOP), "plywood")
    p["control_face"] = (fascia(), "plywood")
    p["brow"] = (box(WALL_X - T, BROW_X, -W + T, W - T, BROW_Z - T, BROW_Z), "plywood")
    p["side_panel_L"] = (side_panel(W - T), "plywood")
    p["side_panel_R"] = (side_panel(-W), "plywood")
    p["shelf"] = (box(-52, 22, -W + T + 1, W - T - 1, 44, 46), "metal")
    p["top_rear"] = (on_door(box(-(HINGE[0] - X0) / math.cos(math.radians(DOOR_TILT)), -0.5, -W, W, DROP, DROP + T)), "plywood")
    p["hinge_base"] = (on_door(box(-6, -0.5, -45, 45, 0, DROP)), "metal")   # hangs under the rear strip to the pivot

    # the door: a plywood frame round an acrylic window, its lip, all on one hinge
    frame = box(0, DOOR_LEN, -W + 1, W - 1, DROP, DROP + T).cut(box(12, DOOR_LEN - 12, -W + 13, W - 13, DROP - 1, DROP + T + 1))
    p["door_frame"] = (on_door(frame), "plywood")
    p["door_window"] = (on_door(box(12, DOOR_LEN - 12, -W + 13, W - 13, DROP + 0.5, DROP + 2.5)), "acrylic")
    skirt = box(WALL_X - T - HINGE[0], WALL_X - HINGE[0], -W + T + 0.5, W - T - 0.5, BROW_Z + 0.5 - HINGE[1], DROP)
    p["door_skirt"] = (on_door(skirt), "plywood")   # the chamber's upper front wall, on the door
    p["door_leaf"] = (on_door(box(0, 10, -45, 45, 0, DROP)), "metal")   # the drop leaf, door to pivot
    if rev == "B":   # the pull lip on the front edge: a 9 mm ledge with a 2 mm drop to hook under
        lip = box(DOOR_LEN - 1, DOOR_LEN + 9, -8, 8, DROP - 2, DROP + T)
    else:            # moulded on the hinge edge: it lies on the fixed rear strip, behind the hinge line
        lip = box(-10, -1, -8, 8, DROP + T + 0.5, DROP + T + 3.5)
    p[f"door_lip_rev{rev}"] = (on_door(lip), "rev")
    # the check block behind the hinge that the door's leaf meets: where it sits sets the opening angle
    if rev == "B":   # low and far back: the leaf meets it at 90 deg
        p["hinge_check_revB"] = (on_door(box(-14, -7, 47, 55, -6, 0)), "rev")
    else:            # tall and close in: the leaf meets it at 40 deg
        p["hinge_check_revA"] = (on_door(box(-9, -1, 47, 55, -6, 6)), "rev")

    # controls: two button caps, proud 2.5 mm of the fascia
    for k in ("temp_down", "temp_up"):
        cap = cq.Workplane("XY").circle(5.0).extrude(3.5).translate((0, 0, -1.0))
        p[f"cap_{k}"] = (on_fascia(cap, CONTROLS_Y[k]), "pla")
    return p


def electronics():
    e = {}
    e["ref_toggle"] = on_fascia(box(-5, 5, -5, 5, 0, 6), CONTROLS_Y["toggle"])
    for k in ("temp_down", "temp_up"):
        e[f"ref_switch_{k}"] = on_fascia(box(-6, 6, -6, 6, -6, -1), CONTROLS_Y[k])
    e["ref_oled"] = box(X1 - 2, X1 + 0.1, -14, 14, 30, 46)
    e["ref_led"] = box(BROW_X - 9, BROW_X - 3, -43, -37, BROW_Z, BROW_Z + 0.3)
    e["ref_heater"] = box(-55, 20, -40, 40, 6, 12)
    e["ref_pico"] = box(-58, -52, -25, 25, 10, 60)
    e["ref_door_switch"] = box(WALL_X - 8, WALL_X - 3, 30, 40, top_z(WALL_X) - 8, top_z(WALL_X) - 1)
    return e


def _assembly(rev):
    a = cq.Assembly(name=f"mi45_rev{rev}")
    for name, (shape, mat) in parts_for(rev).items():
        colour = REV_COLOUR[rev] if mat == "rev" else COLOURS[mat]
        a.add(shape, name=name, color=cq.Color(*colour))
    sub = cq.Assembly(name="electronics_reference")
    for name, shape in electronics().items():
        sub.add(shape, name=name, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
