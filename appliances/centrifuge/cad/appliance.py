"""
Mock mini centrifuge, tube rack and test tubes for the MakeCU demo (design brief v4).

Product frame: origin at the centre of the centrifuge base's bottom face,
+X toward the arm, +Y to the arm's left... (see features.json for the arm frame), +Z up.
All lengths in mm. Every tunable value lives in PARAMS.

Build:   parts = build(PARAMS, rev="A")   ->  dict name -> Part
Patch:   apply_patch(PARAMS, "patch_revB.yaml")
"""
import copy, math
import numpy as np
import cadquery as cq
from OCP.gp import gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

SQ2 = math.sqrt(2.0)
A = math.sqrt(0.5)

# ----------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------
PARAMS = {
    # --- sheet stock (laser) ---
    "sheet_t_mm": 3.0,            # measure the real sheet (often 2.7-3.2)
    "kerf_mm": 0.15,              # applied only in the 2D laser files
    "slot_fit_mm": 0.05,          # extra width on every slot, nominal
    "slip_fit_mm": 0.15,          # radial clearance between every printed insert and its sheet hole (no interference)
    "bayo_ear_w_mm": 4.0,         # quarter-turn bayonet: two ears under the sheet, two notches in the hole
    "bayo_ear_r_mm": 1.5,         # how far an ear sticks out past the sleeve
    "bayo_ear_h_mm": 1.5,
    "bayo_gap_mm": 0.3,           # ear top to sheet underside (and notch clearance)
    "bayo_notch_deg": 90.0,       # notch direction in the sheet's own frame
    "bayo_lock_deg": 45.0,        # twist from notch to locked
    "sheet_w_mm": 600.0,
    "sheet_h_mm": 300.0,
    "tab_w_mm": 10.0,

    # --- body ---
    "body_w_mm": 125.0,           # side panel to side panel, outside
    "body_d_mm": 120.0,
    "body_h_mm": 94.0,            # top panel top. Brief said ~65; the 55 mm tube needs more (see report)
    "slope_inner_run_mm": 39.24,  # horizontal run of the 45 deg control face (inner face)
    "slope_overhang_mm": 3.0,     # control face plate overhangs each side panel (free, sharp corners)
    "base_margin_mm": 4.0,        # base plate margin at sides and front
    "base_clamp_lip_mm": 20.0,    # base plate extension behind the body for a clamp
    "bowl_x_mm": -21.0,           # rotor centre, product X
    "opening_r_mm": 30.0,         # hole in the top panel over the rotor
    "deck_front_x_mm": 13.0,      # front edge of the rotor plate (must clear the breadboard)

    # --- controls row on the 45 deg face (lateral Y positions) ---
    "ctrl_y_mm": {"power": -50.5, "start": -22.86, "stop": 0.0, "time": 22.86, "speed": 50.5},
    "toggle_hole_mm": 6.4,
    "pot_hole_mm": 7.2,

    # --- buttons ---
    "bezel_od_mm": 16.0,
    "bezel_flange_od_mm": 20.0,
    "bezel_flange_t_mm": 2.0,
    "bezel_sleeve_depth_mm": 5.0,  # from plate outer face, inward
    "cap_d_mm": 10.0,
    "cap_proud_mm": 2.5,           # cap top above the bezel flange
    "cap_flange_d_mm": 13.0,
    "cap_flange_gap_mm": 0.8,      # cap flange to sleeve bottom
    "bezel_clearance_mm": {"stop": 0.05},   # per side; F1. A 0.15 variant prints alongside; keep the one that binds
    "stop_variants_mm": [0.05, 0.15],
    "cap_hole_clear_mm": 0.40,     # Start/Time laser caps ride in a plain laser hole, this much per side
    "cap_gap_mm": 0.5,             # laser cap flange to control-face underside
    "coupon_clearances_mm": [0.05, 0.15, 0.25],
    "coupon_sleeve_mm": 6.0,       # coupon bezels are shorter than the real one to print fast

    # --- electronics (typical values: replace with caliper measurements) ---
    "tact_body_mm": 12.0, "tact_body_h_mm": 3.6, "tact_stem_top_mm": 7.3, "tact_stem_d_mm": 3.5,
    "bb_l_mm": 83.0, "bb_w_mm": 55.0, "bb_h_mm": 9.5,
    "pico_l_mm": 51.0, "pico_w_mm": 21.0, "pico_h_mm": 4.0,
    "toggle_body_mm": [8.0, 13.0, 18.0],   # Y, along-slope, depth behind outer face
    "toggle_lever_len_mm": 10.0, "toggle_lever_d_mm": 3.0, "toggle_bushing_mm": 6.0,
    "pot_body_d_mm": 16.0, "pot_body_depth_mm": 15.0, "pot_bushing_above_mm": 4.0,
    "pot_shaft_d_mm": 6.0, "pot_shaft_flat_mm": 4.5, "pot_shaft_above_mm": 10.0,
    "oled_board_mm": [27.0, 27.0, 1.2], "oled_glass_mm": [26.0, 19.0, 1.5],
    "oled_view_mm": [22.0, 11.0], "oled_view_offset_mm": 0.0,
    "oled_hole_pitch_mm": [23.0, 23.5], "oled_hole_d_mm": 2.0, "oled_center_z_mm": 30.0,
    "ring_od_mm": 66.0, "ring_id_mm": 52.0, "ring_h_mm": 3.5,
    "moc_l_mm": 24.5, "moc_w_mm": 6.3, "moc_h_mm": 10.8, "moc_slot_w_mm": 5.0,
    "moc_slot_depth_mm": 8.0, "moc_beam_from_top_mm": 4.0,
    "moc_lead_gap_min_mm": 5.0,

    # --- tube ---
    "tube_od_mm": 16.0,
    "tube_len_mm": 55.0,           # collar top to nub tip
    "tube_wall_mm": 1.6,
    "collar_od_mm": 22.0, "collar_h_mm": 6.0, "collar_chamfer_mm": 3.0, "collar_flats_mm": 18.0,
    "straight_len_mm": 7.0,
    "nub_d_mm": 4.0, "nub_len_mm": 8.5,
    "loop_id_mm": 8.0, "loop_w_mm": 2.6, "loop_t_mm": 3.0,
    "nub_into_beam_mm": 2.0,       # nub tip below the optical beam when seated

    # --- wells ---
    "insert_od_mm": 20.0, "insert_flange_od_mm": 22.5, "insert_flange_t_mm": 1.6,
    "insert_sleeve_mm": 7.0, "insert_chamfer_mm": 1.0,
    "well_id_mm": {"A": 15.6, "B": 16.8, "rack": 16.8},   # A = F3 (tube OD - 0.4); B and rack are plain laser holes
    "well_offset_mm": 13.0,        # wells at bowl centre +/- this along Y (A at -Y)

    # --- lid / hinge ---
    "lid_front_x_mm": 20.0, "lid_half_w_mm": 56.0, "lid_corner_r_mm": 6.0,
    "lid_clear_min_mm": 3.0,
    "hinge_axis_dx_mm": -56.5,     # product X of the lid hinge axis
    "hinge_axis_dz_mm": 5.0,       # axis height above the lid top
    "hinge_pin_hole_mm": 2.0,      # 1.75 mm filament pin
    "hinge_knuckle_r_mm": 4.0,
    "hinge_sets_y_mm": [-35.0, 35.0],    # two laser hinges per door (cheek | knuckle | cheek)
    "hinge_gap_mm": 0.25,
    "lid_open_deg": 105.0,
    "handle_type": "pinch_tab",    # F2. Rev B: "hook_lip"
    "handle_overhang_mm": 10.0,
    "handle_clear_mm": 10.0,
    "peg_w_mm": 2.8,               # square pegs on printed parts
    "peg_hole_fit_mm": 0.2,
    "key_slide_mm": 3.0,          # lid handle J-tabs: push down, slide back this far to lock
    "key_head_mm": [3.6, 6.0, 1.5],  # T-head under the lid: along X, along Y, thickness

    # --- dial knob ---
    "knob_d_mm": 10.0, "knob_h_mm": 11.0, "knob_fin_height_mm": 11.0,
    "knob_fin_r_mm": 9.0, "knob_fin_t_mm": 3.0, "knob_bore_fit_mm": 0.15,
    "dial_sweep_deg": 270.0,

    # --- rack ---
    "rack_pitch_mm": 24.0, "rack_depth_mm": 52.0, "rack_top_front_mm": 30.0,
    "rack_nub_clear_mm": 3.0,
    "rack_pan_deg": 40.0,          # rack centre, degrees off the centrifuge direction (toward +Y)
    "rack_dist_mm": 258.0,         # rack centre to pan axis, horizontal

    # --- arm placement ---
    "pan_axis_x_mm": 274.5,        # pan axis, product X (on the Y = 0 line)
    "riser_height": 58.0,          # arm base height above the surface the products sit on

    # --- print ---
    "print_bed_mm": 220.0,
    "min_wall_mm": 1.2,
}


def apply_patch(params, patch):
    """patch: dict like {'bezel_clearance_mm': {'stop': 0.40}, 'handle_type': 'hook_lip'}"""
    p = copy.deepcopy(params)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k].update(v)
        else:
            p[k] = v
    return p


# ----------------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------------
def frame(origin, u, v):
    u = np.asarray(u, float); v = np.asarray(v, float); w = np.cross(u, v)
    M = np.eye(4); M[:3, 0] = u; M[:3, 1] = v; M[:3, 2] = w; M[:3, 3] = origin
    return M


def rotz(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    M = np.eye(4); M[0, 0] = c; M[0, 1] = -s; M[1, 0] = s; M[1, 1] = c
    return M


def rot_about_y_axis(point_xz, deg):
    """Rotation in the XZ plane about a line parallel to Y through (x, z); positive lifts +X up."""
    x0, z0 = point_xz
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    M = np.eye(4)
    # (dx, dz) -> (dx c - dz s, dx s + dz c)
    M[0, 0] = c; M[0, 2] = -s; M[2, 0] = s; M[2, 2] = c
    T1 = np.eye(4); T1[0, 3] = -x0; T1[2, 3] = -z0
    T2 = np.eye(4); T2[0, 3] = x0; T2[2, 3] = z0
    return T2 @ M @ T1


def xf(shape, M):
    t = gp_Trsf()
    t.SetValues(*[float(M[i, j]) for i in range(3) for j in range(4)])
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape())


