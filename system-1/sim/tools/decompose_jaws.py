"""Convex pieces for the SO-101's two jaws, for the stock gripper (robot.py, effector="stock"): MuJoCo collides a mesh
as its convex hull, and each jaw's hull fills the gap between the fingers, so nothing sits between them. Writes
assets/so101/jaw_pieces/<mesh>__c<i>.stl. Throwaway environment:

    uv run --no-project --python 3.12 --with coacd --with trimesh python sim/tools/decompose_jaws.py
"""
import pathlib

import coacd
import numpy as np
import trimesh

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets" / "so101"
MESHES = ("wrist_roll_follower_so101_v1", "moving_jaw_so101_v1")


def main():
    out = ASSETS / "jaw_pieces"
    out.mkdir(exist_ok=True)
    coacd.set_log_level("error")
    for name in MESHES:
        m = trimesh.load(ASSETS / "assets" / f"{name}.stl", force="mesh")
        pieces = coacd.run_coacd(coacd.Mesh(m.vertices, m.faces), threshold=0.03, max_convex_hull=24,
                                 preprocess_mode="auto", resolution=3000, mcts_iterations=60, seed=1)
        for old in out.glob(f"{name}__c*.stl"):
            old.unlink()
        for i, (v, f) in enumerate(pieces):
            trimesh.Trimesh(np.asarray(v), np.asarray(f)).convex_hull.export(out / f"{name}__c{i}.stl")
        print(name, len(pieces), flush=True)


if __name__ == "__main__":
    main()
