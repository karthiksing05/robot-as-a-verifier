"""HPS-300 hotplate stirrer and its beaker rest, as build.py wants them: one assembly per revision, product frame, mm
(origin on the base's bottom face, centred; +X toward the arm; +Z up).

The housing is 3 mm plywood: base, back, front, two sides and a low top deck, with a raised console across the front
whose 45 deg face carries the POWER toggle and the HEAT and STIR pots. An aluminium hot plate sits on the deck behind
the console with a printed cradle in its centre, a bore the beaker hangs in over the stirrer magnet. The display is on
the front panel and the HOT lamp on the deck beside the plate. The beaker waits in a printed rest beside the unit.

Revision parts: the cradle insert (its bore). Everything else is the same in both.
"""
import math

import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf

T = 3.0                                    # sheet thickness
X0, X1, YW = -66.0, 60.0, 64.0             # housing outside: back face, front face, half width
DECK_TOP = 61.0                            # top deck top
FACE_C = 119.0                             # control face outer plane: x + z = FACE_C
FRONT_TOP = FACE_C - X1                    # 59: where the face meets the front panel
POD_TOP = 94.0                             # the console's top
POD_FRONT = FACE_C - POD_TOP               # 25: where the face meets the console's top
POD_BACK = 15.0                            # the console's back wall, outside
N45 = np.array([0.7071, 0.0, 0.7071])      # control face normal
FIN_X = np.array([0.5, -0.7071, -0.5])     # a knob's fin at its 0 end: toward -y and down the slope
PLATE_C, PLATE_R, PLATE_T = (-26.0, 0.0), 36.0, 3.0
CRADLE_ID = {"A": 15.6, "B": 16.8}         # bore of the cradle insert
CRADLE_OD, CRADLE_FLANGE_OD, CRADLE_FLANGE_T = 26.0, 30.0, 2.0
CRADLE_SLEEVE_BOTTOM = 56.0
REST_C, REST_TOP, REST_BORE = (100.0, 130.0), 52.0, 16.8
JAW = np.array([0.8, -0.6, 0.0])           # the beaker in its rest: flats across this (toward the arm)

LAMP = (5.0, 45.0)                         # the HOT lamp, on the deck beside the plate

# control positions: a point on the face's outer plane per control, mid-slope (x 42.5, z 76.5)
FACE_MID = np.array([42.5, 0.0, 76.5])
CTRL_Y = {"power": 0.0, "heat": -50.5, "stir": 50.5}