def pt(M, p):
    return (M @ np.array([p[0], p[1], p[2], 1.0]))[:3]


def vec(M, d):
    return M[:3, :3] @ np.asarray(d, float)


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cyl(r, z0, z1, x=0.0, y=0.0):
    return cq.Solid.makeCylinder(r, z1 - z0, cq.Vector(x, y, z0))


def prism(pts, z0, z1):
    if hasattr(pts, "exterior"):          # shapely polygon, may have holes
        s = cq.Workplane("XY").workplane(offset=z0).polyline(list(pts.exterior.coords)[:-1]).close().extrude(z1 - z0).val()
        for ring in pts.interiors:
            s = s.cut(cq.Workplane("XY").workplane(offset=z0 - 1).polyline(list(ring.coords)[:-1]).close().extrude(z1 - z0 + 2).val())
        return s
    return cq.Workplane("XY").workplane(offset=z0).polyline(pts).close().extrude(z1 - z0).val()


def revolve(rz):
    """rz: list of (r, z) points, closed polygon in the XZ half plane, revolved about Z."""
    return cq.Workplane("XZ").polyline(rz).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()


def fuse(shapes):
    s = shapes[0]
    for o in shapes[1:]:
        s = s.fuse(o)
    return s.clean()


def cut(s, shapes):
    for o in shapes:
        s = s.cut(o)
    return s.clean()


def _xz(pts, y0, y1):
    wp = cq.Workplane("XZ", origin=(0, y1, 0)).polyline(pts).close().extrude(y1 - y0)
    return wp.val()   # XZ workplane normal is -Y, so extrude goes from y1 toward y0


def bayonet_cutter(P, od, x, y, t):
    """Hole for a bayonet insert in a sheet (sheet local frame, z 0..t)."""
    r = od / 2 + P["slip_fit_mm"]
    s = cyl(r, -1, t + 1, x, y)
    rr = od / 2 + P["bayo_ear_r_mm"] + P["bayo_gap_mm"]
    hw = P["bayo_ear_w_mm"] / 2 + P["bayo_gap_mm"]
    for a in (P["bayo_notch_deg"], P["bayo_notch_deg"] + 180):
        nb = box(0, rr, -hw, hw, -1, t + 1)
        s = s.fuse(xf(nb, frame((x, y, 0), (math.cos(math.radians(a)), math.sin(math.radians(a)), 0),
                                (-math.sin(math.radians(a)), math.cos(math.radians(a)), 0))))
    return s


def bayonet_ears(P, od, t):
    """Two ears on an insert sleeve, at the notch angle, just under a sheet whose top is z = 0."""
    zt = -(t + P["bayo_gap_mm"]); zb = zt - P["bayo_ear_h_mm"]
    hw = P["bayo_ear_w_mm"] / 2
    ears = []
    for a in (P["bayo_notch_deg"], P["bayo_notch_deg"] + 180):
        e = box(od / 2 - 0.6, od / 2 + P["bayo_ear_r_mm"], -hw, hw, zb, zt)
        ears.append(xf(e, frame((0, 0, 0), (math.cos(math.radians(a)), math.sin(math.radians(a)), 0),
                                (-math.sin(math.radians(a)), math.cos(math.radians(a)), 0))))
    return ears


# ----------------------------------------------------------------------------
# Part record
# ----------------------------------------------------------------------------
class Part:
    def __init__(self, name, kind, solid, material, qty=1, rev="both", note="",
                 local=None, M=None, t=None, engrave=None, print_M=None, group="centrifuge"):
        self.name = name; self.kind = kind; self.solid = solid; self.material = material
        self.qty = qty; self.rev = rev; self.note = note
        self.local = local          # laser: solid in local frame (z 0..t); print: solid in its own frame
        self.M = M                  # local -> product frame
        self.t = t
        self.engrave = engrave or []  # laser: list of closed polygons in local XY (outer face)
        self.print_M = print_M      # print: local -> print-bed orientation
        self.group = group


# ----------------------------------------------------------------------------
# Derived layout
# ----------------------------------------------------------------------------
def derive(P):
    D = {}
    t = P["sheet_t_mm"]; D["t"] = t
    D["half_w"] = P["body_w_mm"] / 2
    D["yi"] = D["half_w"] - t                       # side panel inner face
    D["xf"] = P["body_d_mm"] / 2; D["xb"] = -P["body_d_mm"] / 2
    H = P["body_h_mm"]; D["H"] = H
    D["z_f"] = H - P["slope_inner_run_mm"]          # slope inner face meets x = xf
    D["x_t"] = D["xf"] - P["slope_inner_run_mm"]    # slope inner face meets z = H
    D["slope_L"] = P["slope_inner_run_mm"] * SQ2
    D["Ms"] = frame((D["xf"], 0, D["z_f"]), (0, 1, 0), (-A, 0, A))   # slope plate frame
    D["slope_half"] = D["half_w"] + P["slope_overhang_mm"]

    # tube geometry (local: z = 0 at collar top, +Z up)
    ch = P["collar_chamfer_mm"]
    D["tube_body_bottom_straight"] = -(P["collar_h_mm"] + ch + P["straight_len_mm"])
    D["loop_top"] = 1 + P["loop_id_mm"] + 2 * P["loop_w_mm"]

    D["tube_profile"] = tube_profile(P, D)

    def rest_origin(well_id, ch=None):
        """Height of the tube origin (collar top) above the seat plane (insert flange top, or the
        sheet top for a plain hole: ch = 0) when the tube rests in a bore of this ID."""
        ch = P["insert_chamfer_mm"] if ch is None else ch; rb = well_id / 2
        zs, rs = D["tube_profile"]
        best = -1e9
        for z, r in zip(zs, rs):
            # need r <= bore radius at depth d = -(o + z)  (only where the tube is below the flange top)
            if r <= rb:
                continue
            if ch <= 0 or r >= rb + ch:
                need_d = 0.0                  # must stay above the flange top
            else:
                need_d = rb + ch - r          # 45 deg chamfer: radius drops 1:1 with depth
            # o + z >= -need_d  ->  o >= -need_d - z
            best = max(best, -need_d - z)
        return best + 0.02      # 0.02 mm so the resting tube never shares volume with the bore
    D["rest_origin"] = rest_origin
    D["origin_above_flange"] = rest_origin

    good = P["well_id_mm"]["B"]
    D["origin_ok"] = rest_origin(good)
    D["origin_hole"] = rest_origin(P["well_id_mm"]["rack"], ch=0)       # plain laser hole
    # button stack depth: laser cap (2 plunger plies + flange ply) and the printed Stop cap both end on the switch
    sleeve_min = t + P["bayo_gap_mm"] + P["bayo_ear_h_mm"] + 0.2
    D["bezel_sleeve"] = max(P["bezel_sleeve_depth_mm"], sleeve_min)
    D["stem_depth"] = max(2 * t + P["cap_gap_mm"], D["bezel_sleeve"] + 0.3 + 1.2)
    D["bb_depth"] = D["stem_depth"] + P["tact_stem_top_mm"]
    D["origin_stuck"] = rest_origin(min(P["tube_od_mm"] - 0.4, P["well_id_mm"]["A"]))
    D["flange_top"] = H - P["lid_clear_min_mm"] - (D["origin_stuck"] + D["loop_top"])
    D["deck_top"] = D["flange_top"] - P["insert_flange_t_mm"]; D["deck_bot"] = D["deck_top"] - t
    D["ring_top"] = D["deck_bot"]; D["ring_bot"] = D["ring_top"] - P["ring_h_mm"]
    D["cradle_top"] = D["ring_bot"]; D["cradle_bot"] = D["cradle_top"] - 2.0
    D["nub_tip_ok"] = D["flange_top"] + D["origin_ok"] - P["tube_len_mm"]
    D["moc_tube_bot"] = 3 * t                       # base plate + two laser riser frames
    D["moc_tube_top"] = D["moc_tube_bot"] + P["moc_h_mm"]
    D["beam_z"] = D["moc_tube_top"] - P["moc_beam_from_top_mm"]
    D["bowl"] = (P["bowl_x_mm"], 0.0)
    wo = P["well_offset_mm"]
    D["wells"] = {"A": (P["bowl_x_mm"], -wo), "B": (P["bowl_x_mm"], wo)}

    # lid + hinge
    D["lid_top"] = H + t
    D["axis"] = (P["hinge_axis_dx_mm"], D["lid_top"] + P["hinge_axis_dz_mm"])
    D["lid_back_x"] = P["hinge_axis_dx_mm"] + 3.0
    D["lid_moc_x"] = 7.5; D["lid_moc_y"] = -50.0
    D["lid_moc_top"] = H - t                         # glued to the top panel underside, slot up
    D["lid_beam_z"] = D["lid_moc_top"] - P["moc_beam_from_top_mm"]

    # rack (rack frame: u along the row, v toward the pan axis, z up; origin = centre of base bottom)
    D["rack_flange_top"] = t + P["rack_nub_clear_mm"] + P["tube_len_mm"] - D["origin_hole"]   # = top plate top
    D["rack_top_bot"] = D["rack_flange_top"] - t
    D["rack_cover_z"] = D["rack_flange_top"] + D["origin_hole"] + D["loop_top"] + P["lid_clear_min_mm"]
    n = 4
    D["rack_u"] = [(i - (n - 1) / 2) * P["rack_pitch_mm"] for i in range(n)]
    D["rack_in"] = (n - 1) * P["rack_pitch_mm"] + P["collar_od_mm"] + 8.0
    D["rack_hv"] = P["rack_depth_mm"] / 2
    th = math.radians(P["rack_pan_deg"])
    px = P["pan_axis_x_mm"]
    c = np.array([px - P["rack_dist_mm"] * math.cos(th), P["rack_dist_mm"] * math.sin(th), 0.0])
    vdir = np.array([math.cos(th), -math.sin(th), 0.0])   # toward the pan axis
    udir = np.array([-math.sin(th), -math.cos(th), 0.0])   # u x v = +Z
    D["Mrack"] = frame(c, udir, vdir)
    D["rack_axis"] = (-D["rack_hv"] + 4.5, D["rack_cover_z"] + t + P["hinge_axis_dz_mm"])  # (v, z)
    D["well_B_origin"] = None   # set in build (needs deck_top)
    return D


