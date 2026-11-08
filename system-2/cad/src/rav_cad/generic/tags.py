"""The tag file: what the checks need to know about a product that its CAD doesn't say.

One YAML file per product, kept in the repo next to its CAD link (subjects/<product>/onshape.yaml). Units are mm,
in the assembly's frame. Example:

    printer: {bed: [220, 220, 250]}       # what the reprint has to fit on
    fingertip_d: 12                       # the robot's round fingertip
    min_clearance: 0.3                    # sliding parts, per side
    min_wall: 1.2
    fixed: [shell, base]                  # never reprinted by a fix (hours of printing)
    controls:
      button_2:
        skill: press                      # press | pull | slide | turn
        parts: [button_2 insert, button_2 moving]   # everything that belongs to this control
        reprintable: [button_2 insert]    # what a fix may change (defaults to every part of the control)
        moving: [button_2 moving]         # the parts that move together when operated
        motion: {type: slide, axis: [0, 0.707, -0.707], travel: 1.2}
        # or   {type: revolve, point: [x, y, z], axis: [x, y, z], degrees: 90}
        contact: [80, 15, 165]            # where the fingertip touches, on the surface, at rest
        approach: [0, 0.707, -0.707]      # direction the fingertip travels into the contact
        fit: [button_2 moving, button_2 insert]     # a sliding pair whose gap must stay >= min_clearance
      door:
        skill: pull                       # the fingertip hooks behind the handle and pulls: no pinch, no grip
        parts: [door insert, door moving]
        moving: [door insert, door moving]
        motion: {type: revolve, point: [42, -3, 35], axis: [0, 0, -1], degrees: 95}
        contact: [86.5, -9, 35]           # pull: where the fingertip's centre goes, behind the handle
        approach: [0, 0, 1]               # it slides in from below
        pull: [0, -1, 0]                  # and pulls outward

Motion comes from the Onshape assembly's mates when the backend can read them (slider -> slide, revolute ->
revolve); the file fills in what mates don't say. Part names are matched after dropping Onshape's " <1>" suffix.
"""
from __future__ import annotations

import math
import pathlib
import re
from dataclasses import dataclass, field

SKILLS = ("press", "pull", "slide", "turn", "place")
_SUFFIX = re.compile(r"\s*<\d+>$")


def clean_name(name: str) -> str:
    """Onshape names instances 'button_2 cap <1>'; the tag file says 'button_2 cap'."""
    return _SUFFIX.sub("", name.strip())


