"""The appliance spec: a YAML file that fully describes the model. Nothing appliance-specific lives in code.

Units are mm. Every parameter is addressable by a dotted path, which is what a patch edits:
  shell.wall, shell.slope.angle, features.button_2.clearance, features.button_2.u
"""
from __future__ import annotations

import copy
import string
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

Number = Union[float, int]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")          # a typo in the YAML is an error, not a silent default


class Slope(_Strict):
    side: Literal["front", "back", "left", "right"] = "front"   # which top edge is cut off
    angle: float = 45.0                                          # degrees from horizontal
    run: float = 100.0                                           # horizontal depth of the cut, from that side


class Base(_Strict):
    """Plate that closes the open bottom: holds the microcontroller and locates the box on the desk fixture."""
    board: Literal["pico", "none"] = "pico"    # standoffs for a Raspberry Pi Pico (47 x 11.4 mm holes)
    board_u: float = 0.0                       # board offset from the box centre, mm (x)
    board_v: float = 0.0                       # (y)
    board_rot: bool = False                    # turn the board 90 degrees
    flange: float = 2.0                        # thickness of the plate the box stands on
    plug: float = 4.0                          # height of the part that fits inside the walls
    fit: float = 0.3
    fixture: bool = True                       # two desk corner pieces with pegs into the base


class Shell(_Strict):
    size: tuple[float, float, float]        # width x (across), depth y (front to back), height z
    wall: float = 3.5
    insert_t: float = 2.0                   # insert plate thickness = depth of the recess it drops into
    insert_fit: float = 0.2                 # gap around each insert in its recess
    ledge: float = 2.0                      # width of the shelf each insert sits on
    key: float = 3.0                        # size of the keying chamfer, so an insert only seats one way
    slope: Slope | None = None              # at most one sloped face
    base: Base | None = Base()              # set to null for no base plate or fixture


class Feature(_Strict):
    id: str
    type: str                               # button, push_latch, dial, slider, toggle, window, handle
    face: str                               # front, back, left, right, top, slope
    u: float = 0.0                          # mm from the face centre, across (to the right, seen from outside)
    v: float = 0.0                          # mm from the face centre, up the face
    params: dict[str, Union[Number, str, bool]] = {}


class Limits(_Strict):
    max_size: tuple[float, float, float] = (300.0, 300.0, 300.0)
    min_wall: float = 1.2
    clearance_range: tuple[float, float] = (0.10, 0.80)
    clearance_tol: float = 0.02             # measured clearance must match the parameter this closely
    edge_margin: float = 3.0                # insert edge to face edge
    min_web: float = 3.0                    # insert edge to insert edge on the same face
    fingertip_d: float = 12.0               # the robot's round fingertip
    aim_margin: float = 3.0                 # extra room around what the fingertip touches, for aiming error
    bare_patch: float = 20.0                # free flat circle needed on each control face, for the touch taps


class Posture(_Strict):
    max_params: int = 1                     # parameters changed per patch
    max_step: dict[str, float] = {"clearance": 0.25, "default": 2.0}   # by parameter name


class Printer(_Strict):
    density: float = 1.24                   # g/cm^3 (PLA)
    fill: float = 0.6                       # rough fraction of the solid volume actually printed
    g_per_min: float = 0.5                  # rough throughput for small parts
    overhead_min: float = 5.0               # heat-up, first layer, removal


class Spec(_Strict):
    name: str
    rev: str = "A"
    units: Literal["mm"] = "mm"
    shell: Shell
    features: list[Feature] = []
    limits: Limits = Limits()
    posture: Posture = Posture()
    printer: Printer = Printer()

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [f.id for f in self.features]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate feature ids: {sorted(dup)}")
        return self

    # ---- files ----
    @classmethod
    def load(cls, path: str | Path) -> "Spec":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))

    def feature(self, fid: str) -> Feature:
        for f in self.features:
            if f.id == fid:
                return f
        raise KeyError(f"no feature '{fid}'")

    # ---- dotted paths ----
    def get(self, path: str):
        parts = path.split(".")
        if parts[0] == "features":
            if len(parts) != 3:
                raise KeyError(f"feature paths look like features.<id>.<param>, got '{path}'")
            f = self.feature(parts[1])
            if parts[2] in ("u", "v", "face", "type"):
                return getattr(f, parts[2])
            from .features import effective_params
            params = effective_params(f)
            if parts[2] not in params:
                raise KeyError(f"unknown parameter '{path}' (a {f.type} has: u, v, face, {', '.join(sorted(params))})")
            return params[parts[2]]
        node = self
        for p in parts:
            if not hasattr(node, p):
                raise KeyError(f"unknown parameter '{path}'")
            node = getattr(node, p)
        return node

    def with_edits(self, edits: dict[str, object]) -> "Spec":
        """A copy of the spec with dotted-path edits applied (validated again)."""
        data = copy.deepcopy(self.model_dump(mode="python"))
        for path, value in edits.items():
            self.get(path)                                 # unknown path -> KeyError
            parts = path.split(".")
            if parts[0] == "features":
                f = next(f for f in data["features"] if f["id"] == parts[1])
                if parts[2] in ("u", "v", "face", "type"):
                    f[parts[2]] = value
                else:
                    f.setdefault("params", {})[parts[2]] = value
            else:
                node = data
                for p in parts[:-1]:
                    node = node[p]
                node[parts[-1]] = value
        return Spec.model_validate(data)


def next_rev(rev: str) -> str:
    """A -> B, B -> C; anything else gets a numeric suffix."""
    if len(rev) == 1 and rev in string.ascii_uppercase[:-1]:
        return chr(ord(rev) + 1)
    return f"{rev}.1"
