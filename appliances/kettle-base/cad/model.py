"""KB-1 temperature kettle: a power base with a sloped control pod in front and a round jug behind it, whose lid is
hinged at the back and lifted by a hook lip at the front. One assembly per revision, product frame, mm: origin on the
base plate's bottom face, centred; +X toward the arm; +Z up.

Construction: 3 mm plywood base plate and control pod (front panel, 45 deg control face, sides, back, top), a printed
plinth under the jug, a stainless jug and lid, printed hinge, lid lip, button caps and dial knob. Electronics are ref_*
placeholders.

The control face's outer plane is x + z = 119 (the reach envelope of docs/device-authoring.md): controls sit at the
point O = (42.5, y, 76.5) on it, left to right as the user faces the panel (-y to +y): WARM, BOIL, POWER, TEMP.

Revision-dependent part: the lid's hinge leaf. Its web is the lid's stop when shut: Rev B's ends level with the lid's
top, Rev A's is printed 4 mm too long and 2 mm too deep, so it bottoms on the hinge base and the jug's rim before the
lid can seat, and the lid rests about 4.5 deg open.
"""
import math

import cadquery as cq

A = math.sqrt(0.5)
T = 3.0                       # sheet thickness
FACE = 119.0                  # control face outer plane: x + z = FACE
N = (A, 0.0, A)               # its outward normal
DOWN = (A, 0.0, -A)           # down the slope
O_X, O_Z = 42.5, 76.5         # control row on the outer face
CTRL_Y = {"warm": -42.0, "boil": -20.0, "power": 14.0, "temp": 46.0}

JUG_X, JUG_R, JUG_WALL = -20.0, 35.0, 2.0
PLINTH_Z = 22.0               # plinth top: the jug stands on it
RIM_Z = 94.0                  # jug rim; the lid's underside
LID_R, LID_T = 36.0, 3.0
HINGE = (-60.0, 102.0)        # lid hinge axis (x, z), along y
MOUTH_R = JUG_R - JUG_WALL    # 33: the jug's mouth
WEB = {"A": (6.0, 4.0), "B": (4.0, 0.0)}   # hinge leaf web: (length forward of the axis, depth below the lid top)

COL = {"plywood": (0.83, 0.68, 0.47, 1), "steel": (0.78, 0.79, 0.80, 1), "pla_white": (0.93, 0.93, 0.91, 1),
       "pla_dark": (0.22, 0.22, 0.24, 1), "silicone": (0.85, 0.85, 0.82, 1), "glass": (0.10, 0.12, 0.14, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

# hook lip, dial knob and hinge leaf: holes, lips and fins matter to the arm
CONCAVE = ["lid_handle", "lid_hinge_leaf_revA", "lid_hinge_leaf_revB", "hinge_base", "dial_knob"]


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0)).val()


def cyl(r, z0, z1, x=0.0, y=0.0):
    return cq.Workplane("XY").circle(r).extrude(z1 - z0).translate((x, y, z0)).val()


def cyl_y(r, y0, y1, x, z):
    """A cylinder along +y."""
    return cq.Workplane("XZ").center(x, z).circle(r).extrude(-(y1 - y0)).translate((0, y0, 0)).val()


def xz_prism(pts, y0, y1):
    """A profile in (x, z), extruded from y0 to y1."""
    return cq.Workplane("XZ").polyline(pts).close().extrude(-(y1 - y0)).translate((0, y0, 0)).val()


def on_face(solid_local, y, along=0.0):
    """Place a solid built in a face-local frame (z out of the face, x down the slope, origin on the outer face) at the
    control row point O, shifted `along` down the slope."""
    # a 45 deg turn about +y: local x -> DOWN, local y -> +y, local z -> N
    loc = cq.Location(cq.Vector(O_X + along * DOWN[0], y, O_Z + along * DOWN[2]), cq.Vector(0, 1, 0), 45.0)
    return solid_local.moved(loc)


def fuse(shapes):
    s = shapes[0]
    for t in shapes[1:]:
        s = s.fuse(t)
    return s.clean()


