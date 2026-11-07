"""Generate every deliverable for design brief v4 into ./out"""
import os, json, math, copy, subprocess, re, shutil, csv
import numpy as np
import cadquery as cq
import yaml
import appliance as ap
import checks

OUT = os.path.abspath("out")
for d in ("stl/print_revA", "stl/print_revB", "stl/print_common", "stl/laser_fallback", "laser", "renders", "gcode"):
    os.makedirs(os.path.join(OUT, d), exist_ok=True)

P = ap.PARAMS
PATCH = {"bezel_clearance_mm": {"stop": 0.40}, "handle_type": "hook_lip", "well_id_mm": {"A": 16.8}}
PB = ap.apply_patch(P, PATCH)

partsA, EA, DA = ap.build(P, rev="A")
partsB, EB, DB = ap.build(PB, rev="B")
t = DA["t"]


# ----------------------------------------------------------------------------
# 1. printed STLs (print orientation, on the bed, centred)
# ----------------------------------------------------------------------------
def on_bed(p):
    s = p.local if p.local is not None else p.solid
    if p.print_M is not None:
        s = ap.xf(s, p.print_M)
    bb = s.BoundingBox()
    M = np.eye(4); M[:3, 3] = (-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin)
    return ap.xf(s, M)


PRINT = []   # (file, folder, part, qty, rev, what)
def add(fname, folder, part, qty, rev, what):
    PRINT.append(dict(file=fname, folder=folder, part=part, qty=qty, rev=rev, what=what))

A_ = partsA; B_ = partsB
PA05 = ap.apply_patch(P, {"bezel_clearance_mm": {"stop": P["stop_variants_mm"][1]}})
pA15, _, _ = ap.build(PA05)
add("bezel_stop_revA_F1_0.05", "print_revA", A_["bezel_stop"], 1, "A", "F1: Stop bezel, 0.05 mm/side (tight variant)")
add("bezel_stop_revA_F1_0.15", "print_revA", pA15["bezel_stop"], 1, "A", "F1: Stop bezel, 0.15 mm/side (looser variant); keep whichever binds every time")
add("bezel_stop_revB", "print_revB", B_["bezel_stop"], 1, "B", "F1 fix: Stop bezel, 0.40 mm/side")
add("cap_stop", "print_common", A_["cap_stop"], 2, "A+B", "Stop cap: one rides in the Rev A bezel, one in the Rev B bezel")
add("well_insert_A_revA_F3", "print_revA", A_["well_insert_A"], 1, "A", f"F3: well A insert, ID {P['well_id_mm']['A']:.1f}")
add("well_insert_A_revB", "print_revB", B_["well_insert_A"], 1, "B", "F3 fix: well A insert, ID 16.8")
add("hinge_base", "print_common", A_["lid_hinge_base"], 2, "A+B", "lid + rack cover hinge, with the 105 deg stop")
add("hinge_leaf", "print_common", A_["lid_hinge_leaf"], 2, "A+B", "glued on the lid / cover")
add("test_tube", "print_common", A_["tube_1"], 1, "A+B", "test tube (6 mm brim, nub down)")

for it in PRINT:
    s = on_bed(it["part"])
    it["solid"] = s
    path = os.path.join(OUT, "stl", it["folder"], it["file"] + ".stl")
    cq.exporters.export(s, path, tolerance=0.03, angularTolerance=0.15)
    it["path"] = path
    bb = s.BoundingBox()
    it["bbox"] = (round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1))
    it["valid"] = s.isValid() and len(s.Solids()) == 1
    it["vol"] = s.Volume()


# ----------------------------------------------------------------------------
# 2. slice every printed STL
# ----------------------------------------------------------------------------
INI = os.path.join(OUT, "gcode", "pla_0.2.ini")
open(INI, "w").write("""layer_height = 0.2
first_layer_height = 0.2
nozzle_diameter = 0.4
filament_diameter = 1.75
filament_density = 1.24
perimeters = 2
top_solid_layers = 4
bottom_solid_layers = 3
fill_density = 15%
fill_pattern = gyroid
support_material = 0
brim_width = 0
bed_shape = 0x0,220x0,220x220,0x220
max_print_height = 250
temperature = 210
bed_temperature = 60
perimeter_speed = 45
external_perimeter_speed = 25
infill_speed = 80
solid_infill_speed = 60
top_solid_infill_speed = 40
travel_speed = 150
first_layer_speed = 20
gap_fill_speed = 30
small_perimeter_speed = 20
machine_max_acceleration_extruding = 1250
machine_max_acceleration_x = 1000
machine_max_acceleration_y = 1000
default_acceleration = 1000
""")