# ----------------------------------------------------------------------------
# Laser panels
# ----------------------------------------------------------------------------
def tabs_y(P, D, L, positions, side_t):
    """Finger tabs at both lateral ends of a cross panel (local x = product Y)."""
    yi = D["yi"]; t = D["t"]; w = P["tab_w_mm"]; f = P["slot_fit_mm"] / 2
    body, cutters = [], []
    for c in positions:
        for sgn in (-1, 1):
            x0, x1 = (yi, yi + side_t) if sgn > 0 else (-yi - side_t, -yi)
            body.append(box(x0, x1, c - w / 2, c + w / 2, 0, t))
            cutters.append(box(x0 - f, x1 + f, c - w / 2 - f, c + w / 2 + f, -f, t + f))
    return body, cutters


def engrave_text(s, x, y, size, anchor="center", angle=0.0):
    from matplotlib.textpath import TextPath
    from matplotlib.font_manager import FontProperties
    tp = TextPath((0, 0), s, size=size, prop=FontProperties(family="DejaVu Sans", weight="bold"))
    polys = [np.array(p) for p in tp.to_polygons() if len(p) > 2]
    allp = np.vstack(polys)
    w = allp[:, 0].max() - allp[:, 0].min(); h = size * 0.72
    dx = {"center": -w / 2, "left": 0, "right": -w}[anchor]
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out = []
    for p in polys:
        q = p + np.array([dx, -h / 2])
        q = np.c_[q[:, 0] * ca - q[:, 1] * sa, q[:, 0] * sa + q[:, 1] * ca] + np.array([x, y])
        out.append(q)
    return out


def laser_part(name, local, M, t, material, engrave=None, group="centrifuge", qty=1, note=""):
    return Part(name, "laser", xf(local, M), material, qty=qty, local=local, M=M, t=t,
                engrave=engrave, group=group, note=note)


def build_body(P, D, parts, cutters_store):
    t = D["t"]; yi = D["yi"]; xf_, xb = D["xf"], D["xb"]; H = D["H"]
    ply, acr = "plywood", "acrylic_clear"

    # ---- front panel (x xf-t..xf), local (Y, Z) ----
    zf_top = D["z_f"]
    body = [box(-yi, yi, t, zf_top, 0, t)]
    tb, tc = tabs_y(P, D, None, [zf_top * 0.3, zf_top * 0.72], t)
    bt, bc = [], []
    f = P["slot_fit_mm"] / 2
    for c in (-32.5, 32.5):
        bt.append(box(c - 7.5, c + 7.5, 0, t, 0, t))
        bc.append(box(c - 7.5 - f, c + 7.5 + f, -f, t + f, -f, t + f))
    local = fuse(body + tb + bt)
    # OLED window
    vw, vh = P["oled_view_mm"]
    wz = P["oled_center_z_mm"] + P["oled_view_offset_mm"]
    local = local.cut(box(-vw / 2 - 1, vw / 2 + 1, wz - vh / 2 - 1, wz + vh / 2 + 1, -1, t + 1))
    Mf = frame((xf_ - t, 0, 0), (0, 1, 0), (0, 0, 1))
    eng = engrave_text("MC-6  MINI CENTRIFUGE", 0, wz + 12.5, 4.2)
    eng += engrave_text("6000 RPM  .  SAMPLE SAFE", 0, wz - 11.0, 2.6)
    parts["front_panel"] = laser_part("front_panel", local, Mf, t, ply, eng)
    cutters_store["side"] += [xf(c, Mf) for c in tc]
    cutters_store["base"] += [xf(c, Mf) for c in bc]

    # ---- control face (45 deg), overhangs the sides; side-panel tabs go up into it ----
    L = D["slope_L"]; sh = D["slope_half"]
    local = box(-sh, sh, 0, L, 0, t)
    Ms = D["Ms"]
    yc = L / 2
    holes = []
    cy = P["ctrl_y_mm"]
    holes.append(cyl(P["toggle_hole_mm"] / 2 + P["slip_fit_mm"], -1, t + 1, cy["power"], yc))
    holes.append(cyl(P["pot_hole_mm"] / 2 + P["slip_fit_mm"], -1, t + 1, cy["speed"], yc))
    holes.append(bayonet_cutter(P, P["bezel_od_mm"], cy["stop"], yc, t))
    for b in ("start", "time"):
        holes.append(cyl(P["cap_d_mm"] / 2 + P["cap_hole_clear_mm"], -1, t + 1, cy[b], yc))
    local = cut(local, holes)
    eng = []
    for key, lab in (("power", "POWER"), ("start", "START"), ("stop", "STOP"), ("time", "TIME+")):
        eng += engrave_text(lab, cy[key], yc - 15.0, 3.6)
    eng += engrave_text("SPEED", cy["speed"] - 13.0, yc + 15.5, 3.2)
    eng += engrave_text("ON", cy["power"], yc + 10.5, 2.6)
    eng += engrave_text("OFF", cy["power"], yc - 10.0, 2.6)
    # dial scale: 6 major ticks over the sweep (1000..6000 rpm), minor ticks between
    sweep = P["dial_sweep_deg"]
    for i in range(11):
        a = math.radians(-sweep / 2 + i * sweep / 10)
        r0, r1 = (10.6, 13.6) if i % 2 == 0 else (10.6, 12.2)
        wdt = 0.7 if i % 2 == 0 else 0.45
        dx, dy = math.sin(a), math.cos(a)        # angle from +local y, clockwise toward +local x
        nx, ny = dy, -dx
        cx0, cy0 = cy["speed"], yc
        q = np.array([[cx0 + dx * r0 + nx * wdt, cy0 + dy * r0 + ny * wdt],
                      [cx0 + dx * r1 + nx * wdt, cy0 + dy * r1 + ny * wdt],
                      [cx0 + dx * r1 - nx * wdt, cy0 + dy * r1 - ny * wdt],
                      [cx0 + dx * r0 - nx * wdt, cy0 + dy * r0 - ny * wdt]])
        eng.append(q)
    eng += engrave_text("1", cy["speed"] - 13.2, yc - 11.5, 2.6)
    eng += engrave_text("6", cy["speed"] + 13.2 - 0.3, yc - 11.5, 2.6) if cy["speed"] + 13.5 < sh else []
    parts["control_face"] = laser_part("control_face", local, Ms, t, ply, eng,
                                       note="matte; locating corners at the top outside corners")

    # side-panel tabs that go up into the control face
    sl_tabs_local = []
    w = P["tab_w_mm"]
    for c in (L * 0.25, L * 0.75):
        for sgn in (-1, 1):
            x0, x1 = (yi, yi + t) if sgn > 0 else (-yi - t, -yi)
            sl_tabs_local.append((x0, x1, c - w / 2, c + w / 2))
    slope_tab_solids, slope_slot_cutters = [], []
    for (x0, x1, y0, y1) in sl_tabs_local:
        slope_tab_solids.append(xf(box(x0, x1, y0, y1, -0.01, t), Ms))   # belongs to side panel
        slope_slot_cutters.append(xf(box(x0 - f, x1 + f, y0 - f, y1 + f, -1, t + 1), Ms))
    parts["control_face"].local = cut(parts["control_face"].local,
                                      [box(x0 - f, x1 + f, y0 - f, y1 + f, -1, t + 1)
                                       for (x0, x1, y0, y1) in sl_tabs_local])
    parts["control_face"].solid = xf(parts["control_face"].local, Ms)

    # ---- top panel (z H-t..H), local y = x_top - X ----
    xt = D["x_t"] - 0.26
    Lt = xt - xb
    local = box(-yi, yi, 0, Lt, 0, t)
    tb, tc = tabs_y(P, D, Lt, [Lt * 0.2, Lt * 0.8], t)
    local = fuse([local] + tb)
    bx, by = D["bowl"]
    local = local.cut(cyl(P["opening_r_mm"], -1, t + 1, by, xt - bx))
    Mt = frame((xt, 0, H - t), (0, 1, 0), (-1, 0, 0))
    parts["top_panel"] = laser_part("top_panel", local, Mt, t, ply)
    cutters_store["side"] += [xf(c, Mt) for c in tc]
    D["top_x_front"] = xt

    # ---- rotor deck (clear acrylic) ----
    xd = P["deck_front_x_mm"]
    Ld = xd - (xb + 1.0)
    local = box(-yi, yi, 0, Ld, 0, t)
    tb, tc = tabs_y(P, D, Ld, [Ld * 0.2, Ld * 0.8], t)
    local = fuse([local] + tb)
    wx, wy = D["wells"]["A"]
    local = local.cut(bayonet_cutter(P, P["insert_od_mm"], wy, xd - wx, t))
    wx, wy = D["wells"]["B"]
    local = local.cut(cyl(P["well_id_mm"]["B"] / 2, -1, t + 1, wy, xd - wx))
    Md = frame((xd, 0, D["deck_bot"]), (0, 1, 0), (-1, 0, 0))
    parts["rotor_plate"] = laser_part("rotor_plate", local, Md, t, acr,
                                      note="clear acrylic so the light ring shows through")
    cutters_store["side"] += [xf(c, Md) for c in tc]

    # ---- side panels ----
    zf = D["z_f"]; xt0 = D["x_t"]
    prof = [(xf_, t), (xf_, zf), (xt0, H), (xb, H), (xb, t)]
    side_local = prism(prof, 0, t)
    bt = []
    for c in (-27.5, 27.5):
        bt.append(box(c - 10, c + 10, 0, t + 0.01, 0, t))
    side_local = fuse([side_local] + bt)
    out = {}
    for nm, y0 in (("side_panel_L", -yi), ("side_panel_R", D["half_w"])):
        Mside = frame((0, y0, 0), (1, 0, 0), (0, 0, 1))
        solid = xf(side_local, Mside)
        mine = [s for s in slope_tab_solids if (s.Center().y > 0) == (y0 > 0)]
        solid = fuse([solid] + mine)
        solid = cut(solid, cutters_store["side"])
        out[nm] = (solid, Mside)
        f2 = P["slot_fit_mm"] / 2
        for c in (-27.5, 27.5):
            cutters_store["base"].append(xf(box(c - 10 - f2, c + 10 + f2, -f2, t + f2, -f2, t + f2), Mside))
    for nm, (solid, Mside) in out.items():
        inv = np.linalg.inv(Mside)
        loc = xf(solid, inv)
        parts[nm] = Part(nm, "laser", solid, ply, local=loc, M=Mside, t=t)

    # ---- base plate ----
    m = P["base_margin_mm"]
    x_front = xf_ + m; x_back = xb - P["base_clamp_lip_mm"]
    hw = D["half_w"] + m
    local = box(-hw, hw, 0, x_front - x_back, 0, t)
    Mb = frame((x_front, 0, 0), (0, 1, 0), (-1, 0, 0))
    D["Mb"] = Mb; D["base_x_front"] = x_front
    parts["base_plate"] = laser_part("base_plate", local, Mb, t, ply,
                                     note="rear 20 mm is the clamping lip; bottom stays flat")
    return parts


