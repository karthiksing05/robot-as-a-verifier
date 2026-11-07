"""BG-12 burr coffee grinder, as build.py wants it: one cq.Assembly per revision, product frame, mm.

Product frame: origin on the base's bottom face, centred; +X toward the arm; +Z up.

The body is a 124 x 120 mm box of 3 mm panels, 85 mm tall, with a 45 deg face along its top front edge (the control
face) and a matching one along its top back edge. A smoked bean hopper is sunk into the body, its rim flush with the
top panel, under a hinged lid with a hook lip at the front; the lid's hinge stands on a raised post at the back. The
display and the grounds bin are on the front panel.

Every control sits on a sloped face at the plate point (+-42.5, y, 76.5), the same spot the reference device's controls
use, so the arm's reach is the same. Parts that differ between revisions carry _revA / _revB; they are not tinted, the
product is one colour in both.
"""
import math

import cadquery as cq

A = math.sqrt(0.5)
T = 3.0                       # panel thickness
HX, HY = 62.0, 60.0           # body half depth (x) and half width (y), outside
Z_FACE, X_TOP, Z_TOP = 57.0, 34.0, 85.0   # sloped face from (HX, Z_FACE) up to (X_TOP, Z_TOP); x + z = 119 on its outer face
PLATE_X, PLATE_Z = 42.5, 76.5  # where each control meets the sloped face (outer surface)
# the hopper is sunk into the body, its rim flush with the top panel, and set back: the arm's wrist passes low over
# the front of the top as it lifts the lid past vertical
HOPPER_X, HOPPER_R, HOPPER_BOT, HOPPER_TOP = -10.0, 24.0, 52.0, 85.0
LID_R, LID_T = 30.0, 3.0
LID_TOP = HOPPER_TOP + LID_T
AXIS = (-51.0, LID_TOP + 15.0)  # lid hinge axis (x, z), along y: well back and on a raised post, so the arm stays high
CLEAR, OVERHANG = 10.0, 10.0   # hook lip: its underside this far above the lid, and this far past the lid's front edge

# The arm's wrist camera passes about 14 mm over the face, for y from about -25 to 15, as it lifts the lid: only START's
# low cap sits there. The knobs (16 mm) and the lever go outside that band. Each knob's fin points toward the middle
Y = {"grind": -45.0, "start": 0.0, "power": 30.0, "time": 50.0}
GRIND_BACK_Y = 45.0           # Rev A: GRIND on the back face. Turned 180 deg about z this is the front face's y = -45

CHARCOAL = (0.18, 0.18, 0.19, 1)
SMOKE = (0.36, 0.25, 0.17, 0.55)
SILVER = (0.80, 0.80, 0.82, 1)
BLACK = (0.10, 0.10, 0.10, 1)
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = ["lid_handle"]   # the hook lip: its hull would fill the gap under it


# --- helpers -------------------------------------------------------------------------------------------------------

def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cyl(r, z0, z1, x=0.0, y=0.0):
    return cq.Solid.makeCylinder(r, z1 - z0, cq.Vector(x, y, z0), cq.Vector(0, 0, 1))


def cyl_y(r, x, z, y0, y1):
    return cq.Solid.makeCylinder(r, y1 - y0, cq.Vector(x, y0, z), cq.Vector(0, 1, 0))


def xz_prism(pts, y0, y1):
    """A plate whose outline lies in the x-z plane, from y0 to y1."""
    wp = cq.Workplane("XZ", origin=(0, y1, 0)).polyline(pts).close().extrude(y1 - y0)
    return wp.val()


def fuse(shapes):
    s = shapes[0]
    for o in shapes[1:]:
        s = s.fuse(o)
    return s.clean()


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def place(shape, origin, z, x):
    """A shape drawn in a local frame (z out of the face, x along it) moved to origin with those axes."""
    z = _unit(z)
    d = sum(a * b for a, b in zip(x, z))
    x = _unit([a - d * b for a, b in zip(x, z)])
    return shape.moved(cq.Location(cq.Plane(origin=tuple(origin), xDir=tuple(x), normal=tuple(z))))