def slice_one(stl, brim=False):
    g = os.path.join(OUT, "gcode", os.path.basename(stl).replace(".stl", ".gcode"))
    cmd = ["prusa-slicer", "--load", INI, "--export-gcode", "--center", "110,110", "-o", g, stl]
    if brim:
        cmd[3:3] = ["--brim-width", "6"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return None, None, r.stderr[-400:]
    txt = open(g, errors="ignore").read()
    m = re.search(r"estimated printing time \(normal mode\) = ([^\n]+)", txt)
    gr = re.search(r"filament used \[g\] = ([0-9.]+)", txt)
    def secs(s):
        tot = 0
        for v, u in re.findall(r"(\d+)([dhms])", s):
            tot += int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u]
        return tot
    return (secs(m.group(1)) if m else None), (float(gr.group(1)) if gr else None), ""


for it in PRINT:
    s_, g_, err = slice_one(it["path"], brim=(it["file"] == "test_tube"))
    it["sec"], it["g"], it["err"] = s_, g_, err

FAST = os.path.join(OUT, "gcode", "pla_0.2_fast.ini")
txt = open(INI).read()
for k, v in (("perimeter_speed", 120), ("external_perimeter_speed", 80), ("infill_speed", 200),
             ("solid_infill_speed", 150), ("top_solid_infill_speed", 80), ("travel_speed", 250),
             ("gap_fill_speed", 80), ("small_perimeter_speed", 50), ("first_layer_speed", 30),
             ("machine_max_acceleration_extruding", 4000), ("machine_max_acceleration_x", 4000),
             ("machine_max_acceleration_y", 4000), ("default_acceleration", 3000)):
    txt = re.sub(rf"^{k} = .*$", f"{k} = {v}", txt, flags=re.M)
open(FAST, "w").write(txt)


def slice_plate(name, files, ini, brim=False):
    g = os.path.join(OUT, "gcode", f"{name}.gcode")
    cmd = ["prusa-slicer", "--load", ini, "--export-gcode", "--merge", "--duplicate-distance", "4", "-o", g]
    if brim:
        cmd += ["--brim-width", "6"]
    cmd += files
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return dict(name=name, error=r.stderr[-300:] + r.stdout[-300:])
    tx = open(g, errors="ignore").read()
    m_ = re.search(r"estimated printing time \(normal mode\) = ([^\n]+)", tx)
    gr = re.search(r"; filament used \[g\] = ([0-9.]+)", tx)
    sec = sum(int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for v, u in re.findall(r"(\d+)([dhms])", m_.group(1)))
    return dict(name=name, sec=sec, g=float(gr.group(1)), n=len(files))


byf = {i["file"]: i for i in PRINT}
def files_of(names):
    out = []
    for nm in names:
        out += [byf[nm]["path"]] * byf[nm]["qty"]
    return out

PLATES = {
    "plate1_everything": [i["file"] for i in PRINT if i["file"] != "test_tube"] + ["test_tube"],
}
PLATE_RES = {}
for prof, ini in (("standard", INI), ("fast", FAST)):
    res = []
    for nm, lst in PLATES.items():
        res.append(slice_plate(f"{nm}_{prof}", files_of(lst), ini, brim=True))
    for nm in ("bezel_stop_revB", "well_insert_A_revB"):
        res.append(slice_plate(f"single_{nm}_{prof}", [byf[nm]["path"]], ini))
    PLATE_RES[prof] = res

# ----------------------------------------------------------------------------
# 3. laser files: DXF + SVG per material sheet, nested; STL fallback per part
# ----------------------------------------------------------------------------
class _Ply:
    def __init__(self, local, material, t):
        self.local = local; self.material = material; self.t = t; self.engrave = []; self.solid = local; self.kind = "laser"


LASER = {}
for src in (partsA, partsB):
    for k, p in src.items():
        nm = k if src is partsA else k + "_revB"
        if p.kind == "laser" and src is partsA:
            LASER[k] = p
        elif p.kind == "laser_stack" and (src is partsA or k == "lid_handle"):
            if k in ("cap_time",):
                continue        # same plies as cap_start, counted below
            mult = 2 if k == "cap_start" else 1
            tag = "_revA" if (k == "lid_handle" and src is partsA) else ("_revB" if src is partsB else "")
            for pn, loc, q in p.plies:
                for i in range(q * mult):
                    LASER[f"{k}{tag}_{pn}_{i+1}"] = _Ply(loc, p.material, t)