def finish_base(P, D, parts, cutters_store, extra_holes):
    p = parts["base_plate"]
    solid = cut(p.solid, cutters_store["base"] + extra_holes)
    p.solid = solid
    p.local = xf(solid, np.linalg.inv(p.M))


# ----------------------------------------------------------------------------
# Printed parts
# ----------------------------------------------------------------------------
def make_bezel(P, clearance, depth=None, ears=True):
    """Local frame: z = 0 on the control-face outer surface, +z outward.
    Quarter-turn bayonet: drop in with the ears in the notches, twist 45 deg to lock."""
    depth = depth or P["bezel_sleeve_depth_mm"]
    bore = P["cap_d_mm"] + 2 * clearance
    ft = P["bezel_flange_t_mm"]; fr = P["bezel_flange_od_mm"] / 2
    fl = cyl(fr, 0, ft)
    sl = cyl(P["bezel_od_mm"] / 2, -depth, 0.01)
    parts_ = [fl, sl] + (bayonet_ears(P, P["bezel_od_mm"], P["sheet_t_mm"]) if ears else [])
    s = fuse(parts_)
    s = s.cut(cyl(bore / 2, -depth - 1, 5))
    # grip slots across the flange rim (fingernail or coin to twist it)
    for a in (0.0, 180.0):
        g = box(fr - 3.0, fr + 1.0, -0.8, 0.8, ft - 0.6, ft + 1.0)
        s = s.cut(xf(g, frame((0, 0, 0), (math.cos(math.radians(a)), math.sin(math.radians(a)), 0),
                               (-math.sin(math.radians(a)), math.cos(math.radians(a)), 0))))
    return s


def make_cap(P, D):
    """Printed Stop cap. Local: z = 0 at the control-face outer surface."""
    ft = P["bezel_flange_t_mm"]
    top = ft + P["cap_proud_mm"]
    fl_top = -(D["bezel_sleeve"] + 0.3)
    bot = -D["stem_depth"]
    pl = cyl(P["cap_d_mm"] / 2, fl_top - 0.01, top)
    fl = cyl(P["cap_flange_d_mm"] / 2, bot, fl_top)
    s = fuse([pl, fl])
    return s.fillet(0.6, [e for e in s.Edges() if abs(e.Center().z - top) < 1e-6])


def laser_cap_plies(P, D):
    """Start/Time caps as a glued stack of laser discs: 2 plunger plies + 1 flange ply.
    Returns (stack solid in face-local frame, [(ply name, flat ply solid, qty)])."""
    t = D["t"]
    fl_top = -(t + P["cap_gap_mm"]); fl_bot = fl_top - t
    d1, d2 = P["cap_d_mm"], P["cap_flange_d_mm"]
    plies = [("plunger", cyl(d1 / 2, 0, t), 2), ("flange", cyl(d2 / 2, 0, t), 1)]
    stack = fuse([cyl(d2 / 2, fl_bot, fl_top), cyl(d1 / 2, fl_top - 0.01, fl_top + t),
                  cyl(d1 / 2, fl_top + t - 0.01, fl_top + 2 * t)])
    return stack, plies, fl_top + 2 * t


def laser_knob_plies(P, D):
    """Speed knob as 4 identical laser plies: round hub + fin, D-hole for the pot shaft."""
    t = D["t"]
    from shapely.geometry import Point, box as sbox
    outline = Point(0, 0).buffer(P["knob_d_mm"] / 2, 64).union(
        sbox(-P["knob_fin_t_mm"] / 2, 0, P["knob_fin_t_mm"] / 2, P["knob_fin_r_mm"]))
    bd = P["pot_shaft_d_mm"] + P["knob_bore_fit_mm"]
    hole = Point(0, 0).buffer(bd / 2, 64)
    if P["pot_shaft_flat_mm"] > 0:
        hole = hole.intersection(sbox(-bd, -bd, P["pot_shaft_flat_mm"] + P["knob_bore_fit_mm"] / 2 - bd / 2, bd))
    ply = prism(outline.difference(hole), 0, t)
    n = max(1, int(math.ceil(P["knob_fin_height_mm"] / t)))
    z0 = P["pot_bushing_above_mm"] + 1.0
    stack = fuse([xf(ply, frame((0, 0, z0 + i * t), (1, 0, 0), (0, 1, 0))) for i in range(n)])
    return stack, [("ply", ply, n)]


def _circle(x, y, r):
    from shapely.geometry import Point
    return Point(x, y).buffer(r, 64)


def _rect(x0, z0, x1, z1):
    from shapely.geometry import box as sbox
    return sbox(x0, z0, x1, z1)


def hinge_profiles(P):
    """Laser hinge, (x, z) relative to the pin axis; x toward the door's free edge, z up.
    Cheeks stand on the fixed panel and carry the 105 deg stop (the door's own top face lands on it).
    The knuckle tabs down into the door."""
    t = P["sheet_t_mm"]; dz = P["hinge_axis_dz_mm"]; R = P["hinge_knuckle_r_mm"]
    rh = P["hinge_pin_hole_mm"] / 2
    zf = -(t + dz)                         # fixed panel top
    a = math.radians(P["lid_open_deg"])
    n = (-math.sin(a), math.cos(a)); off = -dz          # door top face, rotated to the open angle
    lx = lambda z: (off - n[1] * z) / n[0]
    from shapely.geometry import Polygon
    cheek = (_rect(-7, zf, 2, zf + t).union(_rect(-9, zf, -5, 16)).union(_rect(-6, -2.5, 0, 2.5))
             .union(_circle(0, 0, R)).union(Polygon([(lx(6), 6), (lx(16), 16), (-9, 16), (-9, 6)]))
             .union(_rect(-1, zf - t, 1.5, zf + 0.01))).difference(_circle(0, 0, rh))
    knuckle = (_circle(0, 0, R).union(_rect(0, -dz, 4, 0)).union(_rect(3, -dz, 20, -dz + 4))
               .union(_rect(7, -dz - t, 10, -dz + 0.01)).union(_rect(14, -dz - t, 17, -dz + 0.01))).difference(_circle(0, 0, rh))
    return cheek.buffer(0), knuckle.buffer(0), [(-1, 1.5)], [(7, 10), (14, 17)], zf


def handle_profiles(P, kind):
    """Lid handle as a 3-ply laminate (x from the lid front edge toward the arm, z from the lid top).
    Two J-tabs per ply go down through slots in the lid; slide back key_slide_mm to lock."""
    t = P["sheet_t_mm"]; ks = P["key_slide_mm"]
    def base():
        g = _rect(-19, 0, 0, t)
        for xs in (-8.0, -17.0):
            g = g.union(_rect(xs - 1.5, -t - 0.05, xs + 1.5, 0.01))
            g = g.union(_rect(xs - 1.5 - ks, -t - 0.05 - 1.5, xs + 1.5, -t - 0.05))
        return g
    if kind == "pinch_tab":
        mid = base().union(_rect(-12, t - 0.01, -2, t + 11))
        return [("outer", base(), 2), ("middle", mid, 1)]
    hook = base().union(_rect(-3, t - 0.01, 0, P["handle_clear_mm"] + 0.01)).union(
        _rect(-3, P["handle_clear_mm"], P["handle_overhang_mm"], P["handle_clear_mm"] + 2.5))
    return [("ply", hook, 3)]


def build_xz_part(name, poly, y0, Mbase, t, material="plywood", group="centrifuge", note="", kind="laser"):
    """A flat laser part whose profile lies in the (x, z) plane of Mbase, thickness t from y0 to y0 + t."""
    local = prism(poly, 0, t)
    M = Mbase @ frame((0, y0 + t, 0), (1, 0, 0), (0, 0, 1))
    return Part(name, kind, xf(local, M), material, local=local, M=M, t=t, group=group, note=note)


def recut(p, cutters):
    p.solid = cut(p.solid, cutters)
    p.local = xf(p.solid, np.linalg.inv(p.M))


def make_knob(P):
    """Local: z = 0 at plate outer face. Knob sits above the pot bushing."""
    z0 = P["pot_bushing_above_mm"] + 1.0
    z1 = z0 + P["knob_h_mm"]
    body = cyl(P["knob_d_mm"] / 2, z0, z1)
    fin = box(-P["knob_fin_t_mm"] / 2, P["knob_fin_t_mm"] / 2, 0, P["knob_fin_r_mm"], z0,
              z0 + P["knob_fin_height_mm"])
    s = fuse([body, fin])
    bore_d = P["pot_shaft_d_mm"] + P["knob_bore_fit_mm"]
    depth = min(P["pot_shaft_above_mm"] - 1.0, P["knob_h_mm"] - 1.0)
    bore = cyl(bore_d / 2, z0 - 1, z0 + depth)
    if P["pot_shaft_flat_mm"] > 0:
        flat = P["pot_shaft_flat_mm"] + P["knob_bore_fit_mm"] / 2
        # keep material where x > flat - r  (D-shaft)
        keep = box(-bore_d, flat - bore_d / 2, -bore_d, bore_d, z0 - 2, z0 + depth + 1)
        bore = bore.intersect(keep)
    s = s.cut(bore)
    return s


