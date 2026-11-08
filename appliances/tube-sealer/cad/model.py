"""HS-20 tube heat sealer and its one-tube stand, as build.py wants them: one assembly per revision, product frame, mm.

Origin on the base's bottom face, centred; +X toward the arm, +Z up. A laser-cut 3 mm box with a 45 deg control face
toward the arm (CLAMP lever, SEAL button), a display behind a window in the front panel, and a printed sealing-slot
bezel in the top deck that a tube drops into. The stand is a printed column with a bore, at the spot the arm picks from.

The control face lies in the same plane as the MC-6's (outer face x + z = 119), so the controls sit in the arm's tested
envelope. Fault parts carry a _revA / _revB suffix and are tinted orange / green, as the real kits are printed.
"""
import math

import cadquery as cq

T = 3.0                       # sheet thickness
W = 100.0                     # body width (y), outside
X_FRONT, X_BACK = 60.0, -55.0
Z_TOP = 94.0                  # top deck's top face
FACE_SUM = 119.0              # control face outer plane: x + z = FACE_SUM
FACE_MID = (42.5, 76.5)       # (x, z) of the control row on the face's outer plane
CTRL_Y = {"clamp": -30.0, "seal": 25.0}
SLOT = (-10.0, 0.0)           # sealing slot centre (x, y)
SLOT_ID = {"A": 15.6, "B": 16.8}
BEZEL_OD, BEZEL_FLANGE_OD, BEZEL_FLANGE_T, BEZEL_SLEEVE = 20.0, 26.0, 1.6, 7.0
LAMP = (-30.0, 28.0)
STAND = (84.57, 175.03)       # the stand's bore centre: where the arm picks a tube from
JAW = (0.77, -0.64)           # the tube's flats face this way in the stand
STAND_TOP = 52.4
TUBE_COLLAR_TOP = 61.0        # tube's collar top, resting in the stand

COLOURS = {"body": (0.93, 0.93, 0.91, 1), "panel": (0.35, 0.37, 0.40, 1), "print": (0.92, 0.92, 0.90, 1),
           "black": (0.12, 0.12, 0.12, 1), "tube": (0.92, 0.92, 0.90, 1), "stand": (0.30, 0.55, 0.80, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = []   # the deck, bezel and stand column are arm_only (the tube meets their bores as rings), the rest is convex


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0)).val()


def cyl(r, z0, z1, x=0.0, y=0.0):
    return cq.Workplane("XY").circle(r).extrude(z1 - z0).translate((x, y, z0)).val()


def revolve(rz, x=0.0, y=0.0):
    """A solid of revolution about +Z from (r, z) points, placed at (x, y)."""
    s = cq.Workplane("XZ").polyline(rz).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()
    return s.translate(cq.Vector(x, y, 0))


def on_face(shape):
    """A shape built in the control face's local frame (X down the slope, Y across, Z out of the face, origin on the
    outer face at the control row) placed in the product frame."""
    return shape.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 45).translate(cq.Vector(FACE_MID[0], 0, FACE_MID[1]))


def side_panel(y0):
    pts = [(X_BACK, T), (X_FRONT, T), (X_FRONT, FACE_SUM - X_FRONT), (FACE_SUM - Z_TOP, Z_TOP), (X_BACK, Z_TOP)]
    return cq.Workplane("XZ", origin=(0, y0 + T, 0)).polyline(pts).close().extrude(T).val()