def profile_2d(p):
    """Closed 2D loops (outer first) at mid-thickness in the part's local frame, kerf-compensated."""
    loc = p.local
    sec = loc.intersect(cq.Solid.makeBox(2000, 2000, 0.02, cq.Vector(-1000, -1000, p.t / 2 - 0.01)))
    faces = [f for f in sec.Faces() if abs(f.normalAt().z) > 0.99 and abs(f.Center().z - (p.t / 2 + 0.01)) < 0.02]
    if not faces:
        faces = [f for f in sec.Faces() if abs(f.normalAt().z) > 0.99]
    f = max(faces, key=lambda x: x.Area())
    k2 = P["kerf_mm"] / 2
    loops = []
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    vs, tris = f.tessellate(0.01, 0.05)
    V = [(v.x, v.y) for v in vs]
    poly = unary_union([Polygon([V[i], V[j], V[k]]) for i, j, k in tris if
                        abs(Polygon([V[i], V[j], V[k]]).area) > 1e-9]).buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    poly = poly.simplify(0.005)
    assert poly.is_valid and abs(poly.area - f.Area()) < 0.002 * f.Area(), (poly.area, f.Area())
    outer = Polygon(poly.exterior.coords)
    outer_k = outer.buffer(k2, join_style=2)
    loops.append(("cut", list(outer_k.exterior.coords)))
    for ring in poly.interiors:
        hole = Polygon(ring.coords).buffer(-k2, join_style=2)
        if not hole.is_empty:
            loops.append(("cut", list(hole.exterior.coords)))
    return loops, outer.bounds


def nest(names, W, Hh, gap=3.0):
    """MaxRects packing with 90 deg rotation; returns a list of sheets, each name -> placement."""
    import rectpack
    pk = rectpack.newPacker(rotation=True, pack_algo=rectpack.MaxRectsBssf, sort_algo=rectpack.SORT_AREA)
    info = {}
    for n in names:
        loops, (x0, y0, x1, y1) = PROF[n]
        w, h = x1 - x0, y1 - y0
        info[n] = (w, h, x0, y0)
        pk.add_rect(int(round((w + gap) * 10)), int(round((h + gap) * 10)), rid=n)
    for _ in range(4):
        pk.add_bin(int((W - gap) * 10), int((Hh - gap) * 10))
    pk.pack()
    sheets = []
    for b in pk:
        place = {}
        for r in b:
            n = r.rid; w, h, x0, y0 = info[n]
            rot = abs(r.width / 10 - (w + gap)) > 0.05          # packer turned it
            place[n] = (r.x / 10 + gap, r.y / 10 + gap, rot, x0, y0, w)
        if place:
            sheets.append(place)
    assert sum(len(s) for s in sheets) == len(names), "parts left over"
    return sheets


PROF = {n: profile_2d(p) for n, p in LASER.items()}
mats = {"plywood": [n for n, p in LASER.items() if p.material == "plywood"],
        "acrylic_clear": [n for n, p in LASER.items() if p.material == "acrylic_clear"]}
W, Hh = P["sheet_w_mm"], P["sheet_h_mm"]
SHEETS = {}
import ezdxf


def xform_pts(pts, plc):
    x, y, rot, x0, y0, wx = plc
    out = []
    for (px, py) in pts:
        qx, qy = px - x0, py - y0
        if rot:                       # rotate -90 deg about the part's own bounds
            qx, qy = qy, wx - qx
        out.append((qx + x, qy + y))
    return out


cut_len = {}
for mat, names in mats.items():
  for si, plc in enumerate(nest(names, W, Hh)):
    names_s = list(plc)
    fname = f"sheet_{mat}_{t:.1f}mm" + (f"_{si + 1}" if si else "")
    doc = ezdxf.new("R2010"); doc.units = ezdxf.units.MM
    doc.layers.add("CUT", color=1); doc.layers.add("ENGRAVE", color=5); doc.layers.add("LABEL", color=3)
    msp = doc.modelspace()
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{Hh}mm" viewBox="0 0 {W} {Hh}">',
           f'<rect x="0" y="0" width="{W}" height="{Hh}" fill="none" stroke="#bbbbbb" stroke-width="0.2"/>',
           '<g id="ENGRAVE" fill="#000000" stroke="none">']
    cut_svg = ['<g id="CUT" fill="none" stroke="#ff0000" stroke-width="0.05">']
    total_cut = 0.0; total_eng = 0.0
    for n in names_s:
        loops, bounds = PROF[n]
        for kind, pts in loops:
            q = xform_pts(pts, plc[n])
            msp.add_lwpolyline(q, close=True, dxfattribs={"layer": "CUT"})
            cut_svg.append('<polygon points="' + " ".join(f"{a:.3f},{Hh - b:.3f}" for a, b in q) + '"/>')
            total_cut += sum(np.hypot(q[i][0] - q[i - 1][0], q[i][1] - q[i - 1][1]) for i in range(len(q)))
        for poly in LASER[n].engrave:
            q = xform_pts([tuple(v) for v in poly], plc[n])
            msp.add_lwpolyline(q, close=True, dxfattribs={"layer": "ENGRAVE"})
            from shapely.geometry import Polygon as _P
            total_eng += abs(_P(q).area)
            svg.append('<polygon points="' + " ".join(f"{a:.3f},{Hh - b:.3f}" for a, b in q) + '"/>')
    svg.append("</g>"); svg += cut_svg; svg.append("</g></svg>")
    doc.saveas(os.path.join(OUT, "laser", fname + ".dxf"))
    open(os.path.join(OUT, "laser", fname + ".svg"), "w").write("\n".join(svg))
    SHEETS[fname] = dict(file=fname, material=mat, parts=names_s, place=plc, cut_mm=total_cut, engrave_mm2=total_eng)

