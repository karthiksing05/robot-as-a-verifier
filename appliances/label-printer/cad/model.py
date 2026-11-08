"""LP-40 thermal label printer, as build.py wants it: one cq.Assembly per revision, product frame, mm.

Product frame: origin on the base's bottom face, centred; +X toward the arm; +Z up.

The body is a 3 mm panel box. Its front is a vertical panel (display, label exit slot) under a control face tilted 45 deg
toward the arm (POWER, FEED, PRINT, DARKNESS). Behind the control face a flat deck carries the status light and the roll
bay, which a flat cover hinged at its back edge closes. A lift tab stands on the cover's front edge: a riser, and a lip
reaching forward from its top, to lift the cover by with a fingertip.

The control face's outer surface is the plane x + z = 119, normal (0.7071, 0, 0.7071). Every control is centred on that
plane at product x 42.5, z 76.5, at its own y. Parts on the face are drawn in a local frame (z out of the face, x down
the slope, y along y) and placed with `on_face`.

Revision-dependent parts (suffix _revA / _revB):
    bezel_feed   the FEED cap's bezel: radial clearance 0.05 mm (A) or 0.4 mm (B)
    cover_lip    the lift tab. B: a riser up from the cover's front edge, its lip 21 mm above the deck in front.
                 A: a short skirt down from that edge, its lip only 2 mm above the deck
"""
import cadquery as cq

FACE_C = 119.0                      # control face's outer surface: x + z = FACE_C
FACE_AT = (42.5, 76.5)              # (x, z) of every control's centre on that surface
Y = {"toggle": -48.0, "feed": -21.0, "print": 5.0, "dial": 35.0}
CAP_R, CAP_TOP, CAP_BELOW = 5.0, 2.5, 3.0
BEZEL_OUT, BEZEL_H = 7.5, 1.0
BEZEL_CLEAR = {"A": 0.05, "B": 0.4}
LIP_OVERHANG = 10.0                 # the lip reaches this far past the cover's front edge

# cover, closed: a 3 mm plate lying on a rim around the roll bay, hinged along y at its back edge. It's flat on the
# side that faces the arm when it stands open, so a reach over it to close it meets nothing. It rests open against its
# stop once lifted past about 93 deg, where its bounding box's centre (where the loader puts its mass) passes over the
# hinge. The rim and the hinge's lugs hold the cover high, so the lip swings high and the arm's wrist stays clear of
# the deck at the top of the swing. The lift tab's lip is 11 mm above the plate, and 21 mm above the deck in front of
# the cover, so a fingertip pad fits under it (B).
COVER_X = (-55.0, 20.0)
COVER_Y = 35.0
COVER_Z = (93.5, 96.5)
TAB_Y = 12.0
RISER = (17.0, 20.0)                # riser's x span: its front face is the cover's front edge
LIP_Z = {"A": (88.0, 90.5), "B": (107.5, 110.0)}
HINGE = (-55.0, 100.0)

GREY = (0.86, 0.86, 0.84, 1)        # housing
DARK = (0.22, 0.24, 0.27, 1)        # cover, caps, knob
WHITE = (0.96, 0.96, 0.93, 1)       # label roll
METAL = (0.7, 0.7, 0.72, 1)
ELECTRONICS = (0.2, 0.45, 0.25, 1)
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}

# MuJoCo collides a mesh as its hull: none of these parts' holes matter to the arm (caps stand 1.5 mm proud of their
# bezels, the cover is a plate), so nothing is split.
CONCAVE = []


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl_z(r, z0, z1, x=0.0, y=0.0):
    return cq.Workplane("XY").circle(r).extrude(z1 - z0).translate((x, y, z0))


def xz_prism(pts, y0, y1):
    """A polygon in the xz plane, extruded from y0 to y1."""
    return cq.Workplane("XZ").polyline(pts).close().extrude(-(y1 - y0)).translate((0, y0, 0))


def on_face(shape, y):
    """A shape drawn in the face's local frame (z out of the face) placed on the control face at this y."""
    return shape.rotate((0, 0, 0), (0, 1, 0), 45).translate((FACE_AT[0], y, FACE_AT[1]))


