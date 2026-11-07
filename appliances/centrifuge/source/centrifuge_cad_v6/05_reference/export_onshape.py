"""Export an Onshape-ready folder: STEP assemblies, STEP part studios, single-part STEPs, nominal DXF sketches."""
import os, csv, json, shutil
import numpy as np
import cadquery as cq
import ezdxf
import appliance as ap

OUT = os.path.abspath("onshape_import")
shutil.rmtree(OUT, ignore_errors=True)
for d in ("01_assemblies", "02_part_studios", "03_parts/laser_flat", "03_parts/printed_revA_revB",
          "03_parts/printed_in_place", "04_laser_sketches_dxf", "05_reference"):
    os.makedirs(os.path.join(OUT, d), exist_ok=True)

P = ap.PARAMS
PB = ap.apply_patch(P, {"bezel_clearance_mm": {"stop": 0.40}, "handle_type": "hook_lip", "well_id_mm": {"A": 16.8}})
pA, EA, DA = ap.build(P)
pB, EB, DB = ap.build(PB)

COL = {"plywood": (0.83, 0.68, 0.47, 1), "acrylic_clear": (0.70, 0.85, 0.95, 0.4), "PLA": (0.92, 0.92, 0.90, 1)}
REVA = (0.95, 0.50, 0.10, 1); REVB = (0.20, 0.70, 0.35, 1)
FAULT_PARTS = {"bezel_stop", "well_insert_A", "lid_handle"}
COL["filament"] = (0.3, 0.3, 0.3, 1)
ECOL = (0.2, 0.45, 0.25, 1)


def color(k, p, rev="A"):
    c = (REVA if rev == "A" else REVB) if k in FAULT_PARTS else COL.get(p.material, (0.8, 0.8, 0.8, 1))
    return cq.Color(*c)


def assembly(name, items, elec=None, rev="A"):
    a = cq.Assembly(name=name)
    for k, p in items:
        nm = f"{k}_rev{rev}" if k in FAULT_PARTS else k
        a.add(p.solid, name=nm, color=color(k, p, rev))
    if elec:
        sub = cq.Assembly(name="electronics_reference")
        for k, s in elec.items():
            sub.add(s, name="ref_" + k, color=cq.Color(*ECOL))
        a.add(sub)
    return a


def save(a, path):
    a.save(path, exportType="STEP")


centA = [(k, p) for k, p in pA.items() if p.group == "centrifuge"]
centB = [(k, p) for k, p in pB.items() if p.group == "centrifuge"]
rack = [(k, p) for k, p in pA.items() if p.group == "rack"]

# 1. assemblies (product frame: +X toward the arm, +Z up, mm)
save(assembly("centrifuge_revA", centA, EA), f"{OUT}/01_assemblies/centrifuge_revA.step")
save(assembly("centrifuge_revB", centB, EB, rev="B"), f"{OUT}/01_assemblies/centrifuge_revB.step")
save(assembly("tube_rack", rack), f"{OUT}/01_assemblies/tube_rack.step")
save(assembly("full_rig_revA", [(k, p) for k, p in pA.items()], EA), f"{OUT}/01_assemblies/full_rig_revA.step")
save(assembly("full_rig_revB", [(k, p) for k, p in pB.items()], EB, rev="B"), f"{OUT}/01_assemblies/full_rig_revB.step")

# 2. part studios (flat, multi-part, in place)
def studio(name, items, rev="A"):
    a = cq.Assembly(name=name)
    for k, p in items:
        nm = f"{k}_rev{rev}" if k in FAULT_PARTS else k
        a.add(p.solid, name=nm, color=color(k, p, rev))
    save(a, f"{OUT}/02_part_studios/{name}.step")

studio("PS1_centrifuge_laser_body", [(k, p) for k, p in centA if p.kind == "laser"])
COL["plywood"] = COL.get("plywood")
studio("PS2_centrifuge_fixed_parts", [(k, p) for k, p in centA if p.kind in ("print", "stock", "laser_stack") and k not in FAULT_PARTS])
studio("PS3a_fault_inserts_revA", [(k, pA[k]) for k in ("bezel_stop", "well_insert_A", "lid_handle")], rev="A")
studio("PS3b_fixed_inserts_revB", [(k, pB[k]) for k in ("bezel_stop", "well_insert_A", "lid_handle")], rev="B")
studio("PS4_rack_laser", [(k, p) for k, p in rack if p.kind == "laser"])
studio("PS5_rack_hinge_and_tube", [(k, p) for k, p in rack if p.kind in ("print", "stock", "laser_stack")])
ea = cq.Assembly(name="PS6_electronics_reference")
for k, s in EA.items():
    ea.add(s, name="ref_" + k, color=cq.Color(*ECOL))
save(ea, f"{OUT}/02_part_studios/PS6_electronics_reference.step")