for n, p in LASER.items():
    cq.exporters.export(p.local, os.path.join(OUT, "stl", "laser_fallback", n + ".stl"), tolerance=0.05)
REPORT_LASER_COUNT = len(LASER)
for n in ("lid",):   # Rev B lid identical; handle differs only
    pass


# ----------------------------------------------------------------------------
# 4. checks
# ----------------------------------------------------------------------------
REPORT = {}
# printed parts: validity, bed fit
REPORT["print_parts"] = [dict(file=i["file"], valid=i["valid"], bbox=i["bbox"],
                              fits_bed=max(i["bbox"][0], i["bbox"][1]) <= P["print_bed_mm"]) for i in PRINT]
# laser parts: closed profile + fits the sheet
REPORT["laser_parts"] = []
for n, p in LASER.items():
    loops, (x0, y0, x1, y1) = PROF[n]
    REPORT["laser_parts"].append(dict(part=n, material=p.material, size=(round(x1 - x0, 1), round(y1 - y0, 1)),
                                      loops=len(loops), closed=all(np.allclose(l[1][0], l[1][-1]) for l in loops),
                                      valid=p.local.isValid()))

# interference (Rev A and Rev B, with electronics)
EXPECTED = set()   # nothing may share volume
REASON = {}
for tag, (pp, EE) in (("A", (partsA, EA)), ("B", (partsB, EB))):
    items = {k: v.solid for k, v in pp.items()}
    items.update({"E:" + k: v for k, v in EE.items()})
    ov = checks.overlaps(items, min_vol=1e-6)
    REPORT[f"overlaps_rev{tag}"] = [dict(a=a, b=b, mm3=v, expected=(a, b) in EXPECTED,
                                         why=REASON.get(a, "") if (a, b) in EXPECTED else "UNEXPECTED")
                                    for a, b, v in ov]

# only inserts differ between A and B
diff = []
for k in partsA:
    a, b = partsA[k].solid, partsB[k].solid
    if abs(a.Volume() - b.Volume()) > 1e-3 or (a.BoundingBox().center - b.BoundingBox().center).Length > 1e-3:
        diff.append(k)
REPORT["parts_changed_A_to_B"] = diff

# swing checks
w, g, o = checks.lid_sweep(P)
REPORT["lid_sweep"] = dict(collisions=[(a, h) for a, h in w if h], stop_gap_mm=round(g, 3),
                           overlap_if_pushed_2deg_mm3=round(o, 1), open_deg=P["lid_open_deg"])
w, g, o = checks.lid_sweep(PB)
REPORT["lid_sweep_revB"] = dict(collisions=[(a, h) for a, h in w if h], stop_gap_mm=round(g, 3))
r, g2 = checks.cover_sweep(P)
REPORT["cover_sweep"] = dict(collisions=[(a, h) for a, h in r if h], stop_gap_mm=round(g2, 3))

# clearances from the kernel
C = {}
C["cap_in_bezel_stop_revA"] = partsA["cap_stop"].solid.distance(partsA["bezel_stop"].solid)
for k in ("start", "time"):
    C[f"laser_cap_to_hole_{k}"] = partsA[f"cap_{k}"].solid.distance(partsA["control_face"].solid)
C["cap_in_bezel_stop_revB"] = partsB["cap_stop"].solid.distance(partsB["bezel_stop"].solid)
# tube in a good well: radial gap of the straight body
tube_rb = partsB["tube_1"].solid
band = tube_rb.intersect(ap.box(-200, 200, -200, 200, DB["flange_top"] - 14, DB["flange_top"] - 3))
C["tube_in_well_A_revB_radial"] = band.distance(partsB["well_insert_A"].solid)
C["tube_to_closed_lid_revB"] = partsB["tube_1"].solid.distance(partsB["lid"].solid)
C["tube_to_closed_lid_revA_stuck"] = partsA["tube_1"].solid.distance(partsA["lid"].solid)
C["tube_to_closed_lid_rack"] = partsA["tube_2"].solid.distance(partsA["rack_cover"].solid)
C["lid_tab_to_sensor_body"] = partsA["lid_sensor_fin"].solid.distance(EA["moc_lid"])
C["nub_to_sensor_body_revB"] = partsB["tube_1"].solid.distance(EB["moc_tube"])
tb = partsA["tube_1"].solid.BoundingBox()
nub_tip_A = partsA["tube_1"].solid.BoundingBox().zmin
nub_tip_B = partsB["tube_1"].solid.BoundingBox().zmin
C["nub_tip_z_revA_stuck"] = nub_tip_A
C["nub_tip_z_revB"] = nub_tip_B
C["tube_beam_z"] = DA["beam_z"]
C["tube_sensor_slot_top_z"] = DA["moc_tube_top"]
C["tube_rise_revA_vs_revB"] = nub_tip_A - nub_tip_B
C["lid_tab_bottom_z"] = partsA["lid_sensor_fin"].solid.BoundingBox().zmin
C["lid_beam_z"] = DA["lid_beam_z"]
C["moc_lead_gap_under_tube_sensor"] = DA["moc_tube_bot"] - t
# hook lip: nothing in the 10 mm under the lip
lf = P["lid_front_x_mm"]; zl = DB["lid_top"] + P["handle_clear_mm"]
probe = ap.box(lf, lf + P["handle_overhang_mm"], -12, 12, zl - P["handle_clear_mm"], zl - 0.01)
hits = [k for k, v in partsB.items() if k not in ("lid_handle",) and v.group == "centrifuge"
        and checks.bbox_overlap(v.solid, probe) and v.solid.intersect(probe).Volume() > 0.01]
