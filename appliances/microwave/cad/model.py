"""The MW-1 mock microwave, as build.py wants it: one assembly per revision, mm.

Sourced from Karthik's vendor STEPs (source/step/mw1_rev{A,B}.step), which are in the sim frame (origin at the centre of
the base's bottom face, +X toward the arm, +Z up) with one named solid per part. Nothing of the product is redrawn: each
revision is its STEP, read as an assembly so the part names survive (the hinge parts carry _revA / _revB).

One fixture is added: the box stands on an 80 mm riser block (fixture_riser), so the product is raised RISER_MM here and
every z in device.yaml is the STEP's plus RISER_MM. Why: the lowest button (STOP) is 22 mm above the box's base, and a
level stock gripper's wrist camera hangs 81 mm below its tip, so on the bare stand board it struck the board on every
button (see device.yaml). The riser is smaller than the base, so nothing of it stands proud of the product.
"""
import pathlib

import cadquery as cq

STEP = pathlib.Path(__file__).resolve().parents[1] / "source" / "step"
RISER_MM = 80.0
RISER = (130.0, 236.0)   # x, y: inside the base's 138 x 244

# MuJoCo collides a mesh as its hull: the D-handle's bar stands 12 mm off the door, and the jaws go in behind it
CONCAVE = ["handle"]


def _leaves(assy, loc=None):
    loc = assy.loc if loc is None else loc * assy.loc
    for child in assy.children:
        if child.children:
            yield from _leaves(child, loc)
        elif child.obj is not None:
            shape = child.obj.val() if isinstance(child.obj, cq.Workplane) else child.obj
            yield child.name.split("/")[-1].strip().replace(" ", "_"), shape.moved(loc * child.loc), child.color


def _raised(path):
    out = cq.Assembly(name=path.stem)
    up = cq.Location(cq.Vector(0, 0, RISER_MM))
    for name, shape, colour in _leaves(cq.Assembly.importStep(str(path))):
        out.add(shape.moved(up), name=name, color=colour)
    riser = cq.Workplane("XY").box(RISER[0], RISER[1], RISER_MM, centered=(True, True, False)).val()
    out.add(riser, name="fixture_riser", color=cq.Color(0.45, 0.45, 0.48, 1))
    return out


def assemblies():
    return {rev: _raised(STEP / f"mw1_rev{rev}.step") for rev in ("A", "B")}
