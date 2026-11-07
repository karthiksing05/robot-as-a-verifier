"""Clearance gauge: print this first at the event, on the same printer, profile and orientation as the inserts.

A plate with one bore per clearance value (engraved with the value in hundredths of a mm: "15" = 0.15 mm) and
a peg that matches the feature's stem. Push the peg through each bore with the scale. Pick the fault value
(binds clearly, e.g. about 8 N within the first mm) and the fix value (presses like a good button).
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq

from .features import TYPES, effective_params
from .geom import block, xsec
from .spec import Feature, Spec

DEFAULT_VALUES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]


def stem_of(params: dict) -> tuple[bool, float, float, float]:
    """(round, half_u, half_v, engagement length) of the sliding part, for plunger and slot features."""
    if "stem_d" in params:
        return params.get("shape", "round") == "round", params["stem_d"] / 2, params["stem_d"] / 2, params["guide"]
    if "stem_u" in params:
        return False, params["stem_u"] / 2, params["stem_v"] / 2, params["guide"]
    if "stem_w" in params:
        return False, params["stem_w"] / 2, params["stem_w"] / 2, 0.0
    raise ValueError("this feature type has no sliding fit to gauge")


def make(params: dict, insert_t: float, values=DEFAULT_VALUES) -> dict[str, cq.Shape]:
    rnd, hu, hv, guide = stem_of(params)
    thick = insert_t + guide                       # same engagement length as the real bore
    pitch = 2 * max(hu, hv) + 2 * max(values) + 9
    n = len(values)
    W, Dp = n * pitch + 4, 2 * max(hu, hv) + 18
    plate = block(W / 2, Dp / 2, 0, thick)
    for i, c in enumerate(values):
        x = -W / 2 + 2 + pitch * (i + 0.5)
        plate = plate.cut(xsec(rnd, hu + c, hv + c, -1, thick + 1).translate((x, -3, 0)))
        label = cq.Workplane("XY").workplane(offset=thick).center(x, Dp / 2 - 5).text(
            f"{round(c * 100):d}", 4.0, -0.6, combine=False).val()
        plate = plate.cut(label)
    head = xsec(rnd, hu + 2.5, hv + 2.5, 0, 3)
    peg = head.fuse(xsec(rnd, hu, hv, 2.99, 3 + thick + 6)).clean()
    return {"gauge_plate": plate.clean(), "gauge_peg": peg}


def for_feature(spec: Spec, fid: str, out_dir: str | Path, values=DEFAULT_VALUES) -> list[Path]:
    return _write(make(effective_params(spec.feature(fid)), spec.shell.insert_t, values), out_dir)


def for_type(ftype: str, out_dir: str | Path, insert_t: float = 2.0, values=DEFAULT_VALUES) -> list[Path]:
    f = Feature(id="gauge", type=ftype, face="top")
    if ftype not in TYPES:
        raise KeyError(f"unknown type '{ftype}'")
    return _write(make(effective_params(f), insert_t, values), out_dir)


def _write(parts: dict[str, cq.Shape], out_dir) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, s in parts.items():
        p = out / f"{name}.stl"
        cq.exporters.export(s, str(p), tolerance=0.02, angularTolerance=0.1)
        paths.append(p)
    return paths