# 3. single parts
rows = []
for k, p in pA.items():
    if p.kind == "laser":
        cq.exporters.export(p.local, f"{OUT}/03_parts/laser_flat/{k}.step")
        rows.append((k, "laser", p.material, "03_parts/laser_flat", "flat on XY, outer face up"))
    elif p.kind != "laser":
        cq.exporters.export(p.solid, f"{OUT}/03_parts/printed_in_place/{k}{'_revA' if k in FAULT_PARTS else ''}.step")
for k in FAULT_PARTS:
    cq.exporters.export(pB[k].solid, f"{OUT}/03_parts/printed_in_place/{k}_revB.step")
PA15 = ap.apply_patch(P, {"bezel_clearance_mm": {"stop": P["stop_variants_mm"][1]}})
p15, _, _ = ap.build(PA15)
singles = {"bezel_stop_revA_F1_0.05": pA["bezel_stop"], "bezel_stop_revA_F1_0.15": p15["bezel_stop"],
           "bezel_stop_revB": pB["bezel_stop"], "cap_stop": pA["cap_stop"],
           "well_insert_A_revA_F3": pA["well_insert_A"], "well_insert_A_revB": pB["well_insert_A"],
           "hinge_base": pA["lid_hinge_base"], "hinge_leaf": pA["lid_hinge_leaf"], "test_tube": pA["tube_1"]}
for k, p in singles.items():
    cq.exporters.export(p.local, f"{OUT}/03_parts/printed_revA_revB/{k}.step")
    rows.append((k, "print", "PLA", "03_parts/printed_revA_revB", "own local frame"))
# laser ply stacks (caps, knob, handles): each ply flat
for src, tag in ((pA, ""), (pB, "_revB")):
    for k, p in src.items():
        if p.kind != "laser_stack" or (tag and k != "lid_handle"):
            continue
        nm = k + ("_revA" if (k == "lid_handle" and not tag) else tag)
        for pn, loc, q in p.plies:
            cq.exporters.export(loc, f"{OUT}/03_parts/laser_flat/{nm}_{pn}__x{q}.step")
            rows.append((f"{nm}_{pn}", "laser", p.material, "03_parts/laser_flat", f"flat, cut {q}"))

# 4. nominal DXF sketches (no kerf), real arcs, cut + engrave layers
for k, p in pA.items():
    if p.kind != "laser":
        continue
    sec = p.local.intersect(cq.Solid.makeBox(4000, 4000, 0.02, cq.Vector(-2000, -2000, p.t / 2 - 0.01)))
    f = max([f for f in sec.Faces() if abs(f.normalAt().z) > 0.99], key=lambda x: x.Area())
    path = f"{OUT}/04_laser_sketches_dxf/{k}.dxf"
    cq.exporters.export(cq.Workplane("XY").add(f), path, "DXF")
    doc = ezdxf.readfile(path)
    for e in doc.modelspace():
        e.dxf.layer = "CUT"
    doc.layers.add("CUT", color=1); doc.layers.add("ENGRAVE", color=5)
    for poly in p.engrave:
        doc.modelspace().add_lwpolyline([tuple(v) for v in poly], close=True, dxfattribs={"layer": "ENGRAVE"})
    doc.units = ezdxf.units.MM
    doc.saveas(path)

for src, tag in ((pA, ""), (pB, "_revB")):
    for k, p in src.items():
        if p.kind != "laser_stack" or (tag and k != "lid_handle"):
            continue
        nm = k + ("_revA" if (k == "lid_handle" and not tag) else tag)
        for pn, loc, q in p.plies:
            sec = loc.intersect(cq.Solid.makeBox(4000, 4000, 0.02, cq.Vector(-2000, -2000, P["sheet_t_mm"] / 2 - 0.01)))
            f = max([f for f in sec.Faces() if abs(f.normalAt().z) > 0.99], key=lambda x: x.Area())
            path = f"{OUT}/04_laser_sketches_dxf/{nm}_{pn}__x{q}.dxf"
            cq.exporters.export(cq.Workplane("XY").add(f), path, "DXF")

# 5. reference
with open(f"{OUT}/05_reference/PARAMS.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["name", "value", "note"])
    for k, v in P.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                w.writerow([f"{k}.{kk}", vv, ""])
        elif isinstance(v, list):
            w.writerow([k, " ".join(str(x) for x in v), ""])
        else:
            w.writerow([k, v, ""])
with open(f"{OUT}/05_reference/part_list.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["part", "method", "material", "folder", "orientation"]); w.writerows(rows)
for f in ("features.json", "patch_revB.yaml", "wiring.md", "manual.md", "build_table.md", "feasibility.json", "check_report.json"):
    src = os.path.join("out", f)
    if os.path.exists(src):
        shutil.copy(src, f"{OUT}/05_reference/{f}")
shutil.copy("appliance.py", f"{OUT}/05_reference/appliance.py")
print("ok")