def body_parts(rev):
    """name -> (solid, colour key or rgba)."""
    p = {}
    p["base_plate"] = (box(X_BACK - 6, X_FRONT + 4, -W / 2 - 4, W / 2 + 4, 0, T), "body")
    win = box(X_FRONT - T - 1, X_FRONT + 1, -12.5, 12.5, 24.0, 36.0)
    p["front_panel"] = (box(X_FRONT - T, X_FRONT, -W / 2 + T, W / 2 - T, T, FACE_SUM - X_FRONT - 1.5).cut(win), "body")
    p["back_panel"] = (box(X_BACK, X_BACK + T, -W / 2 + T, W / 2 - T, T, Z_TOP - T), "body")
    p["side_panel_L"] = (side_panel(W / 2 - T), "body")
    p["side_panel_R"] = (side_panel(-W / 2), "body")
    # the control face: 49.5 mm down the slope, across the full width, holes for the SEAL cap and the CLAMP switch
    L = (X_FRONT - (FACE_SUM - Z_TOP)) * math.sqrt(2)
    face = cq.Workplane("XY").box(L, W, T, centered=(True, True, False)).translate((0, 0, -T)).val()
    face = face.cut(cyl(5.4, -T - 1, 1, 0, CTRL_Y["seal"])).cut(cyl(3.2, -T - 1, 1, 0, CTRL_Y["clamp"]))
    p["control_face"] = (on_face(face), "panel")
    deck = box(X_BACK, FACE_SUM - Z_TOP - 1.0, -W / 2, W / 2, Z_TOP - T, Z_TOP)
    p["top_deck"] = (deck.cut(cyl(BEZEL_OD / 2 + 0.15, Z_TOP - T - 1, Z_TOP + 1, *SLOT)), "body")
    # the sealing slot's printed bezel: a sleeve through the deck, a flange on it, a 1 mm lead-in chamfer
    r = SLOT_ID[rev] / 2
    z0, zf = Z_TOP - BEZEL_SLEEVE, Z_TOP + BEZEL_FLANGE_T
    bezel = revolve([(r, z0), (BEZEL_OD / 2, z0), (BEZEL_OD / 2, Z_TOP), (BEZEL_FLANGE_OD / 2, Z_TOP), (BEZEL_FLANGE_OD / 2, zf),
                     (r + 1.0, zf), (r, zf - 1.0)], *SLOT)
    p[f"slot_bezel_rev{rev}"] = (bezel, REV_COLOUR[rev])
    # SEAL cap: 10 mm, 2.5 proud of the face, with a flange under it that keeps it in
    cap = cyl(5.0, 0, 2.5, 0, CTRL_Y["seal"]).fuse(cyl(6.5, -T - 2.0, -T - 0.5, 0, CTRL_Y["seal"])).fuse(cyl(3.0, -T - 0.5, 0, 0, CTRL_Y["seal"]))
    p["cap_seal"] = (on_face(cap), "black")
    p["lamp_bezel"] = (cyl(6.0, Z_TOP, Z_TOP + 1.0, *LAMP).cut(cyl(4.2, Z_TOP - 1, Z_TOP + 2, *LAMP)), "print")
    return p


def electronics():
    e = {}
    e["ref_clamp_switch"] = on_face(box(-6.5, 6.5, CTRL_Y["clamp"] - 4, CTRL_Y["clamp"] + 4, -T - 18, -T).fuse(cyl(3.0, 0, 4.0, 0, CTRL_Y["clamp"])))
    e["ref_seal_switch"] = on_face(box(-6, 6, CTRL_Y["seal"] - 6, CTRL_Y["seal"] + 6, -T - 5.6, -T - 2.0))
    e["ref_oled"] = box(X_FRONT - T - 3.0, X_FRONT - T, -13.5, 13.5, 16.5, 43.5)
    e["ref_pico"] = box(-20, 31, -40, -19, T, T + 4)
    # the sealing jaws and their heater, under the deck either side of the bore
    e["ref_jaws"] = box(SLOT[0] - 6, SLOT[0] + 6, 10.0, 16.0, 72.0, 86.0).fuse(box(SLOT[0] - 6, SLOT[0] + 6, -16.0, -10.0, 72.0, 86.0))
    e["ref_tube_sensor"] = box(SLOT[0] - 12, SLOT[0] + 12, -3.2, 3.2, 35.0, 45.8)
    return e


def _yawed(shape, at):
    deg = math.degrees(math.atan2(JAW[1], JAW[0]))
    return shape.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), deg).translate(cq.Vector(at[0], at[1], 0))


def stand_parts():
    p = {}
    p["stand_base"] = (_yawed(box(-22, 22, -22, 22, 0, T), STAND), "stand")
    p["stand_column"] = (revolve([(8.4, T), (13.0, T), (13.0, STAND_TOP), (8.4, STAND_TOP)], *STAND), "stand")
    return p


def tube():
    """The HS-20 tube, the MC-6's: 16 mm body, 22 mm collar with 18 mm flats across the jaw axis, a 4 mm nub, and a lifting
    loop thin along the jaw axis. Local: z = 0 at the collar top."""
    rz = [(0, 0), (11, 0), (11, -6), (8, -9), (8, -16), (2.5, -46.5), (2, -46.5), (2, -55), (0, -55)]
    s = revolve(rz)
    s = s.cut(box(9, 20, -20, 20, -6, 0.5)).cut(box(-20, -9, -20, 20, -6, 0.5))
    bar = box(-1.5, 1.5, -7.2, 7.2, 0, 2.0)
    loop = cq.Workplane("YZ", origin=(-1.5, 0, 0)).center(0, 7.6).circle(6.6).circle(4.0).extrude(3.0).val()
    s = s.fuse(bar).fuse(loop)
    return _yawed(s, STAND).translate(cq.Vector(0, 0, TUBE_COLLAR_TOP))


def _rgba(c):
    return COLOURS[c] if isinstance(c, str) else c


def _assembly(rev):
    a = cq.Assembly(name=f"hs20_rev{rev}")
    for k, (s, c) in body_parts(rev).items():
        a.add(s, name=k, color=cq.Color(*_rgba(c)))
    for k, (s, c) in stand_parts().items():
        a.add(s, name=k, color=cq.Color(*_rgba(c)))
    a.add(tube(), name="tube", color=cq.Color(*COLOURS["tube"]))
    for k, s in electronics().items():
        a.add(s, name=k, color=cq.Color(*ELECTRONICS))
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
