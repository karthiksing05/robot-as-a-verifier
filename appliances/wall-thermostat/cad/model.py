"""HT-20 room thermostat on its DS-1 desk stand, as build.py wants it: one assembly per revision, product frame, mm.

Origin on the base's bottom face, centred. +X toward the arm, +Z up. The thermostat's face is vertical: it looks along
+X, straight at the arm, as it would on a wall. The stand is a base plate, an upright wall panel and two gussets.

Part names: a part that differs between revisions ends in _revA or _revB. Electronics are ref_* placeholders.
"""
import cadquery as cq

# --- the design's dimensions ---
BASE = dict(x=(-50.0, 50.0), y=(-60.0, 60.0), z=(0.0, 6.0))
PANEL = dict(x=(20.0, 26.0), y=(-60.0, 60.0), z=(6.0, 130.0))          # the "wall": 6 mm plywood
HOUSING = dict(x=(26.0, 52.0), y=(-50.0, 50.0), z=(58.0, 128.0))       # printed shell, 26 deep
FACE_X = HOUSING["x"][1]                                               # the front face, vertical
BUTTON_Z = 116.0                                                      # a row along the top of the face
BUTTONS = {"mode": -25.0, "down": 0.0, "up": 25.0}                     # y, left to right seen from the front
CAP_R, CAP_PROUD, CAP_DEPTH = 5.0, 2.5, 5.0                             # caps stand 2.5 mm proud of the face
BEZEL_OD, BEZEL_T = 14.0, 1.0
HOLE_R = 5.6
DISPLAY = dict(centre=(FACE_X, 0.0, 88.0), size=(44.0, 16.0), frame=(52.0, 22.0))
LIGHT = dict(centre=(40.0, 0.0, 128.0), r=5.0)

# Rev B's DOWN bezel bore clears the cap. Rev A's is printed undersize, and the cap rubs in it.
BEZEL_DOWN_ID = {"A": 10.2, "B": 11.0}
BEZEL_ID = 11.0

PLYWOOD = (0.83, 0.68, 0.47, 1)
SHELL = (0.93, 0.93, 0.90, 1)
CAP = (0.78, 0.78, 0.80, 1)
CAP_MODE = (0.32, 0.32, 0.35, 1)
BEZEL = (0.55, 0.55, 0.58, 1)
FRAME = (0.12, 0.12, 0.12, 1)
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = []  # every collision part is convex, or only the arm meets it where its hull fills a hole


def _box(x, y, z):
    return cq.Workplane("XY").box(x[1] - x[0], y[1] - y[0], z[1] - z[0], centered=False).translate((x[0], y[0], z[0]))


def _face_disc(y, z, r, x0, depth):
    """A cylinder on the face's normal (+X), from x0 forward by depth."""
    return cq.Workplane("YZ", origin=(x0, y, z)).circle(r).extrude(depth)


def _ring(y, z, od, id_, x0, depth):
    return cq.Workplane("YZ", origin=(x0, y, z)).circle(od / 2).circle(id_ / 2).extrude(depth)


def _gusset(y):
    pts = [(-40.0, BASE["z"][1]), (PANEL["x"][0], BASE["z"][1]), (PANEL["x"][0], 90.0)]
    return cq.Workplane("XZ", origin=(0, y, 0)).polyline(pts).close().extrude(3.0, both=True)


def _housing():
    h = _box(HOUSING["x"], HOUSING["y"], HOUSING["z"]).edges("|X").fillet(6.0).faces(">X").edges().fillet(2.0)
    for y in BUTTONS.values():
        h = h.cut(_face_disc(y, BUTTON_Z, HOLE_R, FACE_X - 8.0, 10.0))
    cx, cy, cz = DISPLAY["centre"]
    window = cq.Workplane("YZ", origin=(cx - 0.6, cy, cz)).rect(*DISPLAY["size"]).extrude(1.0)  # the LCD sits in a 0.6 mm recess
    return h.cut(window)


def _parts(rev):
    parts = {
        "base_plate": (_box(BASE["x"], BASE["y"], BASE["z"]), PLYWOOD),
        "wall_panel": (_box(PANEL["x"], PANEL["y"], PANEL["z"]), PLYWOOD),
        "gusset_L": (_gusset(-50.0), PLYWOOD),
        "gusset_R": (_gusset(50.0), PLYWOOD),
        "housing": (_housing(), SHELL),
        "display_frame": (cq.Workplane("YZ", origin=(FACE_X, 0, DISPLAY["centre"][2])).rect(*DISPLAY["frame"]).rect(*DISPLAY["size"]).extrude(0.8), FRAME),
        "bezel_mode": (_ring(BUTTONS["mode"], BUTTON_Z, BEZEL_OD, BEZEL_ID, FACE_X, BEZEL_T), BEZEL),
        "bezel_up": (_ring(BUTTONS["up"], BUTTON_Z, BEZEL_OD, BEZEL_ID, FACE_X, BEZEL_T), BEZEL),
        f"bezel_down_rev{rev}": (_ring(BUTTONS["down"], BUTTON_Z, BEZEL_OD, BEZEL_DOWN_ID[rev], FACE_X, BEZEL_T), REV_COLOUR[rev]),
    }
    for name, y in BUTTONS.items():
        cap = _face_disc(y, BUTTON_Z, CAP_R, FACE_X + CAP_PROUD - CAP_DEPTH, CAP_DEPTH).faces(">X").edges().fillet(0.8)
        parts[f"cap_{name}"] = (cap, CAP_MODE if name == "mode" else CAP)
    return parts


def _electronics():
    lx, ly, lz = LIGHT["centre"]
    return {
        "pico": _box((30.0, 33.0), (-26.0, 26.0), (62.0, 100.0)),
        "lcd_module": _box((46.0, 51.0), (-24.0, 24.0), (79.0, 97.0)),
        "switches": _box((44.0, 47.0), (-32.0, 32.0), (110.0, 122.0)),
        "status_led": cq.Workplane("XY", origin=(lx, ly, lz - 3.0)).circle(2.5).extrude(3.0),
    }


def _assembly(rev):
    a = cq.Assembly(name=f"ht20_rev{rev}")
    for name, (solid, colour) in _parts(rev).items():
        a.add(solid, name=name, color=cq.Color(*colour))
    sub = cq.Assembly(name="electronics_reference")
    for name, solid in _electronics().items():
        sub.add(solid, name="ref_" + name, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