COLOURS = {"plywood": (0.83, 0.68, 0.47, 1), "alu": (0.78, 0.79, 0.80, 1), "PLA": (0.92, 0.92, 0.90, 1),
           "knob": (0.15, 0.15, 0.17, 1), "black": (0.08, 0.08, 0.09, 1), "lamp": (0.45, 0.08, 0.06, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = ["side_panel_L", "side_panel_R"]   # notched where the console rises; the cradle, plate, deck and rest are arm_only


def xf(shape, M):
    t = gp_Trsf()
    t.SetValues(*[float(M[i, j]) for i in range(3) for j in range(4)])
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape())


def frame(origin, z, x):
    z = np.asarray(z, float) / np.linalg.norm(z)
    x = np.asarray(x, float) - (np.asarray(x, float) @ z) * z
    x = x / np.linalg.norm(x)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, np.cross(z, x), z, origin
    return M


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cyl(r, z0, z1, x=0.0, y=0.0):
    return cq.Solid.makeCylinder(r, z1 - z0, cq.Vector(x, y, z0))


def xz_prism(pts, y0, y1):
    """A polygon in (x, z), extruded from y0 to y1."""
    return cq.Workplane("XZ", origin=(0, y1, 0)).polyline(pts).close().extrude(y1 - y0).val()


def revolve(rz):
    return cq.Workplane("XZ").polyline(rz).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()


def on_face(y):
    """Frame of a control's spot on the face's outer plane: z along the normal, x along the knob's fin."""
    return frame(FACE_MID + [0, y, 0], N45, FIN_X)


# ---------------------------------------------------------------- housing

def housing():
    p = {}
    p["base_plate"] = (box(X0, X1, -YW, YW, 0, T), "plywood")
    side = [(X0, T), (X1, T), (X1, FRONT_TOP), (POD_FRONT, POD_TOP), (POD_BACK, POD_TOP), (POD_BACK, DECK_TOP), (X0, DECK_TOP)]
    p["side_panel_L"] = (xz_prism(side, -YW, -YW + T), "plywood")
    p["side_panel_R"] = (xz_prism(side, YW - T, YW), "plywood")
    p["back_panel"] = (box(X0, X0 + T, -YW + T, YW - T, T, DECK_TOP - T), "plywood")
    front = box(X1 - T, X1, -YW + T, YW - T, T, FRONT_TOP - 1.0)
    front = front.cut(box(X1 - T - 1, X1 + 1, -24.0, 0.0, 23.5, 36.5))          # display window
    p["front_panel"] = (front, "plywood")
    deck = box(X0 + T, X1 - T, -YW + T, YW - T, DECK_TOP - T, DECK_TOP)
    deck = deck.cut(cyl(CRADLE_OD / 2 + 0.2, DECK_TOP - T - 1, DECK_TOP + 1, *PLATE_C))
    p["top_deck"] = (deck, "plywood")
    d = T / math.sqrt(2)
    face = xz_prism([(POD_FRONT, POD_TOP), (X1, FRONT_TOP), (X1 - d, FRONT_TOP - d), (POD_FRONT - d, POD_TOP - d)], -YW, YW)
    for k, r in (("power", 3.4), ("heat", 3.8), ("stir", 3.8)):
        face = face.cut(xf(cyl(r, -6, 2), on_face(CTRL_Y[k])))
    p["control_face"] = (face, "plywood")
    p["console_top"] = (box(POD_BACK, POD_FRONT, -YW + T, YW - T, POD_TOP - T, POD_TOP), "plywood")
    p["console_back"] = (box(POD_BACK, POD_BACK + T, -YW + T, YW - T, DECK_TOP, POD_TOP - T), "plywood")
    plate = cyl(PLATE_R, DECK_TOP, DECK_TOP + PLATE_T, *PLATE_C).cut(cyl(CRADLE_OD / 2 + 0.2, DECK_TOP - 1, DECK_TOP + PLATE_T + 1, *PLATE_C))
    p["hot_plate"] = (plate, "alu")
    # the HOT lamp's printed bezel on the deck, and the display's frame on the front panel
    p["lamp_bezel"] = (cyl(6.0, DECK_TOP, DECK_TOP + 0.3, *LAMP).cut(cyl(4.2, DECK_TOP - 1, DECK_TOP + 1, *LAMP)), "PLA")
    p["display_frame"] = (box(X1, X1 + 1.0, -25.0, 1.0, 22.5, 37.5).cut(box(X1 - 1, X1 + 2, -23.0, -1.0, 24.5, 35.5)), "black")
    return p


def cradle(rev):
    top = DECK_TOP + PLATE_T
    rz = [(CRADLE_ID[rev] / 2, CRADLE_SLEEVE_BOTTOM), (CRADLE_OD / 2, CRADLE_SLEEVE_BOTTOM), (CRADLE_OD / 2, top),
          (CRADLE_FLANGE_OD / 2, top), (CRADLE_FLANGE_OD / 2, top + CRADLE_FLANGE_T), (CRADLE_ID[rev] / 2 + 1.0, top + CRADLE_FLANGE_T),
          (CRADLE_ID[rev] / 2, top + CRADLE_FLANGE_T - 1.0)]
    s = revolve(rz)
    return xf(s, frame((PLATE_C[0], PLATE_C[1], 0), (0, 0, 1), (1, 0, 0)))


def knob(y):
    """10 mm knob, 11 mm tall, 5 mm above the face, with a 3 mm fin out to 9 mm: the device file's primitives."""
    s = cyl(5.0, 0, 11.0).fuse(box(0, 9.0, -1.5, 1.5, 0, 11.0))
    return xf(s, on_face(y) @ frame((0, 0, 5.0), (0, 0, 1), (1, 0, 0)))


def electronics():
    e = {}
    e["toggle"] = xf(box(-4, 4, -6.5, 6.5, -18, -T), on_face(CTRL_Y["power"]))
    e["toggle_bushing"] = xf(cyl(3.0, 0, 6.0), on_face(CTRL_Y["power"]))
    for k in ("heat", "stir"):
        e[f"pot_{k}"] = xf(cyl(8.0, -18, -T), on_face(CTRL_Y[k]))
        e[f"pot_{k}_bushing"] = xf(cyl(3.5, 0, 4.0), on_face(CTRL_Y[k]))
    e["oled"] = box(X1 - T - 4, X1 - T, -26.0, 2.0, 21.0, 39.0)
    e["heater"] = cyl(PLATE_R - 4, DECK_TOP - T - 3, DECK_TOP - T, *PLATE_C).cut(cyl(CRADLE_OD / 2 + 2, 0, 100, *PLATE_C))
    e["stir_motor"] = cyl(12.0, 5.0, 14.0, PLATE_C[0], 28.0)
    e["vessel_sensor"] = box(PLATE_C[0] - 6, PLATE_C[0] + 6, -14.0, -9.0, 8.0, 18.0)
    e["pico"] = box(5.0, 56.0, -50.0, -29.0, T, T + 4)
    e["lamp_led"] = cyl(3.5, DECK_TOP - T - 4, DECK_TOP - T, *LAMP)
    return e


# ---------------------------------------------------------------- beaker and its rest

def beaker():
    """15 mL conical beaker. Local: z = 0 at the collar top; flats across local x; the loop thin along local x."""
    rz = [(0, 0), (11.0, 0), (11.0, -6.0), (8.0, -9.0), (8.0, -17.0), (7.2, -22.0), (6.0, -28.0), (5.0, -34.0),
          (4.0, -40.0), (3.0, -46.5), (2.0, -55.0), (0, -55.0)]
    s = revolve(rz)
    s = s.cut(revolve([(0, 1), (6.4, 1), (6.4, -17.0), (1.0, -44.0), (0, -44.0)]))
    s = s.cut(box(9.0, 20, -20, 20, -6.0, 0.5)).cut(box(-20, -9.0, -20, 20, -6.0, 0.5))
    bar = box(-1.5, 1.5, -7.2, 7.2, 0, 2.0)
    ring = cq.Workplane("YZ", origin=(-1.5, 0, 0)).center(0, 7.6).circle(6.6).circle(4.0).extrude(3.0).val()
    s = s.fuse(bar).fuse(ring).clean()
    return xf(s, frame((REST_C[0], REST_C[1], REST_TOP + 8.6), (0, 0, 1), JAW))


def rest():
    p = {}
    p["rest_foot"] = (box(80.0, 120.0, 110.0, 150.0, 0, T), "plywood")
    block = box(85.0, 115.0, 115.0, 145.0, T, REST_TOP).cut(cyl(REST_BORE / 2, 2 * T, REST_TOP + 1, *REST_C))
    p["rest_block"] = (block, "PLA")
    return p


# ---------------------------------------------------------------- assemblies

def _assembly(rev):
    a = cq.Assembly(name=f"hps300_rev{rev}")
    for name, (solid, mat) in {**housing(), **rest()}.items():
        a.add(solid, name=name, color=cq.Color(*COLOURS[mat]))
    a.add(cradle(rev), name=f"cradle_rev{rev}", color=cq.Color(*REV_COLOUR[rev]))
    a.add(knob(CTRL_Y["heat"]), name="knob_heat", color=cq.Color(*COLOURS["knob"]))
    a.add(knob(CTRL_Y["stir"]), name="knob_stir", color=cq.Color(*COLOURS["knob"]))
    a.add(beaker(), name="beaker", color=cq.Color(0.90, 0.93, 0.95, 1))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name="ref_" + k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