def make_insert(P, well_id):
    """Local: z = 0 at the plate top (flange underside), +z up."""
    od, fod = P["insert_od_mm"], P["insert_flange_od_mm"]
    ft, sl, ch = P["insert_flange_t_mm"], P["insert_sleeve_mm"], P["insert_chamfer_mm"]
    r = well_id / 2
    rz = [(r, -sl), (od / 2, -sl), (od / 2, 0), (fod / 2, 0), (fod / 2, ft), (r + ch, ft), (r, ft - ch)]
    s = revolve(rz)
    s = fuse([s] + bayonet_ears(P, od, P["sheet_t_mm"]))
    return s.cut(cyl(r, -sl - 1, ft + 1)).cut(revolve([(r - 0.01, ft - ch), (r + ch, ft + 0.01), (0, ft + 0.01), (0, ft - ch)]))


def tube_outer_rz(P, D):
    od = P["tube_od_mm"]; r = od / 2
    ch, chh = P["collar_chamfer_mm"], P["collar_h_mm"]
    zst = -(chh + ch); zcb = D["tube_body_bottom_straight"]
    ztip = -P["tube_len_mm"]; znub = ztip + P["nub_len_mm"]
    rn = P["nub_d_mm"] / 2
    return [(0, 0), (P["collar_od_mm"] / 2, 0), (P["collar_od_mm"] / 2, -chh), (r, zst), (r, zcb),
            (rn + 0.5, znub), (rn, znub), (rn, ztip), (0, ztip)]


def tube_profile(P, D, step=0.02):
    pts = tube_outer_rz(P, D)[1:-1]
    zs, rs = [], []
    for (r0, z0), (r1, z1) in zip(pts[:-1], pts[1:]):
        n = max(2, int(abs(z1 - z0) / step) + 1)
        for k in range(n):
            f = k / (n - 1); zs.append(z0 + f * (z1 - z0)); rs.append(r0 + f * (r1 - r0))
    return zs, rs


def make_tube(P, D):
    """Local: z = 0 at the collar top, +z up (toward the loop)."""
    od = P["tube_od_mm"]; r = od / 2; w = P["tube_wall_mm"]
    ch, chh = P["collar_chamfer_mm"], P["collar_h_mm"]
    zst = -(chh + ch); zcb = D["tube_body_bottom_straight"]
    ztip = -P["tube_len_mm"]; znub = ztip + P["nub_len_mm"]
    rn = P["nub_d_mm"] / 2
    s = revolve(tube_outer_rz(P, D))
    ri = r - w
    # inner bore: straight, then a cone that keeps >= wall thickness
    zc_end = znub + 3.0
    inner = [(0, 1), (ri, 1), (ri, zcb), (0.9, zc_end), (0, zc_end)]
    s = s.cut(revolve(inner))
    # flats on the collar
    fl = P["collar_flats_mm"] / 2
    s = s.cut(box(fl, 20, -20, 20, -chh, 0.5)).cut(box(-20, -fl, -20, 20, -chh, 0.5))
    # crossbar + loop (loop in the XZ plane)
    lt = P["loop_t_mm"]
    bar = box(-(ri + 0.8), ri + 0.8, -lt / 2, lt / 2, 0, 2.0)
    R_o = P["loop_id_mm"] / 2 + P["loop_w_mm"]; R_i = P["loop_id_mm"] / 2
    zc = 2.0 + R_o - 1.0
    ring = cq.Workplane("XZ", origin=(0, lt / 2, 0)).center(0, zc).circle(R_o).circle(R_i).extrude(lt).val()
    s = fuse([s, bar, ring])
    return s


def make_hinge_base(P):
    """Local (x, z) relative to the hinge axis; extruded along Y. Floor top at z = -(t + dz)."""
    t = P["sheet_t_mm"]; dz = P["hinge_axis_dz_mm"]; R = P["hinge_knuckle_r_mm"]
    zf = -(t + dz)                    # top panel top relative to axis
    rh = P["hinge_pin_hole_mm"] / 2
    open_deg = P["lid_open_deg"]
    floor = [(-7, zf), (2, zf), (2, zf + 2), (-7, zf + 2)]
    col = [(-9.0, zf), (-5.0, zf), (-5.0, 16), (-9.0, 16)]
    parts = [_xz(floor, -12, 12), _xz([(-9.0, zf), (-5.0, zf), (-5.0, 4.5), (-9.0, 4.5)], -12, 12)]
    # outer knuckles: |y| in [6.5, 12]
    for y0, y1 in ((-12, -6.5), (6.5, 12)):
        parts.append(_xz([(-6, -2.5), (0, -2.5), (0, 2.5), (-6, 2.5)], y0, y1))
        parts.append(cq.Workplane("XZ", origin=(0, y1, 0)).circle(R).extrude(y1 - y0).val())
    # centre: tall column + stop wedge (the leaf knuckle lives at |y| < 6)
    a = math.radians(open_deg)
    n = (-math.sin(a), math.cos(a))           # rotated top-surface normal of the leaf
    off = -dz + 2.5                           # leaf pad top surface rel. axis when closed
    def line_x(z):                            # stop face: n . p = off
        return (off - n[1] * z) / n[0]
    wedge = [(line_x(6.0), 6.0), (line_x(16.0), 16.0), (-9.0, 16.0), (-9.0, 6.0)]
    parts.append(_xz(col, -6.0, 6.0))
    parts.append(_xz(wedge, -6.0, 6.0))
    s = fuse(parts)
    s = s.cut(cq.Workplane("XZ", origin=(0, 25, 0)).circle(rh).extrude(50).val())
    return s


def make_hinge_leaf(P):
    """Local (x, z) relative to the hinge axis. Pad glued on top of the lid/cover at its back edge."""
    t = P["sheet_t_mm"]; dz = P["hinge_axis_dz_mm"]; R = P["hinge_knuckle_r_mm"]
    z_lt = -dz                                # lid top relative to axis
    rh = P["hinge_pin_hole_mm"] / 2
    pad_c = box(3.0, 18.0, -6.0, 6.0, z_lt, z_lt + 2.5)
    pad_w = box(6.5, 18.0, -12.0, 12.0, z_lt, z_lt + 2.0)
    web = box(0.0, 4.0, -6.0, 6.0, z_lt, 0.0)
    k = cq.Workplane("XZ", origin=(0, 6.0, 0)).circle(R).extrude(12.0).val()
    s = fuse([pad_c, pad_w, web, k])
    s = s.cut(cq.Workplane("XZ", origin=(0, 25, 0)).circle(rh).extrude(50).val())
    return s


def make_handle(P, kind):
    """Local: x = 0 at the lid front edge, z = 0 at the lid top, +x toward the arm.
    Two T-heads go down through keyholes in the lid; slide the insert back to lock."""
    pw = P["peg_w_mm"]; t = P["sheet_t_mm"]; hw = 8.0
    kh = P["key_head_mm"]
    pad = box(-11.0, 0.0, -hw, hw, 0.0, 2.0)
    keys = []
    for y in (-6.0, 6.0):
        keys.append(box(-9.0 - pw / 2, -9.0 + pw / 2, y - pw / 2, y + pw / 2, -t - 0.05 - kh[2] / 2, 0.01))
        keys.append(box(-9.0 - kh[0] / 2, -9.0 + kh[0] / 2, y - kh[1] / 2, y + kh[1] / 2, -t - 0.05 - kh[2], -t - 0.05))
    if kind == "pinch_tab":
        tab = box(-2.6, -1.0, -7.0, 7.0, 1.9, 14.0)
        return fuse([pad, tab] + keys)
    riser = box(-3.0, 0.0, -hw, hw, 1.9, P["handle_clear_mm"] + 0.01)
    lip = box(-3.0, P["handle_overhang_mm"], -hw, hw, P["handle_clear_mm"], P["handle_clear_mm"] + 2.2)
    return fuse([pad, riser, lip] + keys)


def make_cover_lip(P):
    pad = box(-8.0, 0.0, -12.0, 12.0, 0.0, 2.5)
    lip = box(-0.01, P["handle_overhang_mm"], -12.0, 12.0, 0.0, 2.5)
    rib = box(-8.0, P["handle_overhang_mm"], -1.0, 1.0, 2.5, 4.5)
    return fuse([pad, lip, rib])


def make_moc_cradle(P, with_top, floor_h=2.0):
    """Channel around a MOC7811. Local: MOC centre at origin, long axis X, slot up, z=0 at MOC top."""
    l, w, h = P["moc_l_mm"], P["moc_w_mm"], P["moc_h_mm"]
    gi = w / 2 + 0.1; wt = 2.0
    L2 = l / 2 + 1.0
    zb = -h - floor_h
    walls = [box(-L2, L2, gi, gi + wt, zb, (2 if with_top else -h + 3.5)),
             box(-L2, L2, -gi - wt, -gi, zb, (2 if with_top else -h + 3.5))]
    pads = [box(-L2, -l / 2 + 4.5, -gi - wt, gi + wt, zb, -h),
            box(l / 2 - 4.5, L2, -gi - wt, gi + wt, zb, -h)]
    s = walls + pads
    if with_top:
        top = box(-L2, L2, -gi - wt, gi + wt, 0, 2)
        top = top.cut(box(-P["moc_slot_w_mm"] / 2 - 0.3, P["moc_slot_w_mm"] / 2 + 0.3, -gi, gi, -1, 3))
        s.append(top)
        res = fuse(s)
    else:
        res = fuse(s)
        # free the slot sides so the nub path and beam are open
        res = res.cut(box(-P["moc_slot_w_mm"] / 2 - 0.5, P["moc_slot_w_mm"] / 2 + 0.5, -10, 10, -P["moc_slot_depth_mm"], 5))
    return res