C["hook_lip_clear_10mm_hits"] = hits
below = ap.box(lf, lf + P["handle_overhang_mm"], -12, 12, 0, zl - 0.01)
C["hook_lip_clear_under_mm"] = zl - max([v.solid.intersect(below).BoundingBox().zmax for k, v in partsB.items()
                                         if k != "lid_handle" and v.group == "centrifuge"
                                         and checks.bbox_overlap(v.solid, below)
                                         and v.solid.intersect(below).Volume() > 0.01] or [0])
REPORT["clearances_mm"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in C.items()}

# wall thickness from the meshes (ray casting inward)
import trimesh
WALL = {}
for it in PRINT:
    m = trimesh.load(it["path"])
    pts, fi = trimesh.sample.sample_surface_even(m, 2500, seed=1)
    n = m.face_normals[fi]
    origins = pts - n * 1e-3
    locs, idx_ray, idx_tri = m.ray.intersects_location(origins, -n, multiple_hits=False)
    th = np.full(len(pts), np.inf)
    for L, ir, itr in zip(locs, idx_ray, idx_tri):
        d = np.linalg.norm(L - origins[ir])
        if np.dot(m.face_normals[itr], -n[ir]) > 0.95:   # hit a roughly parallel opposite wall
            th[ir] = min(th[ir], d)
    good = th[np.isfinite(th)]
    WALL[it["file"]] = round(float(np.percentile(good, 1)), 2) if len(good) else None
REPORT["wall_1st_percentile_mm"] = WALL

# electronics fit inside the body (bounding check against the panels' inner volume)
REPORT["electronics_overlaps"] = [r for r in REPORT["overlaps_revA"] if r["a"].startswith("E:") or r["b"].startswith("E:")]

# parameter rebuild check: sheet thickness and kerf
RB = []
for st in (2.7, 3.2):
    for kf in (0.1, 0.2):
        Pq = ap.apply_patch(P, {"sheet_t_mm": st, "kerf_mm": kf})
        try:
            pq, eq, dq = ap.build(Pq)
            ok = all(v.solid.isValid() for v in pq.values())
            items = {k: v.solid for k, v in pq.items() if v.kind == "laser"}
            ov = [x for x in checks.overlaps(items)]
            RB.append(dict(sheet_t=st, kerf=kf, valid=ok, laser_overlaps=ov, body_h=dq["H"], flange_top=round(dq["flange_top"], 2)))
        except Exception as e:
            RB.append(dict(sheet_t=st, kerf=kf, error=str(e)[:200]))
REPORT["rebuild_sheet_kerf"] = RB


# ----------------------------------------------------------------------------
# 5. features.json + reach
# ----------------------------------------------------------------------------
def unit(v):
    v = np.asarray(v, float); return v / np.linalg.norm(v)


