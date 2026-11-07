"""Read and write a product as a STEP assembly of named parts, in one frame (mm)."""
from __future__ import annotations

import pathlib

import cadquery as cq

from .tags import clean_name


def _shape(obj) -> cq.Shape | None:
    if obj is None:
        return None
    if isinstance(obj, cq.Workplane):
        vals = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        return vals[0] if len(vals) == 1 else (cq.Compound.makeCompound(vals) if vals else None)
    return obj if isinstance(obj, cq.Shape) else None


def load_step(path: str | pathlib.Path) -> dict[str, cq.Shape]:
    """Every leaf part of the assembly, placed in the assembly frame, keyed by its cleaned name.

    Nested sub-assemblies are walked with their locations composed. Two parts with the same name get " #2", " #3"
    so nothing is silently dropped (the tag file should then name them apart)."""
    root = cq.Assembly.importStep(str(path))
    out: dict[str, cq.Shape] = {}

    def walk(node: cq.Assembly, loc: cq.Location) -> None:
        here = loc * node.loc if node.loc is not None else loc
        s = _shape(node.obj)
        if s is not None:
            name, n = clean_name(node.name), 2
            while name in out:
                name, n = f"{clean_name(node.name)} #{n}", n + 1
            out[name] = s.moved(here)
        for child in node.children:
            walk(child, here)

    walk(root, cq.Location())
    return out


def save_step(parts: dict[str, cq.Shape], path: str | pathlib.Path) -> pathlib.Path:
    a = cq.Assembly(name="product")
    for name, s in parts.items():
        a.add(s, name=name)
    p = pathlib.Path(path)
    a.export(str(p))
    return p