def make_ring_cradle(P, D):
    """Local: bowl centre, z absolute."""
    s = cyl(37.0, D["cradle_bot"], D["cradle_top"]).cut(cyl(25.0, D["cradle_bot"] - 1, D["cradle_top"] + 1))
    posts = []
    for ang in (75, 195, 315):
        a = math.radians(ang); x, y = 36 * math.cos(a), 36 * math.sin(a)
        posts.append(cyl(2.5, D["cradle_top"] - 0.01, D["ring_top"], x, y))
        posts.append(cyl(1.475, D["ring_top"] - 0.01, D["deck_top"], x, y))
    s = fuse([s] + posts)
    # notch for the ring's wires
    s = s.cut(box(-41, -30, -4, 4, D["cradle_bot"] - 1, D["cradle_top"] + 1))
    return s


def slope_pt(D, ylat, s, d):
    """Point on/behind the control face: s along the inner-face plate frame (0..L), d inward from outer face."""
    return pt(D["Ms"], (ylat, s, D["t"] - d))


def gusset_profile(P, D):
    yc = D["slope_L"] / 2
    s0 = yc - P["bb_w_mm"] / 2; s1 = yc + P["bb_w_mm"] / 2
    dt = D["bb_depth"]; db = dt + P["bb_h_mm"]
    def p(s, d):
        q = slope_pt(D, 0, s, d); return (q[0], q[2])
    A_ = p(s0 - 3, dt + 1); B = p(s0, dt + 1); C = p(s0, db); Dd = p(s1, db); E = p(s1, dt + 1)
    F = p(s1 + 3, dt + 1); G = p(s1 + 3, db + 3); Ap = p(s0 - 3, db + 3)
    t = D["t"]
    from shapely.geometry import Polygon
    outer = Polygon([A_, B, C, Dd, E, F, G, (G[0], t), (Ap[0], t), Ap])
    inner = Polygon([G, (G[0], t), (Ap[0], t), Ap]).buffer(-6.0, join_style=2)
    shape = outer.difference(inner)
    # one closed outline: open the window to the bottom edge would weaken it, so keep it as a hole
    return shape, [G[0] + 8, Ap[0] - 8]


def make_oled_frame(P, D):
    """In product frame directly. Plate x in [xf - t - 2, xf - t], window, 4 pegs toward -X."""
    t = D["t"]; x1 = D["xf"] - t; x0 = x1 - 2.0
    bw, bh, bt = P["oled_board_mm"]; gw, gh, gt = P["oled_glass_mm"]
    zc = P["oled_center_z_mm"]
    plate = box(x0, x1, -bw / 2 - 2, bw / 2 + 2, zc - bh / 2 - 2, zc + bh / 2 + 2)
    vw, vh = P["oled_view_mm"]; zo = zc + P["oled_view_offset_mm"]
    plate = plate.cut(box(x0 - 1, x1 + 1, -vw / 2 - 1, vw / 2 + 1, zo - vh / 2 - 1, zo + vh / 2 + 1))
    hx, hz = P["oled_hole_pitch_mm"]
    pegs = []
    for sy in (-1, 1):
        for sz in (-1, 1):
            pegs.append(xf(cyl(P["oled_hole_d_mm"] / 2 - 0.1, 0, gt + bt + 0.6),
                           frame((x0, sy * hx / 2, zc + sz * hz / 2), (0, 1, 0), (0, 0, -1))) )
    return fuse([plate] + pegs)


def make_pico_tray(P, x0, y0):
    l, w = P["pico_l_mm"], P["pico_w_mm"]
    t = P["sheet_t_mm"]
    outer = box(x0, x0 + l + 4, y0, y0 + w + 4, t, t + 4.5)
    inner = box(x0 + 2, x0 + l + 2, y0 + 2, y0 + w + 2, t + 1.5, t + 6)
    s = outer.cut(inner)
    s = s.cut(box(x0 - 1, x0 + 2.5, y0 + 2 + w / 2 - 5, y0 + 2 + w / 2 + 5, t + 1.5, t + 6))  # USB end open
    return s


def make_lid_tab(P, D):
    """Pad glued under the lid + an arc tab (about the hinge axis) that drops into the lid sensor slot."""
    H = D["H"]; ax, az = D["axis"]
    lx, ly = D["lid_moc_x"], D["lid_moc_y"]
    pad = box(lx - 4.5, lx + 4.5, ly - 4.0, ly + 4.0, H - 2.0, H)
    zb = D["lid_beam_z"] - 2.0
    zm = (zb + D["lid_moc_top"]) / 2          # centre the arc on the part that sits in the slot
    R = math.hypot(lx - ax, zm - az)
    ht = 1.0                                  # half thickness (2.0 mm tab)
    ring = cq.Workplane("XZ", origin=(0, ly + 2.5, 0)).center(ax, az).circle(R + ht).circle(R - ht).extrude(5.0).val()
    clip = box(lx - 10, lx + 10, ly - 3, ly + 3, zb, H - 1.99)
    tab = ring.intersect(clip)
    return fuse([pad, tab])


# ----------------------------------------------------------------------------
# Rack
# ----------------------------------------------------------------------------
def build_rack(P, D, parts, rev):
    t = D["t"]; Mr = D["Mrack"]
    hin = D["rack_in"] / 2; hv = D["rack_hv"]; f = P["slot_fit_mm"] / 2
    ply = "plywood"
    cz = D["rack_cover_z"]
    w = P["tab_w_mm"]

    def hplate(name, z0, v0, v1, holes_d=None, tabs_v=None):
        # local x = u (row), y = v, z up; tabs at both u ends into the end plates
        loc = box(-hin, hin, v0, v1, 0, t)
        tabs = []; cutters = []
        for c in tabs_v:
            for sgn in (-1, 1):
                x0, x1 = (hin, hin + t) if sgn > 0 else (-hin - t, -hin)
                tabs.append(box(x0, x1, c - w / 2, c + w / 2, 0, t))
                cutters.append(box(x0 - f, x1 + f, c - w / 2 - f, c + w / 2 + f, -f, t + f))
        loc = fuse([loc] + tabs)
        if holes_d == "bayonet":
            for u in D["rack_u"]:
                loc = loc.cut(bayonet_cutter(P, P["insert_od_mm"], u, 0, t))
        elif holes_d:
            for u in D["rack_u"]:
                loc = loc.cut(cyl(holes_d / 2, -1, t + 1, u, 0))
        M = Mr @ frame((0, 0, z0), (1, 0, 0), (0, 1, 0))
        parts[name] = Part(name, "laser", xf(loc, M), ply, local=loc, M=M, t=t, group="rack")
        return [xf(c, M) for c in cutters]

    cut_end = []
    cut_end += hplate("rack_base", 0.0, -hv, hv, None, [-hv / 2, hv / 2])
    cut_end += hplate("rack_middle", 24.0, -hv, hv, P["tube_od_mm"] + 3.0, [-hv / 2, hv / 2])
    cut_end += hplate("rack_top", D["rack_top_bot"], -hv, P["rack_top_front_mm"],
                      P["well_id_mm"]["rack"], [-hv / 2, hv / 2])
    cut_end += hplate("rack_back_strip", cz - t, -hv, -hv + 7.0, None, [-hv + 3.5])

    # end plates: profile in (v, z), plate thickness along u
    prof = [(-hv, 0), (hv, 0), (hv, cz), (-hv, cz)]
    for nm, u0 in (("rack_end_L", -hin - t), ("rack_end_R", hin)):
        M = Mr @ frame((u0, 0, 0), (0, 1, 0), (0, 0, 1))   # local x->v, y->z, thickness along +u
        loc = prism(prof, 0, t)
        sol = cut(xf(loc, M), cut_end)
        parts[nm] = Part(nm, "laser", sol, ply, local=xf(sol, np.linalg.inv(M)), M=M, t=t, group="rack")

    # cover (clear acrylic)
    av, az = D["rack_axis"]
    v_back = av + 3.0; v_front = hv + 2.0
    loc = box(-hin - t, hin + t, v_back, v_front, 0, t)
    M = Mr @ frame((0, 0, cz), (1, 0, 0), (0, 1, 0))
    parts["rack_cover"] = Part("rack_cover", "laser", xf(loc, M), "acrylic_clear", local=loc, M=M, t=t,
                               group="rack")
    D["rack_cover_front_v"] = v_front

    # printed hinge (same parts as the lid), laser lip
    hb, hl = make_hinge_base(P), make_hinge_leaf(P)
    Mh = np.eye(4)
    Mh[:3, :3] = (Mr[:3, :3] @ np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]]))
    Mh[:3, 3] = pt(Mr, (0, av, az))
    D["Mh_rack"] = Mh
    parts["rack_hinge_base"] = Part("rack_hinge_base", "print", xf(hb, Mh), "PLA", local=hb, M=Mh, group="rack")
    parts["rack_hinge_leaf"] = Part("rack_hinge_leaf", "print", xf(hl, Mh), "PLA", local=hl, M=Mh, group="rack")
    pin = cq.Workplane("XZ", origin=(0, 11.75, 0)).circle(1.75 / 2).extrude(23.5).val()
    parts["rack_hinge_pin"] = Part("rack_hinge_pin", "stock", xf(pin, Mh), "filament", local=pin, M=Mh, group="rack",
                                   note="23.5 mm of 1.75 mm filament")
    Ml = np.eye(4)
    Ml[:3, :3] = Mr[:3, :3] @ np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])   # local x -> +v, y -> -u
    Ml[:3, 3] = pt(Mr, (0, v_front, cz + t))
    lip = box(-8.0, P["handle_overhang_mm"], -12.0, 12.0, 0, t)
    parts["rack_cover_lip"] = laser_part("rack_cover_lip", lip, Ml, t, "plywood", group="rack",
                                         note="glued on the cover, overhangs its front edge")
    D["cover_group"] = ["rack_cover", "rack_hinge_leaf", "rack_cover_lip"]
    D["Ml_rack"] = Ml