def housing():
    parts = {}
    parts["base_plate"] = box(-62, 70, -60, 60, 0, 3)
    front = box(63, 66, -57, 57, 3, 53)
    front = front.cut(box(62, 67, -24, 24, 44, 46))                      # label exit slot
    parts["front_panel"] = front
    side = [(-62, 3), (66, 3), (66, 53), (33, 86), (-62, 86)]
    parts["side_panel_L"] = xz_prism(side, -60, -57)
    parts["side_panel_R"] = xz_prism(side, 57, 60)
    parts["back_panel"] = box(-62, -59, -57, 57, 3, 86)
    t = 3.0 * 0.7071                 # a 3 mm plate
    face = xz_prism([(66, 53), (33, 86), (33 - t, 86 - t), (66 - t, 53 - t)], -57, 57)
    for name, r in (("feed", CAP_R + 0.5), ("print", CAP_R + 0.5), ("toggle", 3.0), ("dial", 3.5)):
        face = face.cut(on_face(cyl_z(r, -10, 10), Y[name]))
    parts["control_face"] = face
    deck = box(-59, 31.5, -57, 57, 83, 86).cut(box(-50, 17, -32, 32, 82, 87))   # the roll bay's opening
    # the rim the cover rests on: four walls round the opening, each its own part so each collides as itself
    rim = COVER_Z[0]
    parts["bay_rim_front"] = box(17, 20, -35, 35, 86, rim)
    parts["bay_rim_back"] = box(-53, -50, -35, 35, 86, rim)
    parts["bay_rim_L"] = box(-50, 17, -35, -32, 86, rim)
    parts["bay_rim_R"] = box(-50, 17, 32, 35, 86, rim)
    parts["top_deck"] = deck
    parts["cover_hinge_base"] = box(-58, -52, -20, -15, 86, 103).union(box(-58, -52, 15, 20, 86, 103))   # lugs either side of the leaf
    parts["bezel_print"] = on_face(cyl_z(BEZEL_OUT, 0, BEZEL_H).cut(cyl_z(CAP_R + BEZEL_CLEAR["B"], -1, 2)), Y["print"])
    return parts


def visual():
    parts = {}
    roll = cq.Workplane("XZ").circle(24).circle(9).extrude(21, both=True).translate((-12, 0, 58))
    parts["label_roll"] = roll
    spindle = cq.Workplane("XZ").circle(4).extrude(28, both=True).translate((-12, 0, 58))
    parts["roll_spindle"] = spindle
    parts["spindle_bracket_L"] = box(-16, -8, -31, -28, 3, 62)
    parts["spindle_bracket_R"] = box(-16, -8, 28, 31, 3, 62)
    parts["toggle_base"] = on_face(box(-5, 5, -5, 5, 0, 3).union(cyl_z(3.0, 3, 6)), Y["toggle"])
    parts["dial_skirt"] = on_face(cyl_z(9.0, 0, 1.0).cut(cyl_z(3.5, -1, 2)), Y["dial"])
    frame = box(66, 67.5, -14, 14, 22.5, 37.5).cut(box(65, 68, -11.5, 11.5, 24.5, 35.5))
    parts["display_frame"] = frame
    parts["light_window"] = cyl_z(5.0, 85.6, 86.1, 26, -45).cut(cyl_z(4.0, 85, 87, 26, -45))
    return parts


def electronics():
    return {"pico": box(-40, 10, 35, 55, 3, 5), "print_head": box(40, 60, -25, 25, 40, 44), "oled": box(62, 63, -13, 13, 23, 37)}


def moving():
    parts = {}
    for name in ("feed", "print"):
        parts[f"cap_{name}"] = on_face(cyl_z(CAP_R, -CAP_BELOW, CAP_TOP), Y[name])
    knob = cyl_z(5.0, 5, 16).union(box(0, 9, -1.5, 1.5, 5, 16).rotate((0, 0, 0), (0, 0, 1), -45))
    parts["dial_knob"] = on_face(knob, Y["dial"])
    parts["cover"] = box(*COVER_X, -COVER_Y, COVER_Y, *COVER_Z)
    parts["cover_hinge_leaf"] = (cq.Workplane("XZ").circle(3.0).extrude(14.5, both=True).translate((HINGE[0], 0, HINGE[1]))
                                  .union(box(HINGE[0] - 3, HINGE[0] + 3, -14.5, 14.5, COVER_Z[1], HINGE[1])))
    parts["cover_sensor_fin"] = box(12, 14, 28, 30, 86, 93.5)   # down through the rim into the bay: breaks the cover sensor's beam
    return parts


def rev_parts(rev):
    clear = BEZEL_CLEAR[rev]
    bezel = on_face(cyl_z(BEZEL_OUT, 0, BEZEL_H).cut(cyl_z(CAP_R + clear, -1, 2)), Y["feed"])
    z0, z1 = LIP_Z[rev]
    lip = box(RISER[0], RISER[1] + LIP_OVERHANG, -TAB_Y, TAB_Y, z0, z1)
    # B's riser stands on the plate up to the lip; A's skirt hangs from the plate down to it
    stem = box(*RISER, -TAB_Y, TAB_Y, COVER_Z[1], z0) if z0 > COVER_Z[1] else box(*RISER, -TAB_Y, TAB_Y, z1, COVER_Z[0])
    lip = lip.union(stem)
    return {f"bezel_feed_rev{rev}": bezel, f"cover_lip_rev{rev}": lip}


def _assembly(rev):
    a = cq.Assembly(name=f"lp40_rev{rev}")
    for k, s in housing().items():
        a.add(s, name=k, color=cq.Color(*GREY))
    for k, s in visual().items():
        colour = WHITE if k == "label_roll" else METAL if k in ("roll_spindle",) else DARK if k in ("toggle_base", "dial_skirt", "display_frame", "light_window") else GREY
        a.add(s, name=k, color=cq.Color(*colour))
    for k, s in moving().items():
        a.add(s, name=k, color=cq.Color(*(METAL if k == "cover_hinge_leaf" else DARK)))
    for k, s in rev_parts(rev).items():
        a.add(s, name=k, color=cq.Color(*REV_COLOUR[rev]))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name="ref_" + k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