def face(side):
    """A sloped face's plate point maker, outward normal and dial-fin direction. side +1: front, -1: back."""
    n = (side * A, 0.0, A)
    fin = (side * 0.5, -side * A, -0.5)
    return (lambda y: (side * PLATE_X, y, PLATE_Z)), n, fin


# --- parts ---------------------------------------------------------------------------------------------------------

def housing():
    profile = [(-HX, T), (HX, T), (HX, Z_FACE), (X_TOP, Z_TOP), (-X_TOP, Z_TOP), (-HX, Z_FACE)]
    d = T * A
    slope_front = [(HX, Z_FACE), (X_TOP, Z_TOP), (X_TOP - d, Z_TOP - d), (HX - d, Z_FACE - d)]
    slope_back = [(-x, z) for x, z in slope_front]
    return {
        "base_plate": (box(-HX, HX, -HY, HY, 0, T), CHARCOAL),
        "front_panel": (box(HX - T, HX, -HY + T, HY - T, T, Z_FACE), CHARCOAL),
        "back_panel": (box(-HX, -HX + T, -HY + T, HY - T, T, Z_FACE), CHARCOAL),
        "side_panel_L": (xz_prism(profile, HY - T, HY), CHARCOAL),
        "side_panel_R": (xz_prism(profile, -HY, -HY + T), CHARCOAL),
        "control_face": (xz_prism(slope_front, -HY + T, HY - T), CHARCOAL),
        "rear_face": (xz_prism(slope_back, -HY + T, HY - T), CHARCOAL),
        "top_panel": (box(-X_TOP + d, X_TOP - d, -HY + T, HY - T, Z_TOP - T, Z_TOP).cut(cyl(HOPPER_R + 0.3, 0, 200, HOPPER_X)), CHARCOAL),
        # the hopper: a smoked acrylic tube on the top panel
        "hopper": (cyl(HOPPER_R, HOPPER_BOT, HOPPER_TOP, HOPPER_X).cut(cyl(HOPPER_R - 2.5, HOPPER_BOT + 2.0, HOPPER_TOP + 1, HOPPER_X)), SMOKE),
        # the lid's hinge: a post at the back of the hopper with two knuckles, the lid's leaf knuckle between them
        "lid_hinge_base": (fuse([box(AXIS[0] - 9.0, AXIS[0] - 3.0, -12.0, 12.0, Z_TOP - 25.0, AXIS[1] - 2.0),
                                 box(AXIS[0] - 5.0, AXIS[0], -12.0, -6.5, AXIS[1] - 4.0, AXIS[1] + 3.0),
                                 box(AXIS[0] - 5.0, AXIS[0], 6.5, 12.0, AXIS[1] - 4.0, AXIS[1] + 3.0),
                                 cyl_y(4.0, AXIS[0], AXIS[1], -12.0, -6.5), cyl_y(4.0, AXIS[0], AXIS[1], 6.5, 12.0)]), CHARCOAL),
    }


def front_details():
    pf, n, _ = face(+1)
    out = {
        # grounds bin: its front sits flush under the display, with a finger pull
        "bin_front": (fuse([box(HX, HX + 1.0, -32.0, 32.0, 5.0, 18.0), box(HX + 1.0, HX + 4.0, -10.0, 10.0, 15.0, 17.0)]), BLACK),
        "bezel_start": (place(cyl(8.0, 0, 1.0).cut(cyl(5.4, -1, 2)), pf(Y["start"]), n, (0, 1, 0)), BLACK),
    }
    return out


def cap_start():
    pf, n, _ = face(+1)
    cap = cyl(5.0, -3.0, 2.5)
    cap = cap.fillet(0.6, [e for e in cap.Edges() if abs(e.Center().z - 2.5) < 1e-6])
    return place(cap, pf(Y["start"]), n, (0, 1, 0))