def pod():
    """The control pod: a 45 deg control face over a front panel, with sides, back and top. Holes for the controls."""
    front = box(57.0, 60.0, -55.0, 55.0, T, 56.0)
    outer_hi, outer_lo = (FACE - 95.0, 95.0), (60.0, FACE - 60.0)            # (24, 95), (60, 59)
    d = T * A
    face = xz_prism([outer_lo, outer_hi, (outer_hi[0] - d, outer_hi[1] - d), (outer_lo[0] - d, outer_lo[1] - d)], -58.0, 58.0)
    for k, y in CTRL_Y.items():
        r = {"warm": 5.4, "boil": 5.4, "temp": 3.6, "power": 3.2}[k]
        face = face.cut(on_face(cq.Workplane("XY").circle(r).extrude(20).translate((0, 0, -10)).val(), y))
    side = [(17.0, T), (60.0, T), (60.0, 59.0), (24.0, 95.0), (17.0, 95.0)]
    side_l, side_r = xz_prism(side, -58.0, -55.0), xz_prism(side, 55.0, 58.0)
    back = box(17.0, 20.0, -55.0, 55.0, T, 92.0)
    top = box(17.0, 24.0, -58.0, 58.0, 92.0, 95.0)
    return {"front_panel": front, "control_face": face, "pod_side_L": side_l, "pod_side_R": side_r, "pod_back": back, "pod_top": top}


def button_cap():
    """Face-local: a 10 mm cap 2.5 mm proud of the face, its stem through the plate and a flange under it."""
    return fuse([cyl(5.0, -T - 0.5, 2.5), cyl(6.5, -T - 2.0, -T - 0.5)])


def dial_knob():
    """Face-local: a 10 mm knob 5 to 16 mm above the face, with a 3 mm fin out to 9 mm along local -y (the fin points
    toward -y in the product frame, and down the slope)."""
    knob = cyl(5.0, 5.0, 16.0)
    fin = box(-1.5, 1.5, -9.0, 0.0, 5.0, 16.0)
    shaft = cyl(3.0, -T, 5.0)
    s = fuse([knob, fin, shaft])
    # point the fin along the device file's dial x: (0.5, -0.7071, -0.5) = half down-slope, half -y
    return s.rotate((0, 0, 0), (0, 0, 1), 45.0)


def toggle_base():
    """Face-local: the switch's bushing and nut; the lever itself is a primitive in the device file."""
    return fuse([cyl(3.0, 0.0, 6.0), cyl(5.0, 0.0, 1.5)])


def jug():
    shell = cyl(JUG_R, PLINTH_Z, RIM_Z, x=JUG_X).cut(cyl(MOUTH_R, PLINTH_Z + 3.0, RIM_Z + 1.0, x=JUG_X))
    # a grip handle on the left (-y) side
    handle = (cq.Workplane("YZ").polyline([(-32, 40), (-52, 40), (-52, 86), (-32, 86), (-32, 80), (-46, 80), (-46, 46), (-32, 46)])
              .close().extrude(14.0).translate((JUG_X - 7.0, 0, 0)).val())
    return shell, handle


def plinth():
    return cq.Workplane("XY").box(83.0, 100.0, PLINTH_Z - T, centered=False).edges("|Z").fillet(10.0).translate((-66.0, -50.0, T)).val()


def lid(rev):
    disc = cyl(LID_R, RIM_Z, RIM_Z + LID_T, x=JUG_X)
    knob = cyl(6.0, RIM_Z + LID_T, RIM_Z + LID_T + 4.0, x=JUG_X)
    front = JUG_X + LID_R           # 18
    top = RIM_Z + LID_T             # 103
    pad = box(front - 11.0, front, -8.0, 8.0, top, top + 2.0)
    riser = box(front - 3.0, front, -8.0, 8.0, top + 1.9, top + 10.01)
    lip = box(front - 3.0, front + 10.0, -8.0, 8.0, top + 10.0, top + 12.2)   # underside at z 107, 10 mm out past the lid
    hx, hz = HINGE
    web_l, web_d = WEB[rev]
    leaf = fuse([box(hx, hx + 15.0, -6.0, 6.0, top, top + 2.5), box(hx, hx + web_l, -6.0, 6.0, top - web_d, hz),
                 cyl_y(4.0, -6.0, 6.0, hx, hz)])
    leaf = leaf.cut(cyl_y(1.0, -20, 20, hx, hz))
    return {"lid": fuse([disc, knob]), "lid_handle": fuse([pad, riser, lip]), f"lid_hinge_leaf_rev{rev}": leaf}