def feats(Pp, Dd, pp, rev):
    F = []
    Ms = Dd["Ms"]; L = Dd["slope_L"]; yc = L / 2; cy = Pp["ctrl_y_mm"]
    n = ap.vec(Ms, (0, 0, 1)); es = ap.vec(Ms, (0, 1, 0))
    def face_point(ylat, out):
        return ap.pt(Ms, (ylat, yc, t + out))
    top = Pp["bezel_flange_t_mm"] + Pp["cap_proud_mm"]
    tact_travel = "0.25 mm switch travel (12 mm tactile); brief asks 1-3 mm, see notes"
    F.append(dict(id="power_toggle", kind="control", skill="flip", serial="power",
                  contact_point=face_point(cy["power"], 6.0 + 7.0) - es * 1.5, approach=-n,
                  push_on=es, push_off=-es, angle_range_deg=[-15, 15], expected_force_N=3.0,
                  note="push the lever toward the top edge (+s) for ON, toward the bottom edge for OFF; contact 7 mm up the lever"))
    for k, ev in (("start", "btn_start"), ("stop", "btn_stop"), ("time", "btn_time")):
        F.append(dict(id=f"button_{k}", kind="control", skill="press", serial=ev,
                      contact_point=face_point(cy[k], top if k == "stop" else Dd["laser_cap_top"]), approach=-n, travel_mm=[0.2, 0.5],
                      travel_note=tact_travel, expected_force_N=2.5, force_cap_N=5.0,
                      cap_d_mm=Pp["cap_d_mm"],
                      bezel_clearance_mm=Pp["bezel_clearance_mm"]["stop"] if k == "stop" else None))
    kz = Pp["pot_bushing_above_mm"] + 1.0 + Pp["knob_fin_height_mm"] / 2   # mid-fin
    ctr = face_point(cy["speed"], kz)
    sw = Pp["dial_sweep_deg"]; rr = 6.5
    a0 = -sw / 2
    ex = ap.vec(Ms, (1, 0, 0))
    def on_arc(a):
        a = math.radians(a); return ctr + rr * (math.sin(a) * ex + math.cos(a) * es)
    def tang(a):
        a = math.radians(a); return unit(math.cos(a) * ex - math.sin(a) * es)   # clockwise seen from outside
    F.append(dict(id="speed_dial", kind="control", skill="turn", serial="speed",
                  contact_point=on_arc(a0) - tang(a0) * Pp["knob_fin_t_mm"] / 2, approach=-n,
                  push_dir_at_start=tang(a0), arc_center=ctr, arc_axis=n, arc_radius_mm=rr,
                  angle_range_deg=[a0, sw / 2], angle_ref="0 = fin toward the top edge; positive = clockwise seen from outside",
                  rpm_range=[1000, 6000], expected_force_N=2.0,
                  note="fin starts at the 1000 rpm stop; push on the fin face at 6.5 mm radius"))
    # lid
    lf = Pp["lid_front_x_mm"]; ax, az = Dd["axis"]
    if Pp["handle_type"] == "hook_lip":
        e = np.array([lf + Pp["handle_overhang_mm"] - 4.0, 0.0, Dd["lid_top"] + Pp["handle_clear_mm"]])
        dx, dz = e[0] - ax, e[2] - az
        F.append(dict(id="lid_lip", kind="door", skill="hook_pull", serial="lid",
                      contact_point=e, approach=np.array([-1.0, 0, 0]), pull_dir=unit([-dz, 0, dx]),
                      hinge_axis_point=np.array([ax, 0, az]), hinge_axis_dir=np.array([0, 1.0, 0]),
                      angle_range_deg=[0, Pp["lid_open_deg"]], expected_force_N=1.5,
                      lip_overhang_mm=Pp["handle_overhang_mm"], clear_under_lip_mm=Pp["handle_clear_mm"],
                      note="slide the hook under the lip from the front, then lift along the arc; lid rests on its stop at 105 deg"))
    else:
        e = np.array([lf - 7.0, 0.0, Dd["lid_top"] + 3.0 + 6.0])
        F.append(dict(id="lid_lip", kind="door", skill=None, serial="lid", contact_point=e,
                      approach=np.array([-1.0, 0, 0]), angle_range_deg=[0, Pp["lid_open_deg"]],
                      note="F2: thin upright pinch tab only; no allowed skill (press, push_latch, hook_pull, flip, turn) can open it"))
    # wells
    for k in ("A", "B"):
        wx, wy = Dd["wells"][k]
        z_ok = Dd["flange_top"] + Dd["origin_ok"] if k == "A" else Dd["well_B_origin"]
        F.append(dict(id=f"well_{k}", kind="well", skill="place", serial=("tube" if k == "A" else None),
                      contact_point=np.array([wx, wy, z_ok - Pp["collar_h_mm"] / 2]), approach=np.array([0, 0, -1.0]),
                      pre_place_point=np.array([wx, wy, z_ok - Pp["collar_h_mm"] / 2 + 15]),
                      well_id_mm=Pp["well_id_mm"][k], expected_force_N=2.0,
                      note="contact_point = collar centre when seated; grip the collar flats"))
    Mr = Dd["Mrack"]; uv = ap.vec(Mr, (0, 1, 0))
    for i, u in enumerate(Dd["rack_u"]):
        z = Dd["rack_flange_top"] + Dd["origin_hole"] - Pp["collar_h_mm"] / 2
        F.append(dict(id=f"rack_well_{i+1}", kind="well", skill="pick", serial=None,
                      contact_point=ap.pt(Mr, (u, 0, z)), approach=np.array([0, 0, -1.0]),
                      jaw_axis=uv, note="jaws close along the rack depth (toward/away from the arm)"))
    # rack cover lip
    av, az2 = Dd["rack_axis"]; ct = Dd["rack_cover_z"] + t
    vf = Dd["rack_cover_front_v"]
    e_l = (0, vf + Pp["handle_overhang_mm"] - 4.0, ct)
    dv, dz = e_l[1] - av, e_l[2] - az2
    F.append(dict(id="rack_cover_lip", kind="door", skill="hook_pull", serial=None,
                  contact_point=ap.pt(Mr, e_l), approach=-uv, pull_dir=unit(-dz * uv + np.array([0, 0, dv])),
                  hinge_axis_point=ap.pt(Mr, (0, av, az2)), hinge_axis_dir=ap.vec(Mr, (1, 0, 0)),
                  angle_range_deg=[0, Pp["lid_open_deg"]], expected_force_N=1.0))
    # locating features
    sh = Dd["slope_half"]
    for sgn, nm in ((-1, "locate_face_corner_L"), (1, "locate_face_corner_R")):
        q = ap.pt(Ms, (sgn * sh, L, t))
        F.append(dict(id=nm, kind="locate", skill="touch", serial=None, contact_point=q, approach=-n,
                      touch_normals=[n, es, np.array([0, sgn * 1.0, 0])],
                      note="outside top corner of the control face plate (outer face / top edge / side edge)"))
    hin = Dd["rack_in"] / 2
    q = ap.pt(Mr, (-hin, Pp["rack_top_front_mm"], Dd["rack_flange_top"]))
    F.append(dict(id="locate_rack_corner", kind="locate", skill="touch", serial=None, contact_point=q,
                  approach=np.array([0, 0, -1.0]), touch_normals=[np.array([0, 0, 1.0]), uv, -ap.vec(Mr, (1, 0, 0))],
                  note="front outside corner of the rack top plate (top face / front edge / end edge)"))
    # observe-only
    F.append(dict(id="display", kind="observe", skill=None, serial=None,
                  contact_point=np.array([Dd["xf"], 0, Pp["oled_center_z_mm"]]), approach=np.array([-1.0, 0, 0]),
                  note="OLED window; camera only"))
    bx, by = Dd["bowl"]
    F.append(dict(id="light_ring", kind="observe", skill=None, serial=None,
                  contact_point=np.array([bx, by, Dd["ring_top"]]), approach=np.array([0, 0, -1.0]),
                  note="seen through the clear lid and rotor plate"))
    return F