def knob(side, y, finy=-1):
    """A selector knob with a fin, 5 to 16 mm above the face (the fin is what turn pushes). At rest the fin points down
    the face, toward finy * y on the front face (mirrored on the back, so a half turn gives the front's geometry)."""
    pf, n, fin = face(side)
    fin = (fin[0], side * finy * A, fin[2])
    k = fuse([cyl(5.0, 5.0, 16.0), box(0.0, 9.0, -1.5, 1.5, 5.0, 16.0)])
    k = k.cut(cyl(1.6, 4.0, 13.0))
    return place(k, pf(y), n, fin)


def lid():
    x_front = HOPPER_X + LID_R
    disk = cyl(LID_R, HOPPER_TOP, LID_TOP, HOPPER_X)
    knob_ring = cyl(6.0, LID_TOP, LID_TOP + 1.5, HOPPER_X)          # a moulded ring at the centre, cosmetic
    leaf = fuse([box(AXIS[0] - 2.0, HOPPER_X - LID_R + 12.0, -6.0, 6.0, LID_TOP - 0.5, LID_TOP + 2.0),
                 box(AXIS[0] - 1.5, AXIS[0] + 3.0, -6.0, 6.0, LID_TOP - 0.5, AXIS[1]),
                 cyl_y(4.0, AXIS[0], AXIS[1], -6.0, 6.0),
                 box(AXIS[0] - 3.0, AXIS[0] + 3.0, -3.0, 3.0, AXIS[1], AXIS[1] + 9.0)]   # stop lug: meets the post at full open
                ).cut(cyl_y(1.0, AXIS[0], AXIS[1], -20, 20))
    handle = fuse([box(x_front - 11.0, x_front, -8.0, 8.0, LID_TOP - 0.5, LID_TOP + 2.0),
                   box(x_front - 3.0, x_front, -8.0, 8.0, LID_TOP + 1.9, LID_TOP + CLEAR + 0.01),
                   box(x_front - 3.0, x_front + OVERHANG, -8.0, 8.0, LID_TOP + CLEAR, LID_TOP + CLEAR + 2.2)])
    return {"lid": (fuse([disk, knob_ring]), SMOKE), "lid_hinge_leaf": (leaf, CHARCOAL), "lid_handle": (handle, CHARCOAL)}


def lid_fin(right):
    """The tab under the lid that drops through a slot in the hopper's rim into the lid switch when the lid is shut.
    The wrong one is the same tab on the other side of the lid, where there is no switch."""
    y0 = 11.0 if right else -15.0
    return box(-31.0, -27.0, y0, y0 + 4.0, HOPPER_TOP - 1.0, HOPPER_TOP + 0.01)


def electronics():
    pf, n, _ = face(+1)
    return {
        "ref_oled": box(HX, HX + 1.2, -14.0, 14.0, 24.0, 40.0),
        "ref_toggle": place(cyl(4.5, 0, 3.0), pf(Y["power"]), n, (0, 1, 0)),
        "ref_motor": cyl(18.0, T, HOPPER_BOT, -5.0, 0.0),
        "ref_lid_switch": box(-40.0, -31.0, 8.0, 18.0, Z_TOP - 16.0, Z_TOP - 5.0),
    }


def _assembly(rev):
    a = cq.Assembly(name=f"bg12_rev{rev}")
    parts = {**housing(), **front_details(), **lid()}
    parts["cap_start"] = (cap_start(), SILVER)
    parts["knob_time"] = (knob(+1, Y["time"]), SILVER)
    if rev == "A":
        parts["knob_grind_revA"] = (knob(-1, GRIND_BACK_Y, +1), SILVER)
        parts["lid_sensor_fin_revA"] = (lid_fin(False), SMOKE)
    else:
        parts["knob_grind_revB"] = (knob(+1, Y["grind"], +1), SILVER)
        parts["lid_sensor_fin_revB"] = (lid_fin(True), SMOKE)
    for k, (solid, colour) in parts.items():
        a.add(solid, name=k, color=cq.Color(*colour))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name=k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