def _vec(v, what: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError(f"{what} must be [x, y, z], got {v!r}")
    return tuple(float(c) for c in v)


def _unit(v: tuple[float, float, float], what: str) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-9:
        raise ValueError(f"{what} can't be a zero vector")
    return tuple(c / n for c in v)


@dataclass(frozen=True)
class Motion:
    type: str                                   # "slide", "revolve" or "place"
    axis: tuple[float, float, float]            # unit; slide or place direction, or the hinge axis
    travel: float = 0.0                         # mm, for slide
    point: tuple[float, float, float] | None = None   # a point on the hinge axis, for revolve
    degrees: float = 0.0                        # for revolve
    seat: tuple[float, float, float] | None = None   # place: a point the part's leading end must reach

    @classmethod
    def parse(cls, d: dict, where: str) -> Motion:
        kind = d.get("type")
        axis = lambda: _unit(_vec(d.get("axis"), f"{where}.axis"), f"{where}.axis")  # noqa: E731
        if kind == "slide":
            return cls("slide", axis(), travel=float(d.get("travel", 0)))
        if kind == "revolve":
            return cls("revolve", axis(), point=_vec(d.get("point"), f"{where}.point"), degrees=float(d.get("degrees", 0)))
        if kind == "place":
            # e.g. a tube lowered into its well: axis [0, 0, -1], seat = a point at the height its tip must reach
            if d.get("seat") is None:
                raise ValueError(f"{where}.seat is needed for place: a point the part's leading end must reach")
            return cls("place", axis(), seat=_vec(d["seat"], f"{where}.seat"))
        raise ValueError(f"{where}.type must be slide, revolve or place, got {kind!r}")


@dataclass(frozen=True)
class Control:
    id: str
    skill: str
    parts: tuple[str, ...]
    reprintable: tuple[str, ...]
    moving: tuple[str, ...] = ()               # every part that moves together when operated
    motion: Motion | None = None
    contact: tuple[float, float, float] | None = None    # press: on the surface; pull: where the fingertip's centre goes
    approach: tuple[float, float, float] | None = None   # direction the fingertip travels to reach the contact
    pull: tuple[float, float, float] | None = None       # pull only: the direction the fingertip pulls to open it
    fit: tuple[str, str] | None = None
    probe_d: float | None = None               # the tool that touches this control, if not the fingertip (a hook jaw)
    actuates: tuple[str, ...] = ()             # what the control drives (its switch, the pot): its motion may touch these
    slide_in: bool = False                     # pull: start at `contact`, slide along `approach` until touching, then pull


@dataclass(frozen=True)
class Tags:
    controls: dict[str, Control]
    fixed: tuple[str, ...] = ()
    bed: tuple[float, float, float] = (220.0, 220.0, 250.0)
    fingertip_d: float = 12.0
    min_clearance: float = 0.3
    min_wall: float = 1.2
    source: dict = field(default_factory=dict)  # document ids and anything else the backend keeps here
    ignore_suffixes: tuple[str, ...] = ()       # e.g. ("_revA", "_revB"): revision tags in part names

    def normalize(self, parts: dict) -> dict:
        """Part names as the tag file uses them: 'bezel_stop_revA' -> 'bezel_stop' when '_revA' is ignored."""
        def base(name: str) -> str:
            for s in self.ignore_suffixes:
                if name.endswith(s):
                    return name[: -len(s)]
            return name
        return {base(n): s for n, s in parts.items()}

    @classmethod
    def from_dict(cls, d: dict) -> Tags:
        controls = {}
        for cid, c in (d.get("controls") or {}).items():
            where = f"controls.{cid}"
            skill = c.get("skill", "press")
            if skill not in SKILLS:
                raise ValueError(f"{where}.skill must be one of {', '.join(SKILLS)}, got {skill!r}")
            parts = tuple(clean_name(p) for p in c.get("parts") or [])
            if not parts:
                raise ValueError(f"{where}.parts is empty: list the parts that make up this control")
            raw_moving = c.get("moving") or []
            moving = tuple(clean_name(p) for p in ([raw_moving] if isinstance(raw_moving, str) else raw_moving))
            fit = tuple(clean_name(p) for p in c["fit"]) if c.get("fit") else None
            if fit is not None and len(fit) != 2:
                raise ValueError(f"{where}.fit must name two parts")
            if skill == "pull" and c.get("pull") is None:
                raise ValueError(f"{where}.pull is needed for a pull control: the direction the fingertip pulls")
            unit = lambda key: _unit(_vec(c[key], f"{where}.{key}"), f"{where}.{key}") if c.get(key) is not None else None  # noqa: E731
            controls[cid] = Control(
                id=cid, skill=skill, parts=parts,
                # an explicit empty list means nothing of this control may change (a bought switch)
                reprintable=tuple(clean_name(p) for p in (c["reprintable"] if "reprintable" in c else parts)),
                moving=moving, motion=Motion.parse(c["motion"], f"{where}.motion") if c.get("motion") else None,
                contact=_vec(c["contact"], f"{where}.contact") if c.get("contact") is not None else None,
                approach=unit("approach"), pull=unit("pull"), fit=fit,
                probe_d=float(c["probe_d"]) if c.get("probe_d") is not None else None,
                actuates=tuple(clean_name(p) for p in c.get("actuates") or []), slide_in=bool(c.get("slide_in")))
        printer = d.get("printer") or {}
        return cls(controls=controls, fixed=tuple(clean_name(p) for p in d.get("fixed") or []),
                   bed=_vec(printer.get("bed", (220, 220, 250)), "printer.bed"), fingertip_d=float(d.get("fingertip_d", 12.0)),
                   min_clearance=float(d.get("min_clearance", 0.3)), min_wall=float(d.get("min_wall", 1.2)),
                   source=dict(d.get("source") or {}), ignore_suffixes=tuple(d.get("ignore_suffixes") or ()))

    @classmethod
    def load(cls, path: str | pathlib.Path) -> Tags:
        import yaml
        return cls.from_dict(yaml.safe_load(pathlib.Path(path).read_text()) or {})

    def reprintable(self) -> set[str]:
        return {p for c in self.controls.values() for p in c.reprintable}

    def owner(self, part: str) -> str | None:
        """The control a part belongs to, or None for the body."""
        return next((c.id for c in self.controls.values() if part in c.parts), None)

    def missing(self, names: set[str]) -> list[str]:
        """Part names the tag file uses that the CAD doesn't have. Empty means the file matches the model."""
        used = set(self.fixed)
        for c in self.controls.values():
            used |= set(c.parts) | set(c.reprintable) | set(c.moving) | set(c.fit or ()) | set(c.actuates)
        return sorted(used - names)
