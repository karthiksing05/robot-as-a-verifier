"""The MC-6 centrifuge and its rack, as build.py wants them: one assembly per revision, product frame, mm.

appliance.py is the design's CadQuery source, unchanged from the CAD package (centrifuge_cad_v6). Part names follow
its Onshape export: a fault part is suffixed _revA or _revB, and the electronics are ref_* placeholders.
"""
import cadquery as cq

import appliance as ap

# Rev B's patch (the CAD package's patch_revB.yaml, as its Onshape export applied it)
PATCH_B = {"bezel_clearance_mm": {"stop": 0.40}, "handle_type": "hook_lip", "well_id_mm": {"A": 16.8}}
FAULT_PARTS = {"bezel_stop", "well_insert_A", "lid_handle"}
COLOURS = {"plywood": (0.83, 0.68, 0.47, 1), "acrylic_clear": (0.70, 0.85, 0.95, 0.4), "PLA": (0.92, 0.92, 0.90, 1), "filament": (0.3, 0.3, 0.3, 1)}
REV_COLOUR = {"A": (0.95, 0.50, 0.10, 1), "B": (0.20, 0.70, 0.35, 1)}
ELECTRONICS = (0.2, 0.45, 0.25, 1)

# parts whose holes, hooks or lips matter: MuJoCo collides a mesh as its hull, so these are split into convex pieces
CONCAVE = ["dial_knob", "lid_handle_revA", "lid_handle_revB", "lid_hinge_leaf", "rack_cover_lip", "rack_hinge_leaf", "rack_middle", "rack_top",
           "rotor_plate", "top_panel", "tube_1", "tube_2", "well_insert_A_revA", "well_insert_A_revB"]


def _assembly(rev, parts, electronics):
    a = cq.Assembly(name=f"mc6_rev{rev}")
    for k, p in parts.items():
        colour = REV_COLOUR[rev] if k in FAULT_PARTS else COLOURS.get(p.material, (0.8, 0.8, 0.8, 1))
        a.add(p.solid, name=f"{k}_rev{rev}" if k in FAULT_PARTS else k, color=cq.Color(*colour))
    sub = cq.Assembly(name="electronics_reference")
    for k, s in electronics.items():
        sub.add(s, name="ref_" + k, color=cq.Color(*ELECTRONICS))
    a.add(sub)
    return a


def assemblies():
    pa, ea, _ = ap.build(ap.PARAMS)
    pb, eb, _ = ap.build(ap.apply_patch(ap.PARAMS, PATCH_B))
    return {"A": _assembly("A", pa, ea), "B": _assembly("B", pb, eb)}