def hinge_base():
    hx, hz = HINGE
    block = box(hx - 5.0, JUG_X - JUG_R + 0.5, -12.0, 12.0, RIM_Z - 10.0, RIM_Z + 1.0)
    knuckles = [cyl_y(4.0, -12.0, -6.5, hx, hz), cyl_y(4.0, 6.5, 12.0, hx, hz),
                box(hx - 5.0, hx + 1.0, -12.0, -6.5, RIM_Z, hz), box(hx - 5.0, hx + 1.0, 6.5, 12.0, RIM_Z, hz)]
    return fuse([block] + knuckles).cut(cyl_y(1.0, -20, 20, hx, hz))


def electronics():
    return {
        "ref_pico": box(-40.0, 11.0, -10.5, 10.5, T, T + 4.0),
        "ref_oled": box(57.0, 58.5, -13.5, 13.5, 18.5, 45.5),
        "ref_encoder": on_face(box(-6.0, 6.0, -6.0, 6.0, -T - 8.0, -T), CTRL_Y["temp"]),
        "ref_toggle": on_face(box(-6.5, 6.5, -4.0, 4.0, -T - 15.0, -T), CTRL_Y["power"]),
        "ref_tact_warm": on_face(box(-6.0, 6.0, -6.0, 6.0, -T - 6.0, -T - 2.4), CTRL_Y["warm"]),
        "ref_tact_boil": on_face(box(-6.0, 6.0, -6.0, 6.0, -T - 6.0, -T - 2.4), CTRL_Y["boil"]),
        "ref_lid_switch": box(JUG_X - JUG_R - 9.0, JUG_X - JUG_R - 1.0, -16.0, -12.5, RIM_Z - 12.0, RIM_Z - 1.0),
        "ref_heater": cyl(26.0, PLINTH_Z - 2.0, PLINTH_Z, x=JUG_X),
    }


def build(rev):
    parts, colours = {}, {}

    def add(name, solid, colour):
        parts[name], colours[name] = solid, colour

    add("base_plate", box(-70.0, 64.0, -62.0, 62.0, 0.0, T), COL["plywood"])
    for k, s in pod().items():
        add(k, s, COL["plywood"])
    add("display_glass", box(60.0, 61.2, -13.0, 13.0, 25.0, 39.0), COL["glass"])
    add("plinth", plinth(), COL["pla_white"])
    shell, handle = jug()
    add("jug", shell, COL["steel"])
    add("jug_handle", handle, COL["pla_dark"])
    add("hinge_base", hinge_base(), COL["pla_dark"])
    for k, s in lid(rev).items():
        add(k, s, REV_COLOUR[rev] if k.startswith("lid_hinge_leaf") else (COL["steel"] if k == "lid" else COL["pla_dark"]))
    add("cap_warm", on_face(button_cap(), CTRL_Y["warm"]), COL["pla_white"])
    add("cap_boil", on_face(button_cap(), CTRL_Y["boil"]), (0.85, 0.20, 0.15, 1))
    add("dial_knob", on_face(dial_knob(), CTRL_Y["temp"]), COL["pla_dark"])
    add("toggle_base", on_face(toggle_base(), CTRL_Y["power"]), (0.75, 0.75, 0.78, 1))

    a = cq.Assembly(name=f"kb1_rev{rev}")
    for k, s in parts.items():
        a.add(s, name=k, color=cq.Color(*colours[k]))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name=k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": build("A"), "B": build("B")}