ZONES = {"down": dict(r=(140, 300), h=(-50, 50)), "45": dict(r=(220, 340), h=(-50, 150))}
SKILL_ZONE = {"press": "45", "flip": "45", "turn": "45", "hook_pull": "45", "place": "down", "pick": "down",
              None: None}


def zone_for(f):
    if f["kind"] == "locate":
        return "down" if "rack" in f["id"] else "45"
    if f["kind"] == "observe":
        return None
    if f["id"] == "lid_lip" and f["skill"] is None:
        return "45"
    return SKILL_ZONE[f["skill"]]


def arm_coords(p, px, riser):
    dx, dy = p[0] - px, p[1]
    r = math.hypot(dx, dy); h = p[2] - riser
    pan = math.degrees(math.atan2(dy, -dx))     # 0 = straight at the centrifuge, + toward product +Y
    return r, h, pan


def margins(F, px, riser, heights_only=False):
    out = []
    for f in F:
        z = zone_for(f)
        if not z:
            continue
        r, h, pan = arm_coords(f["contact_point"], px, riser)
        Z = ZONES[z]
        if heights_only:
            out.append(min(h - Z["h"][0], Z["h"][1] - h))
        else:
            out.append(min(r - Z["r"][0], Z["r"][1] - r, h - Z["h"][0], Z["h"][1] - h))
    return min(out)


FA = feats(P, DA, partsA, "A"); FB = feats(PB, DB, partsB, "B")
best = None
for px in np.arange(240, 300.5, 0.5):
    for rs in np.arange(20, 110.5, 0.5):
        m = (round(min(margins(FA, px, rs), margins(FB, px, rs)), 1),
             min(margins(FA, px, rs, True), margins(FB, px, rs, True)))
        if best is None or m > best[0]:
            best = (m, px, rs)
REACH = dict(best_min_margin_mm=best[0][0], best_height_margin_mm=round(best[0][1], 1),
             pan_axis_x_mm=float(best[1]), riser_height=float(best[2]))
# use the parameters (kept in sync with the optimum below)
PX, RS = P["pan_axis_x_mm"], P["riser_height"]
REACH["used"] = dict(pan_axis_x_mm=PX, riser_height=RS, min_margin_mm=round(min(margins(FA, PX, RS), margins(FB, PX, RS)), 1))


def jsonable(F, px, riser):
    out = []
    for f in F:
        g = {}
        for k, v in f.items():
            if isinstance(v, np.ndarray):
                g[k] = [round(float(x), 2) for x in v]
            elif isinstance(v, list) and v and isinstance(v[0], np.ndarray):
                g[k] = [[round(float(x), 3) for x in u] for u in v]
            elif isinstance(v, float):
                g[k] = round(v, 3)
            else:
                g[k] = v
        z = zone_for(f)
        r, h, pan = arm_coords(f["contact_point"], px, riser)
        g["arm"] = dict(distance_mm=round(r, 1), height_mm=round(h, 1), pan_deg=round(pan, 1), zone=z)
        if z:
            Z = ZONES[z]
            g["arm"]["in_zone"] = bool(Z["r"][0] <= r <= Z["r"][1] and Z["h"][0] <= h <= Z["h"][1])
            g["arm"]["margin_mm"] = round(min(r - Z["r"][0], Z["r"][1] - r, h - Z["h"][0], Z["h"][1] - h), 1)
        out.append(g)
    return out


