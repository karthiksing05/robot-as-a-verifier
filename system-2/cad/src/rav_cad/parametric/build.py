"""Build a spec into solids, and export STLs, features.json and assembly.glb.

The shell, base and fixture are exported in the device frame (print the shell upright, open bottom down).
Inserts and moving pieces are exported in their own local frame (flat, bore or slot axis vertical): print them
that way every time, because print orientation changes a fit more than a 0.25 mm patch does.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cadquery as cq

from .faces import Frame, frames, make_base, make_shell
from .features import TYPES, effective_params
from .geom import Ctx, FeatureGeom, block, fuse, keyed_outline, prism, signature
from .spec import Feature, Spec


@dataclass
class Placed:
    feature: Feature
    params: dict
    geom: FeatureGeom
    plane: cq.Plane
    insert: cq.Shape                 # device frame
    moving: cq.Shape | None          # device frame, rest pose
    slider: cq.Shape | None = None
    extras: dict[str, cq.Shape] = field(default_factory=dict)
    hardware: dict[str, cq.Shape] = field(default_factory=dict)


@dataclass
class Built:
    spec: Spec
    frames: dict[str, Frame]
    shell_raw: cq.Shape              # hollow shell before pockets (used to test what lies on a face)
    shell: cq.Shape                  # with pockets cut and hinge knuckles etc. added
    placed: dict[str, Placed] = field(default_factory=dict)
    base: cq.Shape | None = None
    fixture: dict[str, cq.Shape] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def pieces(self) -> dict[str, cq.Shape]:
        """Every printable part, keyed by file stem: shell, base, fixture_1, <id>__insert, <id>__cap, ..."""
        out = {"shell": self.shell}
        if self.base is not None:
            out["base"] = self.base
        out.update(self.fixture)
        for fid, pl in self.placed.items():
            for name, s in pl.geom.pieces.items():
                bb = s.BoundingBox()
                out[f"{fid}__{name}"] = s.translate((-bb.center.x, -bb.center.y, -bb.zmin))
        return out

    def assembly(self) -> cq.Shape:
        parts = [self.shell] + ([self.base] if self.base is not None else [])
        for p in self.placed.values():
            parts += [p.insert] + ([p.moving] if p.moving is not None else []) + list(p.extras.values())
        return cq.Compound.makeCompound(parts)


def build(spec: Spec) -> Built:
    fr = frames(spec.shell)
    shell_raw = make_shell(spec.shell, fr)
    sh, lim = spec.shell, spec.limits
    ctx = Ctx(t=sh.insert_t, ledge=sh.ledge, key=sh.key, min_wall=lim.min_wall, wall=sh.wall, fit=sh.insert_fit,
              fingertip_d=lim.fingertip_d)
    b = Built(spec, fr, shell_raw, shell_raw)
    cuts, adds = [], []
    for f in spec.features:
        if f.face not in fr:
            b.errors.append(f"feature '{f.id}': face '{f.face}' doesn't exist (have: {sorted(fr)})")
            continue
        try:
            params = effective_params(f)
            geom = TYPES[f.type][0](params, ctx)
        except (KeyError, ValueError) as e:
            b.errors.append(str(e).strip("'\""))
            continue
        plane = fr[f.face].plane(f.u, f.v)
        loc = cq.Location(plane)
        if geom.pocket is not None:
            cuts.append(geom.pocket.moved(loc))
        else:
            hu, hv = geom.half
            recess = prism(keyed_outline(hu + sh.insert_fit, hv + sh.insert_fit, sh.key), -sh.insert_t, 1.0)
            opening = block(hu - sh.ledge, hv - sh.ledge, -(sh.wall + 2), 0.5)
            cuts.append(fuse(recess, opening).moved(loc))
        adds += [s.moved(loc) for s in geom.shell_add]
        mv = lambda s: s.moved(loc) if s is not None else None          # noqa: E731
        b.placed[f.id] = Placed(f, params, geom, plane, mv(geom.insert), mv(geom.moving), mv(geom.slider),
                                {k: mv(v) for k, v in geom.extras.items()},
                                {k: mv(v) for k, v in geom.hardware.items()})
    for c in cuts:
        b.shell = b.shell.cut(c)
    for a in adds:
        b.shell = b.shell.fuse(a)
    b.shell = b.shell.clean()
    if sh.base is not None:
        b.base, b.fixture = make_base(sh)
    return b


def features_json(b: Built) -> dict:
    """Feature list for the planner, the sim and the detector check: poses and waypoints in the device frame."""
    out = []
    for fid, p in b.placed.items():
        w = lambda xyz: [round(c, 3) for c in p.plane.toWorldCoords(tuple(xyz)).toTuple()]   # noqa: E731
        item = {
            "id": fid, "type": p.feature.type, "face": p.feature.face,
            "origin": w((0, 0, 0)), "normal": [round(c, 4) for c in p.plane.zDir.toTuple()],
            "u_axis": [round(c, 4) for c in p.plane.xDir.toTuple()],
            "insert_half_mm": [round(x, 3) for x in p.geom.half],
            "clearance_mm": p.geom.clearance,
            "waypoints": {k: w(v) for k, v in p.geom.waypoints.items()},
            "info": p.geom.info,
        }
        if p.geom.swing:
            pt, d, deg = p.geom.swing
            o = p.plane.toWorldCoords((0, 0, 0))
            item["hinge"] = {"point": w(pt), "axis": [round(c, 4) for c in (p.plane.toWorldCoords(d) - o).toTuple()],
                             "max_deg": deg}
        out.append(item)
    return {"name": b.spec.name, "rev": b.spec.rev, "units": "mm", "frame": "x across, y front to back, z up, "
            "origin bottom front left", "size": list(b.spec.shell.size), "features": out}


def export(b: Built, out_dir: str | Path, only: set[str] | None = None) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, s in b.pieces().items():
        if only is not None and name not in only:
            continue
        path = out / f"{name}.stl"
        cq.exporters.export(s, str(path), tolerance=0.02, angularTolerance=0.1)
        written.append(path)
    (out / "features.json").write_text(json.dumps(features_json(b), indent=2, default=list))
    b.spec.save(out / "spec.yaml")
    export_glb(b, out / "assembly.glb")
    return written


def export_glb(b: Built, path: str | Path) -> None:
    """The assembled device (rest pose) for viewer.html. Bought parts (switches, display) are dark grey."""
    a = cq.Assembly(name=f"{b.spec.name}_rev_{b.spec.rev}")
    a.add(b.shell, name="shell", color=cq.Color(0.79, 0.78, 0.75))
    if b.base is not None:
        a.add(b.base, name="base", color=cq.Color(0.62, 0.61, 0.58))
    for name, s in b.fixture.items():
        a.add(s, name=name, color=cq.Color(0.45, 0.47, 0.42))
    for fid, p in b.placed.items():
        a.add(p.insert, name=f"{fid}__insert", color=cq.Color(0.23, 0.43, 0.66))
        if p.moving is not None:
            a.add(p.moving, name=f"{fid}__moving", color=cq.Color(0.88, 0.54, 0.17))
        for k, s in p.extras.items():
            a.add(s, name=f"{fid}__{k}", color=cq.Color(0.36, 0.55, 0.75))
        for k, s in p.hardware.items():
            a.add(s, name=f"{fid}__hw_{k}", color=cq.Color(0.15, 0.15, 0.17))
    a.export(str(path), tolerance=0.1, angularTolerance=0.2)


def signatures(b: Built) -> dict[str, tuple]:
    return {name: signature(s) for name, s in b.pieces().items()}


__all__ = ["Built", "Placed", "build", "export", "export_glb", "features_json", "signatures", "FeatureGeom", "Ctx"]
