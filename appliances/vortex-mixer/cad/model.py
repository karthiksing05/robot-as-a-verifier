"""VM-3 touch vortex mixer, as build.py wants it: one assembly per revision, product frame, mm.

Product frame: origin on the base plate's bottom face, centred on the housing; +X toward the arm; +Z up.
A 3 mm panel housing with a 45 deg control face (MODE toggle, START, SPEED dial), a printed cup head on top, a
printed cup holder on the +Y side, an OLED on the front panel, and one sample cup in the holder.

Only the cup head differs between revisions (its bore). Every number the device file needs is printed by
`python model.py` (no CadQuery needed for that part).
"""
import math

S = math.sqrt(0.5)
T = 3.0                                   # panel thickness

# housing
XF, XB = 58.0, -56.0                      # front panel outer face, back panel outer face
HW = 46.0                                 # side panel outer face, |y|
H = 90.0                                  # top panel top
FACE_C = 119.0                            # control face outer plane: x + z = FACE_C
Z_FRONT = FACE_C - XF                     # 61: where the face meets the front panel's plane
X_TOP = FACE_C - H                        # 29: where the face meets the top panel's plane

# controls: points on the control face's outer surface
CTRL_S = (42.5, 76.5)                     # (x, z) of the control row on the face
CTRL_Y = {"mode": -30.0, "start": 0.0, "speed": 30.0}

# cup head (on top) and holder (side)
HEAD_XY = (-18.0, 0.0)
HEAD_OD, HEAD_H = 32.0, 8.0               # boss above the top panel
HEAD_ID = {"A": 15.6, "B": 16.8}          # bore
HOLDER_XY = (20.0, 80.0)
HOLDER_Z = (62.0, 70.0)
HOLDER_ID = 16.8

# sample cup (local: z = 0 at the cap's top, +z up)
CUP = dict(collar_od=22.0, flats=18.0, collar_h=6.0, shoulder_r=9.5, shoulder_to=8.6, body_r=8.0, body_to=17.0,
           tip_r=2.0, length=55.0, loop_od=14.0, loop_id=8.0, loop_t=3.0)
SEAT_ABOVE = CUP["shoulder_to"]          # cap top above the bore's top when seated (the shoulder rests on it)
# the jaws close along the line to the arm's pan axis (product (274.5, 0)): the cap's flats and the loop face it
_r = (HOLDER_XY[0] - 274.5, HOLDER_XY[1])
JAW = (-_r[0] / math.hypot(*_r), -_r[1] / math.hypot(*_r))
CUP_YAW = math.degrees(math.atan2(JAW[1], JAW[0]))

COLOURS = {"panel": (0.86, 0.87, 0.89, 1), "face": (0.18, 0.19, 0.21, 1), "print": (0.92, 0.92, 0.90, 1),
           "rubber": (0.12, 0.12, 0.12, 1), "cup": (0.95, 0.95, 0.92, 1), "cap": (0.25, 0.45, 0.85, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

CONCAVE = []   # nothing's holes matter to the arm: the cup meets bore rings, and the plates with holes are arm_only


def on_face(y, d):
    """Product point d mm out along the control face's normal from the control row at lateral y."""
    return (CTRL_S[0] + d * S, y, CTRL_S[1] + d * S)


def numbers():
    """The device file's numbers, from the same constants."""
    n = (S, 0, S)
    out = {}
    out["start_top"] = on_face(CTRL_Y["start"], 4.5)
    hinge = on_face(CTRL_Y["mode"], 6.0)
    lean = (S, 0, -S)
    tip = tuple(hinge[i] + 10 * (math.cos(math.radians(15)) * n[i] + math.sin(math.radians(15)) * lean[i]) for i in range(3))
    out["toggle_hinge"], out["toggle_tip"] = hinge, tip
    fin = (0.5, -S, -0.5)
    out["dial_top"] = on_face(CTRL_Y["speed"], 5.0)
    out["dial_knob_to"] = on_face(CTRL_Y["speed"], 16.0)
    out["dial_anchor"] = on_face(CTRL_Y["speed"], 10.5)
    out["dial_fin"] = tuple(out["dial_anchor"][i] + 4.5 * fin[i] for i in range(3))
    out["head_ring_z"] = (H, H + HEAD_H)
    out["head_collar"] = (*HEAD_XY, H + HEAD_H + SEAT_ABOVE - 3.0)
    out["holder_collar"] = (*HOLDER_XY, HOLDER_Z[1] + SEAT_ABOVE - 3.0)
    out["cup_collar_top"] = (*HOLDER_XY, HOLDER_Z[1] + SEAT_ABOVE)
    out["jaw"], out["perp"] = JAW, (-JAW[1], JAW[0])
    return out


# ---------------------------------------------------------------------------- CadQuery from here

def _cq():
    import cadquery as cq
    return cq


def box(x0, x1, y0, y1, z0, z1):
    cq = _cq()
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0)).val()


