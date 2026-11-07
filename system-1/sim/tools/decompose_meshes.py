"""Convex pieces for parts whose holes or hooks matter, since MuJoCo collides a mesh as its convex hull. Writes
<part>__c<i>.stl beside the part and lists them in manifest.json. Throwaway environment, like cad_to_meshes.py:

    uv run --no-project --python 3.12 --with coacd --with trimesh python tools/decompose_meshes.py meshes_dir part [part ...]
"""
import argparse
import json
import pathlib

import coacd
import numpy as np
import trimesh


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir")
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.02)
    args = ap.parse_args()
    root = pathlib.Path(args.dir)
    manifest = json.loads((root / "manifest.json").read_text())
    coacd.set_log_level("error")
    for name in args.parts:
        if name not in manifest:
            continue
        m = trimesh.load(root / manifest[name]["file"], force="mesh")
        pieces = coacd.run_coacd(coacd.Mesh(m.vertices, m.faces), threshold=args.threshold, max_convex_hull=64,
                                 preprocess_mode="off", resolution=4000, mcts_iterations=60, seed=1)
        files = []
        for i, (v, f) in enumerate(pieces):
            hull = trimesh.Trimesh(np.asarray(v), np.asarray(f)).convex_hull
            path = root / f"{name}__c{i}.stl"
            hull.export(path)
            files.append(path.name)
        manifest[name]["collision"] = files
        print(name, len(files), flush=True)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
