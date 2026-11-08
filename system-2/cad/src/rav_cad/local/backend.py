"""LocalCadBackend: the fix loop's CadBackend on a local copy of the product, where the analyst writes new geometry.

The same shape as OnshapeBackend, so the same analyst and checks work on both. The tested revision is the base parts
(from a STEP assembly or our parametric model) and is never edited. Each fix gets its own Workspace (a folder) where
the analyst replaces reprintable parts with solids made by its own CadQuery code; a patch points at the workspace's
state hash. check() runs the generic robot-centred checks against the base; apply() needs an approver, makes sure the
workspace hasn't changed since the check, and writes rev_<X>/ with the changed parts' STLs, the full assembly STEP and
the code that made each new part.
"""
from __future__ import annotations

import inspect
import itertools
import json
import pathlib
import re
import shutil
from typing import Any

import cadquery as cq
from rav_contracts import CADPatch, CadSource

from ..generic import Tags, failures, load_step, run, save_step
from ..generic.checks import _changed, as_json
from ..onshape.backend import BranchCheck
from .workspace import Workspace

PREFIX = "local:"


def _r(v, n=3):
    return round(float(v), n)


def faces_of(shape: cq.Shape) -> list[dict]:
    """A solid's faces, largest first: id (f1, f2, ... stable while the solid doesn't change), kind, area and its
    plane (normal, origin) or cylinder (radius, axis, origin), in mm."""
    rows = []
    for f in shape.Faces():
        row: dict[str, Any] = {"area": _r(f.Area(), 2)}
        kind = f.geomType()
        if kind == "PLANE":
            n, c = f.normalAt(), f.Center()
            row.update(kind="plane", normal=[_r(x, 4) for x in n.toTuple()], origin=[_r(x) for x in c.toTuple()])
        elif kind == "CYLINDER":
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            ad = BRepAdaptor_Surface(f.wrapped).Cylinder()    # also right for trimmed and offset surfaces
            ax = ad.Axis()
            row.update(kind="cylinder", radius=_r(ad.Radius()),
                       axis=[_r(x, 4) for x in (ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z())],
                       origin=[_r(x) for x in (ax.Location().X(), ax.Location().Y(), ax.Location().Z())])
        else:
            row["kind"] = kind.lower()
        bb = f.BoundingBox()
        row["box"] = [_r(x, 2) for x in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)]
        rows.append(row)
    rows.sort(key=lambda r: -r["area"])
    return [{"id": f"f{i + 1}", **r} for i, r in enumerate(rows)]