# ----------------------------------------------------------------------------
# Electronics placeholders (for fit checks and renders only)
# ----------------------------------------------------------------------------
def build_electronics(P, D):
    E = {}
    t = D["t"]; yc = D["slope_L"] / 2; cy = P["ctrl_y_mm"]
    Ms = D["Ms"]

    def on_face(ylat, solid_local):
        # local frame at the control: x = Y, y = along slope, z = outward normal, z=0 at outer face
        M = Ms @ frame((ylat, yc, t), (1, 0, 0), (0, 1, 0))
        return xf(solid_local, M)
    bb = D["bb_depth"]
    for k in ("start", "stop", "time"):
        b = P["tact_body_mm"]
        body = box(-b / 2, b / 2, -b / 2, b / 2, -bb, -bb + P["tact_body_h_mm"])
        stem = cyl(P["tact_stem_d_mm"] / 2, -bb + P["tact_body_h_mm"] - 0.01, -bb + P["tact_stem_top_mm"])
        E[f"switch_{k}"] = on_face(cy[k], fuse([body, stem]))
    E["breadboard"] = on_face(0, box(-P["bb_l_mm"] / 2, P["bb_l_mm"] / 2, -P["bb_w_mm"] / 2, P["bb_w_mm"] / 2,
                                     -bb - P["bb_h_mm"], -bb))
    tb = P["toggle_body_mm"]
    tog = fuse([box(-tb[0] / 2, tb[0] / 2, -tb[1] / 2, tb[1] / 2, -tb[2], -t),
                cyl(P["toggle_bushing_mm"] / 2, -t - 0.01, 6.0),
                cyl(5.0, 0.0, 2.0)])
    lev = cyl(P["toggle_lever_d_mm"] / 2, 0, P["toggle_lever_len_mm"])
    lev = xf(lev, rot_x(-15) @ frame((0, 0, 6.0), (1, 0, 0), (0, 1, 0)))
    E["toggle"] = on_face(cy["power"], fuse([tog, lev]))
    sd = P["pot_shaft_d_mm"]
    shaft = cyl(sd / 2, P["pot_bushing_above_mm"] - 0.01, P["pot_bushing_above_mm"] + P["pot_shaft_above_mm"])
    if P["pot_shaft_flat_mm"] > 0:
        shaft = shaft.intersect(box(-sd, P["pot_shaft_flat_mm"] - sd / 2, -sd, sd, -50, 50))
    shaft = xf(shaft, rotz(P["dial_sweep_deg"] / 2))
    pot = fuse([cyl(P["pot_body_d_mm"] / 2, -P["pot_body_depth_mm"], -t),
                cyl(3.6, -t - 0.01, P["pot_bushing_above_mm"]), cyl(5.0, 0, 2.0), shaft])
    E["pot"] = on_face(cy["speed"], pot)
    # OLED (header at the bottom: display rotated 180 deg in firmware)
    bw, bh, bt = P["oled_board_mm"]; gw, gh, gt = P["oled_glass_mm"]
    x_face = D["xf"] - t
    zc = P["oled_center_z_mm"]
    glass = box(x_face - gt, x_face, -gw / 2, gw / 2, zc - gh / 2, zc + gh / 2)
    board = box(x_face - gt - bt, x_face - gt, -bw / 2, bw / 2, zc - bh / 2, zc + bh / 2)
    hdr = box(x_face - gt - bt - 14.0, x_face - gt - bt, -6, 6, zc - bh / 2 + 0.5, zc - bh / 2 + 3.0)
    E["oled"] = fuse([glass, board, hdr])
    bx, by = D["bowl"]
    E["ring"] = cyl(P["ring_od_mm"] / 2, D["ring_bot"], D["ring_top"], bx, by).cut(
        cyl(P["ring_id_mm"] / 2, D["ring_bot"] - 1, D["ring_top"] + 1, bx, by))
    l, w, h = P["moc_l_mm"], P["moc_w_mm"], P["moc_h_mm"]
    def moc(x, y, ztop):
        body = box(x - l / 2, x + l / 2, y - w / 2, y + w / 2, ztop - h, ztop)
        return body.cut(box(x - P["moc_slot_w_mm"] / 2, x + P["moc_slot_w_mm"] / 2, y - w, y + w,
                            ztop - P["moc_slot_depth_mm"], ztop + 1))
    E["moc_lid"] = moc(D["lid_moc_x"], D["lid_moc_y"], D["lid_moc_top"])
    wa = D["wells"]["A"]
    E["moc_tube"] = moc(wa[0], wa[1], D["moc_tube_top"])
    px, py = D["pico_xy"]
    E["pico"] = box(px - 3.3 - P["pico_w_mm"], px - 3.3, py + 3.3, py + 3.3 + P["pico_l_mm"],
                    t, t + P["pico_h_mm"])
    return E


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    M = np.eye(4); M[1, 1] = c; M[1, 2] = -s; M[2, 1] = s; M[2, 2] = c
    return M


