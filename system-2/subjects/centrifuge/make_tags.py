"""Write the centrifuge's tag file (onshape.yaml) from the Rev A model and the public brief only.

    cd system-2 && .venv/bin/python subjects/centrifuge/make_tags.py               # exports Rev A from Onshape
    .venv/bin/python subjects/centrifuge/make_tags.py --step revA.step             # or from a saved export
    .venv/bin/python subjects/centrifuge/make_tags.py --create-version             # also make the tested version

Nothing here reads Rev B or the fault table. Positions the brief doesn't give are measured from Rev A's parts.
Assumptions, fixed before any run:
- the robot presses and hooks with its 12 mm round fingertip (no other tool);
- sliding fits need 0.3 mm per side; the press force limit is the harness's;
- the tube sensor's beam is 3 mm below the top of the MOC7811 (typical for the part; measure to confirm), and the
  tube is seated when its nub reaches the beam (brief: the nub passes through the tube sensor's beam);
- the hook skims the lid: the fingertip's lowest point 1 mm above the lid, sliding toward the hinge until it
  touches, then lifting.
--create-version makes a permanent Onshape version of the document's current state, named "Rev A (tested)", and
writes its id into the tag file: the analyst's branches are made from it.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import tempfile

import cadquery as cq
import yaml

from rav_cad.generic import load_step
from rav_cad.generic.tags import Tags
from rav_cad.onshape.client import DocRef, OnshapeClient, parse_document_url
from rav_cad.onshape.settings import load_settings

HERE = pathlib.Path(__file__).resolve().parent
ASSEMBLY, PART_STUDIO = "5bab0e7f50c9ff71e448f5f0", "6675bf254e69f8145767c98f"   # full_rig_revA, full_rig_revA parts
IGNORE = ["_revA", "_revB"]
FINGERTIP_D, MIN_CLEARANCE = 12.0, 0.3
BEAM_BELOW_SENSOR_TOP, HOOK_ABOVE_LID = 3.0, 1.0
FACE_NORMAL = cq.Vector(math.sqrt(0.5), 0, math.sqrt(0.5))     # the 45 degree control face, toward the arm and up
r = lambda v: [round(float(c), 3) for c in v]                   # noqa: E731


def outer_point(shape):
    """Centre of a part's outward end along the control face's normal: where the fingertip touches it."""
    c = shape.Center()
    lead = max(cq.Vector(*v.toTuple()).dot(FACE_NORMAL) for v in shape.Vertices())
    return c + FACE_NORMAL * (lead - c.dot(FACE_NORMAL))


def build(parts: dict, document: str, version: str | None) -> dict:
    n = FACE_NORMAL

    def button(name):
        return {"skill": "press", "parts": [f"bezel_{name}", f"cap_{name}"], "moving": [f"cap_{name}"],
                "motion": {"type": "slide", "axis": r(-n), "travel": 0.25},          # the switch's own travel
                "contact": r(outer_point(parts[f"cap_{name}"])), "approach": r(-n),
                "fit": [f"cap_{name}", f"bezel_{name}"], "actuates": [f"ref_switch_{name}"]}

    # the lid swings about its hinge pin (axis along Y); take the sign that lifts the front edge
    pin, lid = parts["lid_hinge_pin"].Center(), parts["lid"]
    axis = next(s for s in (1, -1) if lid.rotate(cq.Vector(pin.x, 0, pin.z), cq.Vector(pin.x, s, pin.z), 10)
                .BoundingBox().zmax > lid.BoundingBox().zmax)
    handle, lid_top = parts["lid_handle"].BoundingBox(), lid.BoundingBox().zmax
    hook_start = (handle.xmax + 40, (handle.ymin + handle.ymax) / 2, lid_top + HOOK_ABOVE_LID + FINGERTIP_D / 2)

    # tube 1 into well A: down until its nub reaches the tube sensor's beam
    beam_z = parts["ref_moc_tube"].BoundingBox().zmax - BEAM_BELOW_SENSOR_TOP
    well = parts["well_insert_A"].Center()

    return {
        "source": {"document": document, "assembly": ASSEMBLY, "part_studio": PART_STUDIO,
                   "tested_version": version or "<run make_tags.py --create-version>"},
        "ignore_suffixes": IGNORE,
        "printer": {"bed": [220, 220, 250]},
        "fingertip_d": FINGERTIP_D, "min_clearance": MIN_CLEARANCE, "min_wall": 1.2,
        # laser-cut parts never change between revisions (brief, hard rule 3)
        "fixed": ["base_plate", "side_panel_L", "side_panel_R", "control_face", "front_panel", "top_panel", "rotor_plate",
                  "gusset_L", "gusset_R", "pico_frame", "lid", "rack_base", "rack_middle", "rack_top", "rack_end_L",
                  "rack_end_R", "rack_back_strip", "rack_cover"],
        "controls": {
            "power": {"skill": "slide", "parts": ["ref_toggle"], "reprintable": [],          # a bought toggle switch
                      "contact": r(outer_point(parts["ref_toggle"])), "approach": r(-n)},
            "start": button("start"), "stop": button("stop"), "time": button("time"),
            "dial": {"skill": "turn", "parts": ["dial_knob"], "moving": ["dial_knob"],
                     "motion": {"type": "revolve", "point": r(parts["dial_knob"].Center()), "axis": r(n), "degrees": 270},
                     "contact": r(outer_point(parts["dial_knob"])), "approach": r(-n), "actuates": ["ref_pot"]},
            "lid": {"skill": "pull", "parts": ["lid", "lid_handle", "lid_hinge_leaf", "lid_sensor_tab"],
                    "reprintable": ["lid_handle", "lid_hinge_leaf", "lid_sensor_tab"],
                    "moving": ["lid", "lid_handle", "lid_hinge_leaf", "lid_sensor_tab"],
                    "motion": {"type": "revolve", "point": r((pin.x, 0, pin.z)), "axis": [0, axis, 0], "degrees": 105},
                    "slide_in": True, "contact": r(hook_start), "approach": [-1, 0, 0], "pull": [0, 0, 1]},
            "well_A": {"skill": "place", "parts": ["well_insert_A", "tube_1"], "reprintable": ["well_insert_A"],
                       "moving": ["tube_1"], "motion": {"type": "place", "axis": [0, 0, -1], "seat": r((well.x, well.y, beam_z))}},
        },
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", type=pathlib.Path, help="a saved STEP export of the Rev A assembly (default: export it)")
    ap.add_argument("--create-version", action="store_true", help="make the permanent 'Rev A (tested)' version")
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "onshape.yaml")
    args = ap.parse_args(argv)

    settings = load_settings()
    doc = parse_document_url(settings.dev_document_url)
    document = f"https://cad.onshape.com/documents/{doc.did}/w/{doc.wvmid}"
    old = yaml.safe_load(args.out.read_text()) if args.out.exists() else {}
    version = (old.get("source") or {}).get("tested_version")
    version = None if not version or version.startswith("<") else version
    with OnshapeClient(settings) as c:
        if args.create_version:
            v = c.create_version(doc.did, doc.wvmid, "Rev A (tested)", "The revision the robot tested; analyst branches start here")
            version = v["id"]
            print("created version", version)
        step = args.step
        if step is None:
            step = pathlib.Path(tempfile.mkdtemp()) / "revA.step"
            step.write_bytes(c.export_step(DocRef(doc.did, "w", doc.wvmid, ASSEMBLY), kind="assembly"))
    parts = Tags(controls={}, ignore_suffixes=tuple(IGNORE)).normalize(load_step(step))
    tags = build(parts, document, version)
    Tags.from_dict(tags)                                     # the file must load
    args.out.write_text("# Written by make_tags.py from the Rev A model and brief.md only. See its docstring.\n"
                        + yaml.safe_dump(tags, sort_keys=False))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
