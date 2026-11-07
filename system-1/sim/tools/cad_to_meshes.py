"""One STL per named part of a STEP assembly, plus manifest.json (each part's colour, bounding box and whether it is
convex). Needs CadQuery, which the sim doesn't, so it runs in a throwaway environment:

    uv run --no-project --python 3.12 --with cadquery --with numpy python tools/cad_to_meshes.py assembly.step out_dir [--unit m]

STEP brings solids and positions, not mates: cad_device.py joins the parts into bodies from the device file."""
import argparse
import json
import pathlib

import cadquery as cq


def walk(assy, prefix=""):
    for child in assy.children:
        if child.children:
            yield from walk(child, prefix)
        elif child.obj is not None:
            yield child


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step")
    ap.add_argument("out")
    ap.add_argument("--tolerance", type=float, default=0.05, help="mm")
    ap.add_argument("--angular", type=float, default=0.25, help="rad")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    assy = cq.Assembly.importStep(args.step)
    manifest = {}
    for part in walk(assy):
        name = part.name.split("/")[-1].strip().replace(" ", "_")
        shape = part.obj.val() if isinstance(part.obj, cq.Workplane) else part.obj
        shape = shape.moved(assy.loc * part.loc) if part.loc is not None else shape
        path = out / f"{name}.stl"
        shape.exportStl(str(path), tolerance=args.tolerance, angularTolerance=args.angular)
        box = shape.BoundingBox()
        manifest[name] = dict(file=path.name, rgba=list(part.color.toTuple()) if part.color else None,
                              min=[box.xmin, box.ymin, box.zmin], max=[box.xmax, box.ymax, box.zmax], volume=shape.Volume())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for k, v in sorted(manifest.items()):
        print(f"{k:32s} {[round(x, 1) for x in v['min']]} {[round(x, 1) for x in v['max']]} rgba={v['rgba'] and [round(c, 2) for c in v['rgba']]}")


if __name__ == "__main__":
    main()