def cyl(r, z0, z1, x=0.0, y=0.0):
    cq = _cq()
    return cq.Workplane("XY").circle(r).extrude(z1 - z0).translate((x, y, z0)).val()


def xz_prism(pts, y0, y1):
    """A polygon in the XZ plane, extruded from y0 to y1."""
    cq = _cq()
    w = cq.Workplane("XZ").polyline(pts).close().extrude(-(y1 - y0))   # XZ's normal is -Y
    return w.translate((0, y0, 0)).val()


def to_face(shape, y, d=0.0):
    """A solid built in the face-local frame (z along the normal, x down the slope) placed at lateral y."""
    cq = _cq()
    s = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 45.0)
    return s.translate(cq.Vector(*on_face(y, d)))


def housing():
    p = {}
    p["base_plate"] = box(XB - 2, XF + 4, -HW - 2, HW + 2, 0, T)
    side = [(XB, T), (XF, T), (XF, Z_FRONT), (X_TOP, H), (XB, H)]
    p["side_panel_L"] = xz_prism(side, -HW, -HW + T)
    p["side_panel_R"] = xz_prism(side, HW - T, HW)
    p["back_panel"] = box(XB, XB + T, -HW + T, HW - T, T, H - T)
    front = box(XF - T, XF, -HW + T, HW - T, T, Z_FRONT - 2.0)
    oled_window = box(XF - T - 1, XF + 1, -12, 12, 26, 38)
    p["front_panel"] = front.cut(oled_window)
    d = T * S
    face = xz_prism([(XF, Z_FRONT), (X_TOP, H), (X_TOP - d, H - d), (XF - d, Z_FRONT - d)], -HW, HW)
    for k, y in CTRL_Y.items():
        hole = to_face(cyl({"mode": 3.2, "start": 8.2, "speed": 3.6}[k], -10, 10), y)
        face = face.cut(hole)
    p["control_face"] = face
    top = box(XB, X_TOP - 1.0, -HW + T, HW - T, H - T, H)
    p["top_panel"] = top.cut(cyl(HEAD_OD / 2 - 4, H - T - 1, H + 1, *HEAD_XY))
    return p


def cup_head(rev):
    cq = _cq()
    r = HEAD_ID[rev] / 2
    boss = cyl(HEAD_OD / 2, H, H + HEAD_H, *HEAD_XY)
    sleeve = cyl(HEAD_OD / 2 - 4.3, H - T - 8, H, *HEAD_XY)
    s = boss.fuse(sleeve)
    s = s.cut(cyl(r, H - T - 9, H + HEAD_H + 1, *HEAD_XY))
    cone = cq.Solid.makeCone(r, r + 1.2, 1.2, cq.Vector(HEAD_XY[0], HEAD_XY[1], H + HEAD_H - 1.2))
    return s.cut(cone)


def holder():
    hx, hy = HOLDER_XY
    arm = box(hx - 12, hx + 12, HW, hy + 12, *HOLDER_Z)
    arm = arm.fuse(cyl(12, *HOLDER_Z, hx, hy))
    arm = arm.cut(cyl(HOLDER_ID / 2, HOLDER_Z[0] - 1, HOLDER_Z[1] + 1, hx, hy))
    plate = box(hx - 12, hx + 12, HW, HW + T, HOLDER_Z[0] - 22, HOLDER_Z[1])   # screwed to the side panel
    return arm.fuse(plate)


