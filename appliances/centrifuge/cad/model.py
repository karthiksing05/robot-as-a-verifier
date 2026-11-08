"""The MC-6 centrifuge and its MC-R4 rack (v7), as build.py wants them: one assembly per revision, product frame, mm.

The design's source is Karthik's STEP export (source/step/mc6_rev{A,B}.step, one named solid per part, already in the
product frame; source/README.md). This only re-packs it, with three changes for the sim:

- tube_1_revA / tube_1_revB are left out. They show where a tube ends up in well A (source/faults.md), not where it
  starts. The sim starts both tubes in the rack: tube 1 in position 2, where the CAD has tube_2, and the second tube in
  position 4, `tube_2_pos4`, tube_2 moved along the rack's row (a pure translation, so its flats face the same way).
  Not position 1 or 3: beside a tube (24 mm pitch, 18 mm collars) the stock gripper's jaws can't get down to either
  tube. Not seated in well B either: 26 mm from well A, it stops the jaws placing a tube there.
- ref_toggle_lever is left out of the meshes' use (device.yaml draws the lever as a capsule): the STEP poses it ON
  (15 deg toward the top edge), and the loader puts a body's q = 0 where its mesh is, where motion.md puts OFF.
- The bought panel-button housings have no colour in the STEP; they get a dark grey.

Part names are the STEP's: a fault part is suffixed _revA or _revB, and bought electronics are ref_* placeholders.
"""
import pathlib

import cadquery as cq

STEP = pathlib.Path(__file__).resolve().parents[1] / "source" / "step"
SKIP = {"tube_1_revA", "tube_1_revB"}
GREY = (0.25, 0.25, 0.27, 1)
RACK_2, RACK_4 = (84.57, 175.03, 58.0), (53.72, 138.26, 58.0)   # collar points in rack positions 2 and 4, product frame

# parts whose holes, hooks or lips matter: MuJoCo collides a mesh as its hull, so these are split into convex pieces
CONCAVE = ["lid_handle_revA", "lid_handle_revB", "lid_hinge_leaf", "rack_cover_lip", "rack_hinge_leaf", "rack_middle", "rack_top",
           "rotor_plate", "top_panel", "well_insert_A_revA", "well_insert_A_revB"]


def _leaves(assy):
    for child in assy.children:
        if child.children:
            yield from _leaves(child)
        elif child.obj is not None:
            yield child


def _assembly(rev):
    src = cq.Assembly.importStep(str(STEP / f"mc6_rev{rev}.step"))
    out = cq.Assembly(name=f"mc6_rev{rev}")
    for leaf in _leaves(src):
        name = leaf.name.split("/")[-1].strip().replace(" ", "_")
        if name in SKIP:
            continue
        shape = leaf.obj.val() if isinstance(leaf.obj, cq.Workplane) else leaf.obj
        shape = shape.moved(src.loc * leaf.loc) if leaf.loc is not None else shape
        colour = leaf.color.toTuple() if leaf.color else GREY
        out.add(shape, name=name, color=cq.Color(*colour))
        if name == "tube_2":
            out.add(shape.translate(cq.Vector(*(b - a for a, b in zip(RACK_2, RACK_4)))), name="tube_2_pos4", color=cq.Color(*colour))
    return out


def assemblies():
    return {"A": _assembly("A"), "B": _assembly("B")}
