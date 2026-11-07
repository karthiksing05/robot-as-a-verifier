"""IT-90 lab interval timer, as build.py wants it: one cq.Assembly per revision, product frame, mm.

Product frame: origin on the bottom face, centred; +X toward the arm; +Z up. The case is a printed wedge: a vertical front
face carrying the display, and a panel sloped 45 deg toward the arm carrying the four controls in one row, on the plane
x + z = 119 (where the centrifuge's controls are, so the arm reaches them). The status light is a lens on the flat top.

Revision-dependent parts get _revA / _revB and the kit's print colour (orange / green). Only the +MIN bezel differs: in
Rev A its bore has a raised inner shoulder that the cap lands on after 0.1 mm, before the switch under it closes.
"""
import math

import cadquery as cq

A = math.sqrt(0.5)
N = cq.Vector(A, 0, A)     # the control panel's outward normal
U = cq.Vector(-A, 0, A)    # up the panel, away from the arm
PANEL = 119.0              # the panel's outer surface: x + z = PANEL
ROW = (42.5, 76.5)         # (x, z) of the control row on the panel surface

# the controls along y, left to right as the user sees them from the front (+X looking back): +MIN, +SEC, START/STOP, POWER
Y_MIN, Y_SEC, Y_GO, Y_POWER = -42.0, -20.0, 8.0, 44.0
CAP_R = {"min": 5.0, "sec": 5.0, "go": 7.0}
CAP_H = {"min": 2.5, "sec": 2.5, "go": 3.5}
CAP_Y = {"min": Y_MIN, "sec": Y_SEC, "go": Y_GO}

CASE = (0.88, 0.88, 0.86, 1)
TRIM = (0.62, 0.62, 0.64, 1)
INK = (0.12, 0.12, 0.14, 1)
KEY = (0.26, 0.26, 0.29, 1)
GO_KEY = (0.20, 0.36, 0.72, 1)
LENS = (0.95, 0.95, 0.95, 0.55)
RUBBER = (0.10, 0.10, 0.10, 1)
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = []   # every colliding part is convex enough as its hull: the case is a wedge, caps and bosses are cylinders


def on_panel(y, up=0.0, out=0.0):
    """A point on the panel: the control row at this y, `up` mm up the slope, `out` mm along the normal."""
    return cq.Vector(ROW[0], y, ROW[1]) + U * up + N * out


def cyl(r, h, at, d):
    return cq.Workplane().add(cq.Solid.makeCylinder(r, h, at, d))


def housing():
    prof = [(-50, 2), (60, 2), (60, PANEL - 60), (PANEL - 105, 105), (-50, 105)]
    w = cq.Workplane("XZ").polyline(prof).close().extrude(62, both=True)
    w = w.edges("|Z").fillet(8.0)
    for k, y in CAP_Y.items():   # cap bores
        w = w.cut(cyl(CAP_R[k] + 0.6, 8, on_panel(y, out=-6), N))
    w = w.cut(cyl(3.2, 8, on_panel(Y_POWER, out=-6), N))   # toggle bushing hole
    w = w.cut(cq.Workplane().box(4, 9, 4).translate((-50, 0, 12)))  # USB port at the back
    return w


def feet():
    out = cq.Workplane()
    for x in (-40, 50):
        for y in (-50, 50):
            out = out.union(cyl(5, 2, cq.Vector(x, y, 0), cq.Vector(0, 0, 1)))
    return out


def bezel(r_in, r_out, h):
    return lambda y: cyl(r_out, h, on_panel(y), N).cut(cyl(r_in, h + 1, on_panel(y, out=-0.5), N))


def cap(k):
    y = CAP_Y[k]
    return cyl(CAP_R[k], CAP_H[k], on_panel(y), N).union(cyl(CAP_R[k] - 1.5, 4.0, on_panel(y, out=-4.0), N))


def display_bezel():
    frame = cq.Workplane("YZ").workplane(offset=60).center(0, 40).rect(54, 24).extrude(1.5)
    window = cq.Workplane("YZ").workplane(offset=59).center(0, 40).rect(46, 17).extrude(4)
    return frame.cut(window)


def label(text, y, size=3.4):
    plane = cq.Plane(origin=on_panel(y, up=10.0), xDir=(0, 1, 0), normal=N.toTuple())
    return cq.Workplane(plane).text(text, size, 0.3, halign="center", valign="center")


def toggle_boss():
    return cyl(5.0, 1.2, on_panel(Y_POWER), N).union(cyl(3.0, 4.5, on_panel(Y_POWER), N))


def electronics():
    return {
        "pcb": cq.Workplane().box(70, 80, 1.6).translate((5, 0, 12)),
        "lcd_module": cq.Workplane().box(4, 50, 22).translate((57, 0, 40)),
        "toggle": cq.Workplane().box(8, 13, 9).translate((ROW[0] - 7, Y_POWER, ROW[1] - 7)),
        "switches": cq.Workplane().box(6, 70, 6).translate((ROW[0] - 6, -17, ROW[1] - 6)),
        "led": cq.Workplane().box(5, 5, 3).translate((-18, 0, 102)),
        "usb": cq.Workplane().box(8, 9, 4).translate((-45, 0, 12)),
    }


def assembly(rev):
    a = cq.Assembly(name=f"it90_rev{rev}")
    a.add(housing(), name="housing", color=cq.Color(*CASE))
    a.add(feet(), name="feet", color=cq.Color(*RUBBER))
    a.add(display_bezel(), name="display_bezel", color=cq.Color(*INK))
    a.add(cyl(8.0, 1.5, cq.Vector(-18, 0, 105), cq.Vector(0, 0, 1)), name="lamp_lens", color=cq.Color(*LENS))
    a.add(toggle_boss(), name="toggle_boss", color=cq.Color(*TRIM))
    # +MIN's bezel is the revision part. Rev B: a plain ring with clearance. Rev A: a raised ring whose bore steps in to
    # a shoulder just under the cap's skirt, so the cap stops 0.1 mm down
    if rev == "A":
        a.add(bezel(CAP_R["min"] + 0.1, CAP_R["min"] + 2.5, 1.8)(Y_MIN), name="bezel_min_revA", color=cq.Color(*REV_COLOUR["A"]))
    else:
        a.add(bezel(CAP_R["min"] + 0.6, CAP_R["min"] + 2.5, 1.2)(Y_MIN), name="bezel_min_revB", color=cq.Color(*REV_COLOUR["B"]))
    a.add(bezel(CAP_R["sec"] + 0.6, CAP_R["sec"] + 2.5, 1.2)(Y_SEC), name="bezel_sec", color=cq.Color(*TRIM))
    a.add(bezel(CAP_R["go"] + 0.6, CAP_R["go"] + 2.5, 1.2)(Y_GO), name="bezel_go", color=cq.Color(*TRIM))
    a.add(cap("min"), name="cap_min", color=cq.Color(*KEY))
    a.add(cap("sec"), name="cap_sec", color=cq.Color(*KEY))
    a.add(cap("go"), name="cap_go", color=cq.Color(*GO_KEY))
    for name, text, y, size in (("label_min", "+MIN", Y_MIN, 3.4), ("label_sec", "+SEC", Y_SEC, 3.4),
                                ("label_go", "START/STOP", Y_GO, 3.0), ("label_power", "POWER", Y_POWER, 3.0)):
        a.add(label(text, y, size), name=name, color=cq.Color(*INK))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name="ref_" + k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": assembly("A"), "B": assembly("B")}