def controls():
    cq = _cq()
    p = {}
    # START: printed bezel (flange on the face) and its cap, 4.5 mm proud of the face
    bezel = cyl(10.0, 0, 2.0).fuse(cyl(8.0, -5.0, 0.01)).cut(cyl(5.4, -6, 3))
    p["bezel_start"] = to_face(bezel, CTRL_Y["start"])
    cap = cyl(5.0, -5.3, 4.5).fuse(cyl(6.5, -7.5, -5.3))
    p["cap_start"] = to_face(cap.fillet(0.6, [e for e in cap.Edges() if abs(e.Center().z - 4.5) < 1e-6]), CTRL_Y["start"])
    # MODE: the toggle's square nut and bushing (the lever is a primitive in the device file)
    p["toggle_base"] = to_face(box(-5, 5, -5, 5, 0, 3.0).fuse(cyl(3.0, 3.0, 5.5)), CTRL_Y["mode"])
    # SPEED: knob, 5 to 16 mm above the face, with its pointer fin toward -y and down the slope
    knob = cyl(5.0, 5.0, 16.0)
    fin = box(0, 9.0, -1.5, 1.5, 5.0, 16.0).rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), -45.0)
    p["dial_knob"] = to_face(knob.fuse(fin), CTRL_Y["speed"])
    p["dial_skirt"] = to_face(cyl(8.0, 0, 1.0).cut(cyl(3.7, -1, 2)), CTRL_Y["speed"])
    # display: an OLED frame on the front panel
    p["oled_frame"] = box(XF, XF + 0.8, -15, 15, 23, 41).cut(box(XF - 1, XF + 2, -11, 11, 26.5, 37.5))
    return p


def cup():
    """The sample cup in its holder: a cap with two flats, a shoulder, a straight body and a long taper, and a loop."""
    cq = _cq()
    c = CUP
    s = cyl(c["collar_od"] / 2, -c["collar_h"], 0)
    s = s.cut(box(c["flats"] / 2, 20, -20, 20, -c["collar_h"] - 1, 1)).cut(box(-20, -c["flats"] / 2, -20, 20, -c["collar_h"] - 1, 1))
    s = s.fuse(cyl(c["shoulder_r"], -c["shoulder_to"], -c["collar_h"] + 0.01))
    s = s.fuse(cyl(c["body_r"], -c["body_to"], -c["shoulder_to"] + 0.01))
    taper = cq.Solid.makeCone(c["tip_r"], c["body_r"], c["length"] - c["body_to"], cq.Vector(0, 0, -c["length"]))
    s = s.fuse(taper)
    ro, ri = c["loop_od"] / 2, c["loop_id"] / 2
    loop = (cq.Workplane("YZ").center(0, 1.6 + ro).circle(ro).circle(ri).extrude(c["loop_t"]).translate((-c["loop_t"] / 2, 0, 0)).val())
    s = s.fuse(loop).fuse(box(-1.5, 1.5, -4, 4, -0.01, 2.0))
    s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), CUP_YAW)
    return s.translate(cq.Vector(HOLDER_XY[0], HOLDER_XY[1], HOLDER_Z[1] + SEAT_ABOVE))


def electronics():
    return {"motor": cyl(14.0, 20.0, 46.0, *HEAD_XY),
            "pico": box(-10, 41, -10.5, 10.5, 3.0, 7.0),
            "oled": box(XF - T - 1.5, XF - T, -13.5, 13.5, 18.5, 45.5),
            "beam": box(HEAD_XY[0] - 3, HEAD_XY[0] + 3, -12.25, 12.25, H - T - 12, H - T - 1.2)}


def _assembly(rev):
    cq = _cq()
    a = cq.Assembly(name=f"vm3_rev{rev}")
    for k, s in housing().items():
        a.add(s, name=k, color=cq.Color(*COLOURS["face" if k == "control_face" else "panel"]))
    a.add(cup_head(rev), name=f"cup_head_rev{rev}", color=cq.Color(*REV_COLOUR[rev]))
    a.add(holder(), name="cup_holder", color=cq.Color(*COLOURS["print"]))
    for k, s in controls().items():
        colour = COLOURS["rubber"] if k in ("dial_knob", "toggle_base", "oled_frame") else COLOURS["print"]
        a.add(s, name=k, color=cq.Color(*colour))
    a.add(cup(), name="sample_cup", color=cq.Color(*COLOURS["cup"]))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics().items():
        sub.add(s, name="ref_" + k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}


if __name__ == "__main__":
    for k, v in numbers().items():
        print(f"{k:16s}", [round(x, 2) for x in v])