# ----------------------------------------------------------------------------
# Build everything
# ----------------------------------------------------------------------------
def build(P=None, rev="A", tube_in="A_seated", lid_deg=0.0, cover_deg=0.0, with_tubes=True):
    P = P or PARAMS
    D = derive(P)
    parts = {}
    store = {"side": [], "base": []}
    build_body(P, D, parts, store)
    t = D["t"]; Ms = D["Ms"]; yc = D["slope_L"] / 2; cy = P["ctrl_y_mm"]

    def face_M(ylat):
        return Ms @ frame((ylat, yc, t), (1, 0, 0), (0, 1, 0))

    # ---- buttons: Stop = printed bayonet bezel + printed cap (F1); Start/Time = laser cap stacks in plain holes
    bz = make_bezel(P, P["bezel_clearance_mm"]["stop"], depth=D["bezel_sleeve"])
    M = face_M(cy["stop"]) @ rotz(P["bayo_lock_deg"])
    parts["bezel_stop"] = Part("bezel_stop", "print", xf(bz, M), "PLA", local=bz, M=M, rev=rev,
                               note=f"bore clearance {P['bezel_clearance_mm']['stop']:.2f} mm per side",
                               print_M=rot_x(180))
    cap = make_cap(P, D)
    parts["cap_stop"] = Part("cap_stop", "print", xf(cap, M), "PLA", local=cap, M=M,
                             note="captive in the Stop bezel: bezel and cap swap together")
    stack, plies, captop = laser_cap_plies(P, D)
    D["laser_cap_top"] = captop
    for k in ("start", "time"):
        Mc = face_M(cy[k])
        pc = Part(f"cap_{k}", "laser_stack", xf(stack, Mc), "plywood", local=stack, M=Mc,
                  note="3 laser discs glued: 2 x plunger + 1 x flange")
        pc.plies = plies
        parts[f"cap_{k}"] = pc
    # ---- knob: 4 laser plies
    kst, kplies = laser_knob_plies(P, D)
    sweep = P["dial_sweep_deg"]
    Mk = face_M(cy["speed"]) @ rotz(sweep / 2)       # fin at the 1000 rpm end
    pk = Part("dial_knob", "laser_stack", xf(kst, Mk), "plywood", local=kst, M=Mk, note="4 laser plies glued")
    pk.plies = kplies
    parts["dial_knob"] = pk

    # ---- wells: A = printed bayonet insert (F3); B = plain laser hole in the rotor plate
    bx, by = D["bowl"]
    wx, wy = D["wells"]["A"]
    ins = make_insert(P, P["well_id_mm"]["A"])
    M = frame((wx, wy, D["deck_top"]), (0, 1, 0), (-1, 0, 0)) @ rotz(P["bayo_lock_deg"])
    parts["well_insert_A"] = Part("well_insert_A", "print", xf(ins, M), "PLA", local=ins, M=M, rev=rev,
                                  note=f"ID {P['well_id_mm']['A']:.2f} mm", print_M=rot_x(180))
    D["well_B_origin"] = D["deck_top"] + D["rest_origin"](P["well_id_mm"]["B"], ch=0)

    # ---- lid (acrylic) + printed hinge + laser handle + laser sensor fin, all built closed
    H = D["H"]; lf = P["lid_front_x_mm"]; lb = D["lid_back_x"]; hw = P["lid_half_w_mm"]
    lid_loc = cq.Workplane("XY").rect(2 * hw, lf - lb).extrude(t).edges("|Z").fillet(P["lid_corner_r_mm"]).val()
    lid_loc = xf(lid_loc, frame((0, (lf - lb) / 2, 0), (1, 0, 0), (0, 1, 0)))
    Mlid = frame((lf, 0, H), (0, 1, 0), (-1, 0, 0))
    lid = Part("lid", "laser", xf(lid_loc, Mlid), "acrylic_clear", local=lid_loc, M=Mlid, t=t,
               note="leave the paper off; clear")
    hb, hl = make_hinge_base(P), make_hinge_leaf(P)
    Mh = np.eye(4); Mh[:3, 3] = (D["axis"][0], 0, D["axis"][1])
    parts["lid_hinge_base"] = Part("lid_hinge_base", "print", xf(hb, Mh), "PLA", local=hb, M=Mh,
                                   print_M=rot_x(90), note="glued to the top panel; same part as rack_hinge_base")
    leaf = Part("lid_hinge_leaf", "print", xf(hl, Mh), "PLA", local=hl, M=Mh,
                print_M=rot_x(90), note="glued on the lid; same part as rack_hinge_leaf")
    pin = cq.Workplane("XZ", origin=(0, 11.75, 0)).circle(1.75 / 2).extrude(23.5).val()   # 1.75 mm filament
    parts["lid_hinge_pin"] = Part("lid_hinge_pin", "stock", xf(pin, Mh), "filament", local=pin, M=Mh,
                                  note="23.5 mm of 1.75 mm filament")
    # handle: 3-ply laser laminate, centred on y = 0
    Mhd = frame((lf, 0, D["lid_top"]), (1, 0, 0), (0, 1, 0))     # x toward the arm, z up, origin at lid front edge top
    hprof = handle_profiles(P, P["handle_type"])
    layers = [hprof[0][1], hprof[1][1], hprof[0][1]] if len(hprof) == 2 else [hprof[0][1]] * 3
    hsol = fuse([build_xz_part("x", g, -1.5 * t + i * t, Mhd, t).solid for i, g in enumerate(layers)])
    handle = Part("lid_handle", "laser_stack", hsol, "plywood", local=None, M=Mhd, rev=rev, note=P["handle_type"])
    handle.plies = [(nm, prism(g, 0, t), q) for nm, g, q in hprof]
    # lid slots for the J-tabs (insertion position = locked position + key_slide)
    f = P["peg_hole_fit_mm"]; ks = P["key_slide_mm"]
    lid_cuts = []
    for xs in (-8.0, -17.0):
        lid_cuts.append(xf(box(xs - 1.5 - f, xs + 1.5 + ks + f, -1.5 * t - f, 1.5 * t + f, -1, t + 1), Mhd @ frame((0, 0, -t), (1, 0, 0), (0, 1, 0))))
    # sensor fin: laser plywood, arc about the hinge axis so it leaves the slot cleanly; tab glued in a lid slot
    ax, az = D["axis"]; lx, ly = D["lid_moc_x"], D["lid_moc_y"]
    zb = D["lid_beam_z"] - 2.0
    zm = (zb + D["lid_moc_top"]) / 2
    Rf = math.hypot(lx - ax, zm - az)
    from shapely.geometry import Point
    band = Point(ax, az).buffer(Rf + 1.2, 256).difference(Point(ax, az).buffer(Rf - 1.2, 256)).intersection(
        _rect(lx - 10, zb, lx + 10, H + 0.01))
    xH = ax + math.sqrt(Rf ** 2 - (H - az) ** 2)
    fin_poly = band.union(_rect(xH - 1.2, H - 0.01, xH + 1.2, H + t)).buffer(0)
    fin = build_xz_part("lid_sensor_fin", fin_poly, ly - t / 2, np.eye(4), t, note="glued into a slot in the lid")
    lid_cuts.append(box(xH - 1.2 - f, xH + 1.2 + f, ly - t / 2 - f, ly + t / 2 + f, H - 1, H + t + 1))
    recut(lid, lid_cuts)
    parts["lid"] = lid; parts["lid_hinge_leaf"] = leaf; parts["lid_handle"] = handle; parts["lid_sensor_fin"] = fin
    D["lid_group"] = ["lid", "lid_hinge_leaf", "lid_handle", "lid_sensor_fin"]
    # top panel: fin opening, handle-foot relief
    tp = parts["top_panel"]
    recut(tp, [box(lx - 3.5, lx + 4.5, ly - 2.6, ly + 2.6, H - t - 1, H + 1),
               box(lf - 22.5 - ks, lf + 2.0, -1.5 * t - 1.0, 1.5 * t + 1.0, H - t - 1, H + 1)])
    if lid_deg:
        Rlid = rot_about_y_axis(D["axis"], lid_deg)
        for k in D["lid_group"]:
            parts[k].solid = xf(parts[k].solid, Rlid)
    D["Rlid"] = rot_about_y_axis(D["axis"], lid_deg)

    # ---- sensors: both MOC7811s are glued; the tube sensor stands on two laser riser frames
    wa = D["wells"]["A"]
    l2 = P["moc_l_mm"] / 2 + 1.0; w2 = P["moc_w_mm"] / 2 + 2.0
    riser = box(-l2, l2, -w2, w2, 0, t).cut(box(-6, 6, -2.6, 2.6, -1, t + 1))
    for i in range(2):
        Mr_ = frame((wa[0], wa[1], t + i * t), (1, 0, 0), (0, 1, 0))
        parts[f"tube_sensor_riser_{i+1}"] = laser_part(f"tube_sensor_riser_{i+1}", riser, Mr_, t, "plywood",
                                                       note="2 stacked frames; the MOC7811 is glued on top")

    # breadboard gussets: laser-cut plywood, tabs down into the base plate
    f2 = P["slot_fit_mm"] / 2
    gus_base_cut = []
    gy = 37.5
    for nm, y_org in (("gusset_L", -gy), ("gusset_R", gy + t)):
        poly, tab_x = gusset_profile(P, D)
        loc = prism(poly, 0, t)
        tabs = [box(x - 4, x + 4, 0, t + 0.01, 0, t) for x in tab_x]
        loc = fuse([loc] + tabs)
        Mg = frame((0, y_org, 0), (1, 0, 0), (0, 0, 1))      # local x -> X, y -> Z, thickness -> -Y
        parts[nm] = laser_part(nm, loc, Mg, t, "plywood", note="breadboard support")
        for x in tab_x:
            gus_base_cut.append(xf(box(x - 4 - f2, x + 4 + f2, -f2, t + f2, -f2, t + f2), Mg))
    # deck notches for the gussets
    rp = parts["rotor_plate"]
    gus_cut = []
    for nm in ("gusset_L", "gusset_R"):
        g = parts[nm].solid
        sl = g.intersect(box(-100, 100, -100, 100, D["deck_bot"] - 0.5, D["deck_top"] + 0.5))
        sb = sl.BoundingBox()
        gus_cut.append(box(sb.xmin - 0.4, 40, sb.ymin - 0.4, sb.ymax + 0.4, D["deck_bot"] - 1, D["deck_top"] + 1))
    rp.solid = cut(rp.solid, gus_cut)
    rp.local = xf(rp.solid, np.linalg.inv(rp.M))

    # Pico holder: laser-cut frame glued on the base, the Pico sits in the pocket
    l, w = P["pico_l_mm"] + 0.6, P["pico_w_mm"] + 0.6
    D["pico_xy"] = (-34.9, -(l + 6) / 2)          # frame corner; long axis along Y, behind the wells
    px0, py0 = D["pico_xy"]
    loc = box(0, l + 6, 0, w + 6, 0, t).cut(box(3, 3 + l, 3, 3 + w, -1, t + 1)).cut(box(-1, 4, 3 + w / 2 - 5, 3 + w / 2 + 5, -1, t + 1))
    Mp = frame((px0, py0, t), (0, 1, 0), (-1, 0, 0))   # local x -> +Y, local y -> -X
    parts["pico_frame"] = laser_part("pico_frame", loc, Mp, t, "plywood", note="glued to the base; USB end open")
    peg_holes = gus_base_cut

    # base plate holes + placement marks
    finish_base(P, D, parts, store, peg_holes)
    Mb = D["Mb"]; xb0 = D["base_x_front"]
    def mark_rect(x0, x1, y0, y1):
        # engrave outline (0.6 mm line) in base-local coords (local y = xb0 - X)
        r = []
        for (a0, a1, b0, b1) in ((x0, x1, y0, y0 + 0.6), (x0, x1, y1 - 0.6, y1), (x0, x0 + 0.6, y0, y1), (x1 - 0.6, x1, y0, y1)):
            r.append(np.array([[b0, xb0 - a0], [b1, xb0 - a0], [b1, xb0 - a1], [b0, xb0 - a1]]))
        return r
    l2 = P["moc_l_mm"] / 2 + 1; g2 = P["moc_w_mm"] / 2 + 2.1
    parts["base_plate"].engrave = mark_rect(wa[0] - l2, wa[0] + l2, wa[1] - g2, wa[1] + g2) + \
        mark_rect(D["pico_xy"][0] - P["pico_w_mm"] - 6.6, D["pico_xy"][0], D["pico_xy"][1], D["pico_xy"][1] + P["pico_l_mm"] + 6.6)

    # tubes
    if with_tubes:
        tube = make_tube(P, D)
        if tube_in:
            wid = P["well_id_mm"]["A"]
            o = D["flange_top"] + D["origin_above_flange"](wid)
            parts["tube_1"] = Part("tube_1", "print", xf(tube, frame((wa[0], wa[1], o), (1, 0, 0), (0, 1, 0))),
                                   "PLA", local=tube, M=frame((wa[0], wa[1], o), (1, 0, 0), (0, 1, 0)),
                                   note="print 1 (the model shows it in well A and in the rack); brim, nub down")
        Mr = D["Mrack"]
        o2 = D["rack_flange_top"] + D["origin_hole"]
        Mt2 = Mr @ frame((D["rack_u"][1], 0, o2), (1, 0, 0), (0, 1, 0))
        parts["tube_2"] = Part("tube_2", "print", xf(tube, Mt2), "PLA", local=tube, M=Mt2, group="rack")

    build_rack(P, D, parts, rev)
    if cover_deg:
        Mr = D["Mrack"]; av, az = D["rack_axis"]
        # rotate about the rack hinge axis (line along u through v=av, z=az), lifting +v
        R = Mr @ rot_about_y_axis_v(av, az, cover_deg) @ np.linalg.inv(Mr)
        for nm in D["cover_group"]:   # pin stays: it is the axis
            parts[nm].solid = xf(parts[nm].solid, R)
        D["Rcover"] = R
    E = build_electronics(P, D)
    return parts, E, D


def rot_about_y_axis_v(v0, z0, deg):
    """Rotation in the rack (v, z) plane about a line along u, lifting +v."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    M = np.eye(4); M[1, 1] = c; M[1, 2] = -s; M[2, 1] = s; M[2, 2] = c
    T1 = np.eye(4); T1[1, 3] = -v0; T1[2, 3] = -z0
    T2 = np.eye(4); T2[1, 3] = v0; T2[2, 3] = z0
    return T2 @ M @ T1


def build_coupon(P):
    """Three Stop bezels at the coupon clearances, flange down, joined by two thin bars.
    Index = number of notches in each flange rim (1, 2, 3 = first, second, third clearance)."""
    cl = P["coupon_clearances_mm"]
    fo = P["bezel_flange_od_mm"]
    pitch = fo + 3.0
    n = len(cl)
    sol, cuts = [], []
    for i, c in enumerate(cl):
        x = (i - (n - 1) / 2) * pitch
        bz = make_bezel(P, c, depth=P["coupon_sleeve_mm"], ears=False)
        bz = xf(bz, frame((x, 0, P["bezel_flange_t_mm"]), (1, 0, 0), (0, -1, 0)))  # flange on the bed
        sol.append(bz)
        for k in range(i + 1):
            a = math.radians(90 + (k - i / 2) * 18)
            cx, cy = x + (fo / 2) * math.cos(a), (fo / 2) * math.sin(a)
            cuts.append(xf(box(-0.6, 0.6, -1.2, 1.2, -1, 5), frame((cx, cy, 0), (math.cos(a), math.sin(a), 0), (-math.sin(a), math.cos(a), 0))))
    L = pitch * (n - 1)
    for y in (-fo / 2 + 2.5, fo / 2 - 2.5):
        bar = box(-L / 2, L / 2, -1.5, 1.5, 0, 1.2)
        bar = xf(bar, frame((0, -y, 0), (1, 0, 0), (0, 1, 0)))
        sol.append(bar)
    return cut(fuse(sol), cuts)