FEAT = dict(
    frame=dict(product="origin at the centre of the centrifuge base bottom face; +X toward the arm; +Z up; mm",
               arm=f"origin on the pan axis at riser height: product ({PX}, 0, {RS}). distance = horizontal from the "
                   "pan axis; height = above the arm base; pan_deg 0 = straight at the centrifuge, positive toward "
                   "product +Y (the arm's right, clockwise seen from above)"),
    pan_axis_product=[PX, 0, RS], riser_height=RS,
    reach_zones=dict(down="straight-down press / pick-and-place: 140-300 mm, height -50..+50",
                     d45="45 deg press: 220-340 mm, height -50..+150",
                     note="hook_pull checked against the 45 deg zone; it was not in the Oct 31 reach test"),
    rev_A=jsonable(FA, PX, RS), rev_B=jsonable(FB, PX, RS))
json.dump(FEAT, open(os.path.join(OUT, "features.json"), "w"), indent=1)
REPORT["reach"] = REACH
REPORT["reach_out_of_zone"] = [(rv, f["id"]) for rv in ("rev_A", "rev_B") for f in FEAT[rv]
                               if f["arm"].get("in_zone") is False]

# ----------------------------------------------------------------------------
# 6. patch file, build table, misc
# ----------------------------------------------------------------------------
patch = {"rev": "B", "from": "A",
         "params": {"bezel_clearance_mm": {"stop": {"from": P["bezel_clearance_mm"]["stop"], "to": 0.40}},
                    "handle_type": {"from": P["handle_type"], "to": "hook_lip"},
                    "handle_overhang_mm": P["handle_overhang_mm"], "handle_clear_mm": P["handle_clear_mm"],
                    "well_id_mm": {"A": {"from": P["well_id_mm"]["A"], "to": 16.8}}},
         "reprint": ["stl/print_revB/bezel_stop_revB.stl", "stl/print_revB/well_insert_A_revB.stl"],
         "laser_recut": ["lid_handle_revB_ply_1..3 (3-ply laminate, on the plywood sheet)"],
         "laser_parts_changed": [],
         "fixes": {"F1": "Stop bezel bore to 0.40 mm per side", "F2": "pinch-tab laminate -> hook-lip laminate (laser)",
                   "F3": "well A ID to tube OD + 0.8"}}
yaml.safe_dump(patch, open(os.path.join(OUT, "patch_revB.yaml"), "w"), sort_keys=False)
shutil.copy("appliance.py", os.path.join(OUT, "appliance.py"))

PLY_SPEED, ACR_SPEED = 15.0, 10.0   # mm/s, estimates for 3 mm stock on a 40-60 W CO2 laser
rows = []
for fname_, sh in SHEETS.items():
    mat = sh["material"]
    for n in sh["parts"]:
        loops, (x0, y0, x1, y1) = PROF[n]
        L_ = sum(sum(np.hypot(np.diff(np.array(l)[:, 0]), np.diff(np.array(l)[:, 1]))) for _, l in loops)
        sp = PLY_SPEED if mat == "plywood" else ACR_SPEED
        eng = sum(abs(__import__("shapely").geometry.Polygon(e).area) for e in LASER[n].engrave)
        tmin = L_ / sp / 60 + eng / 400.0 / 60      # engrave estimate: ~400 mm^2/s raster
        rows.append(dict(part=n, method="laser", material=f"{mat} {t:.1f} mm", qty=1,
                         size=f"{x1 - x0:.0f} x {y1 - y0:.0f}", time_min=round(tmin, 1), grams=None,
                         cut_mm=round(L_), rev="A+B"))
for it in PRINT:
    rows.append(dict(part=it["file"], method="print", material="PLA", qty=it["qty"],
                     size=" x ".join(str(v) for v in it["bbox"]),
                     time_min=round((it["sec"] or 0) * it["qty"] / 60, 1), grams=round((it["g"] or 0) * it["qty"], 1),
                     cut_mm=None, rev=it["rev"], what=it["what"]))
json.dump(dict(rows=rows, plates=PLATE_RES, sheets={k: dict(file=v["file"], parts=v["parts"]) for k, v in SHEETS.items()}),
          open(os.path.join(OUT, "build_table.json"), "w"), indent=1)
json.dump(REPORT, open(os.path.join(OUT, "check_report.json"), "w"), indent=1, default=str)
json.dump(dict(DA={k: (v if isinstance(v, (int, float)) else None) for k, v in DA.items()}),
          open(os.path.join(OUT, "derived.json"), "w"), indent=1, default=str)
print("done")