class LocalCadBackend:
    name = "local"

    def __init__(self, tags_path: str | pathlib.Path, base: dict[str, cq.Shape] | str | pathlib.Path,
                 out_dir: str | pathlib.Path | None = None, require_approval: bool = True, product: str | None = None,
                 sources: dict[str, str] | None = None):
        """`base` is the tested revision: named solids, or a STEP assembly's path. `sources` optionally maps a part to
        the CadQuery source that builds it in our parametric model (shown to the analyst as a reference)."""
        self.tags_path = pathlib.Path(tags_path)
        self.tags = Tags.load(self.tags_path)
        self.base_path = None if isinstance(base, dict) else pathlib.Path(base)
        self._base = self.tags.normalize(base if isinstance(base, dict) else load_step(base))
        self.product = product or self.tags_path.parent.name or "product"
        self.out_dir = pathlib.Path(out_dir) if out_dir else self.tags_path.parent / "local_out"
        self.require_approval = require_approval
        self.sources = sources or {}
        self._open: dict[str, Workspace] = {}

    # --- where things are -------------------------------------------------------------------------------------

    @property
    def document_id(self) -> str:
        return PREFIX + self.product

    def branch(self, workspace_id: str) -> Workspace:
        if workspace_id not in self._open:
            self._open[workspace_id] = Workspace(workspace_id)
        return self._open[workspace_id]

    def url(self, workspace_id: str) -> str:
        return str(pathlib.Path(workspace_id).resolve())

    def microversion(self, workspace_id: str) -> str:
        return self.branch(workspace_id).state()

    def open_branch(self, name: str, description: str = "", root: str | pathlib.Path | None = None) -> str:
        """A new workspace holding the tested revision. The analyst only ever edits this. Returns its folder."""
        parent = pathlib.Path(root) if root else self.out_dir / "workspaces"
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:40] or "fix"
        for n in itertools.count(1):
            path = parent / (slug if n == 1 else f"{slug}-{n}")
            if not path.exists():
                break
        ws = Workspace.create(path, self._base, name=self.product)
        self._open[str(path)] = ws
        return str(path)

    def before(self) -> dict:
        return dict(self._base)

    def check_branch(self, workspace_id: str, quick: bool = False) -> BranchCheck:
        ws = self.branch(workspace_id)
        state = ws.state()
        after = ws.parts()
        before = self.before()
        changed = _changed(before, after)
        owners = sorted({o for o in (self.tags.owner(n) for n in changed) if o})
        target = owners[0] if len(owners) == 1 else None
        results = run(after, self.tags, before=before, target=target, quick=quick)
        return BranchCheck(state, changed, target, failures(results), as_json(results))

    # --- CadBackend -------------------------------------------------------------------------------------------

    def read_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {"rev": "A", "backend": "local", "document": self.document_id}
        for c in self.tags.controls.values():
            out[f"controls.{c.id}"] = {"skill": c.skill, "parts": list(c.parts), "reprintable": list(c.reprintable)}
        return out

    def rules(self) -> str:
        t = self.tags
        return "\n".join([
            "Work only in your own workspace; the tested revision is never changed. You replace whole parts by writing "
            "CadQuery code that makes the new solid.",
            "A fix may change parts of one control only, and only parts listed as reprintable. The body "
            f"({', '.join(t.fixed) or 'none listed'}) is never reprinted.",
            f"Changed parts must be single valid solids that fit a {' x '.join(f'{b:g}' for b in t.bed)} mm printer bed.",
            f"Sliding parts keep at least {t.min_clearance:g} mm of clearance per side, measured at mid-travel.",
            "Nothing overlaps at rest, and moving parts never hit anything through their full travel or swing.",
            f"The robot uses a round {t.fingertip_d:g} mm fingertip: it must reach every control from outside without "
            "touching anything else. A pull control must catch the fingertip when it pulls (a hook): the robot "
            "can't pinch or grip.",
            "A failure that was already there in the tested version on another control doesn't count against a fix.",
        ])

    def check(self, patch: CADPatch) -> list[str]:
        if patch.source is None:
            return ["a local patch points at its workspace (source); make the change with the CAD tools"]
        if patch.source.document_id != self.document_id:
            return [f"the patch is for {patch.source.document_id}, not {self.document_id}"]
        if not pathlib.Path(patch.source.workspace_id, "meta.json").exists():
            return [f"no workspace at {patch.source.workspace_id}"]
        result = self.check_branch(patch.source.workspace_id)
        if result.microversion != patch.source.microversion_id:
            return ["the workspace has changed since this patch was made; check it again and resubmit"]
        return result.reasons

    def apply(self, patch: CADPatch) -> str:
        if self.require_approval and not patch.approved_by:
            raise ValueError("a teammate approves a patch before it is applied and printed (set approved_by)")
        problems = self.check(patch)
        if problems:
            raise ValueError("; ".join(problems))
        ws = self.branch(patch.source.workspace_id)
        result = self.check_branch(patch.source.workspace_id)
        out = self.out_dir / f"rev_{patch.revision_to}"
        out.mkdir(parents=True, exist_ok=True)
        parts = ws.parts()
        written = []
        for name in result.changed:
            if name in parts:
                stem = re.sub(r"[^A-Za-z0-9 _.-]+", "_", name)
                cq.exporters.export(parts[name], str(out / f"{stem}.stl"), tolerance=0.05, angularTolerance=0.1)
                written.append(f"{stem}.stl")
                code = ws.code(name)
                if code:
                    (out / f"{stem}.py").write_text(code)
        save_step(parts, out / "assembly.step")
        shutil.copy(ws.root / "edits.jsonl", out / "edits.jsonl")
        (out / "patch_result.json").write_text(json.dumps({
            "workspace": str(ws.root), "state": result.microversion, "changed": result.changed, "stl": written,
            "checks": result.results, "patch": patch.model_dump(mode="json")}, indent=2))
        return str(out)

    def faces(self, part: str, workspace_id: str | None = None) -> list[dict]:
        parts = self.branch(workspace_id).parts() if workspace_id else self._base
        if part not in parts:
            raise LookupError(f"no part named {part}; list_controls has the names")
        return faces_of(parts[part])

    def describe(self, control: str, max_faces: int = 12) -> str:
        from ..parametric.geom import distance
        c = self.tags.controls.get(control)
        if c is None:
            return ""
        parts = self._base
        lines = [f"Control {c.id}: skill {c.skill}; parts {', '.join(c.parts)}; may reprint {', '.join(c.reprintable) or 'nothing'}"
                 + (f"; it drives {', '.join(c.actuates)}" if c.actuates else "")]
        for name in dict.fromkeys([*c.parts, *c.actuates]):
            if name in parts:
                bb = parts[name].BoundingBox()
                lines.append(f"- {name}: box X {bb.xmin:.2f}..{bb.xmax:.2f}, Y {bb.ymin:.2f}..{bb.ymax:.2f}, "
                             f"Z {bb.zmin:.2f}..{bb.zmax:.2f} mm; volume {parts[name].Volume():.0f} mm3")
        if c.fit and all(p in parts for p in c.fit):
            lines.append(f"- gap between {c.fit[0]} and {c.fit[1]} at rest: {distance(parts[c.fit[0]], parts[c.fit[1]]):.3f} mm")
        for name in c.reprintable:
            if name not in parts:
                continue
            fs = faces_of(parts[name])
            shown = [f for f in fs if f.get("kind") == "cylinder"] + [f for f in fs if f.get("kind") != "cylinder"]
            lines.append(f"- faces of {name} ({len(fs)}; cylinders first, then largest):")
            lines += [f"    {json.dumps(f)}" for f in shown[:max_faces]]
        return "\n".join(lines)

    def source(self, workspace_id: str, microversion: str) -> CadSource:
        return CadSource(document_id=self.document_id, workspace_id=str(workspace_id), microversion_id=microversion,
                         base_version_id=str(self.tags.source.get("tested_version") or "A"), url=self.url(workspace_id))


def parametric_sources(built) -> dict[str, str]:
    """For our parametric appliance: each control's parts -> the CadQuery source of the feature type that builds
    them (a reference for the analyst, who writes its own code)."""
    from ..generic import bench
    from ..parametric.features import TYPES
    out = {}
    names = bench.parts(built)
    for fid, p in built.placed.items():
        fn = TYPES.get(p.feature.type, (None,))[0]
        try:
            src = inspect.getsource(inspect.getmodule(fn)) if fn else None
        except (OSError, TypeError):
            src = None
        if src:
            out.update({n: src for n in names if n.startswith(f"{fid} ")})
    return out
