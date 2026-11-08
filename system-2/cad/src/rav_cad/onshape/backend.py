"""OnshapeBackend: the fix loop's CadBackend on the team's real Onshape model.

The tested revision (Rev A) is an Onshape version and is never edited. Each fix gets its own branch workspace made
from it; the analyst edits that branch through the CAD tools (mcp_server.py), and a patch points at the branch's
microversion. check() exports the branch as a STEP assembly and runs the generic robot-centred checks against the
tested version; apply() needs an approver, makes sure the branch hasn't moved since the check, creates the new
version (Rev B) and exports STLs of the parts that changed. Merging into main is left to a person in Onshape.

The product's tag file (subjects/<product>/onshape.yaml) names the document and its tabs under `source`:

    source:
      document: https://cad.onshape.com/documents/<did>/w/<wid>     # any link into the document
      assembly: <element id>         # exported for the checks: parts placed at rest
      part_studio: <element id>      # where parts are edited and exported as STL
      variables: <element id>        # optional Variable Studio
      tested_version: <version id>   # Rev A, the version the robot tested
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import Any

from rav_contracts import CADPatch, CadSource

from ..generic import Tags, failures, load_step, run
from ..generic.checks import _changed, as_json
from .client import DocRef, OnshapeClient, decode_fs_value, parse_document_url


CACHE = pathlib.Path(os.environ.get("RAV_CAD_CACHE") or pathlib.Path.home() / ".cache" / "rav-cad" / "onshape")
EXPORT_POLL_S = 1.0          # how often to ask Onshape whether an export is ready (each ask is an API call)


# One part's faces, by name (NAMES is replaced with a JSON array of the names it may have). Read-only.
FACES_FS = """
function(context is Context, queries is map)
{
    var names = NAMES;
    var out = [];
    for (var body in evaluateQuery(context, qAllModifiableSolidBodies()))
    {
        var name = getProperty(context, { "entity" : body, "propertyType" : PropertyType.NAME });
        var wanted = false;
        for (var n in names)
        {
            if (n == name)
                wanted = true;
        }
        if (!wanted)
            continue;
        for (var face in evaluateQuery(context, qOwnedByBody(body, EntityType.FACE)))
        {
            var row = { "id" : transientQueriesToStrings(face), "area" : evArea(context, { "entities" : face }) };
            var surface = evSurfaceDefinition(context, { "face" : face });
            if (surface is Cylinder)
            {
                row["kind"] = "cylinder";
                row["radius"] = surface.radius;
                row["axis"] = surface.coordSystem.zAxis;
                row["origin"] = surface.coordSystem.origin;
            }
            else if (surface is Plane)
            {
                row["kind"] = "plane";
                row["normal"] = surface.normal;
                row["origin"] = surface.origin;
            }
            else
            {
                row["kind"] = "other";
            }
            out = append(out, row);
        }
    }
    return out;
}
"""


@dataclass
class BranchCheck:
    """One check of a branch: what was exported, what changed and what the checks said."""
    microversion: str
    changed: list[str]
    target: str | None
    reasons: list[str]
    results: list[dict]


class OnshapeBackend:
    name = "onshape"

    def __init__(self, tags_path: str | pathlib.Path, client: Any = None, out_dir: str | pathlib.Path | None = None,
                 require_approval: bool = True, cache_dir: str | pathlib.Path | None = None):
        self.tags_path = pathlib.Path(tags_path)
        self.tags = Tags.load(self.tags_path)
        src = self.tags.source
        for key in ("document", "assembly", "part_studio", "tested_version"):
            if not src.get(key) or str(src[key]).startswith("<"):
                raise ValueError(f"{self.tags_path}: source.{key} isn't set; see rav_cad/onshape/backend.py")
        self.doc = parse_document_url(str(src["document"]))
        self.client = client if client is not None else OnshapeClient()
        self.out_dir = pathlib.Path(out_dir) if out_dir else self.tags_path.parent / "onshape_out"
        self.require_approval = require_approval
        self.cache = pathlib.Path(cache_dir) if cache_dir else CACHE     # exports of versions, which never change
        self._before: dict | None = None

    # --- where things are -------------------------------------------------------------------------------------

    def _at(self, wvm: str, wvmid: str, element: str) -> DocRef:
        return DocRef(self.doc.did, wvm, wvmid, self.tags.source[element])

    def tested(self, element: str = "assembly") -> DocRef:
        return self._at("v", self.tags.source["tested_version"], element)

    def branch(self, workspace_id: str, element: str = "part_studio") -> DocRef:
        return self._at("w", workspace_id, element)

    def url(self, workspace_id: str) -> str:
        return f"https://cad.onshape.com/documents/{self.doc.did}/w/{workspace_id}/e/{self.tags.source['part_studio']}"

    def microversion(self, workspace_id: str) -> str:
        # the cheap document call, not the feature tree: the feature-tree endpoint has a tight Onshape rate limit
        return self.client.current_microversion(self.doc.did, workspace_id)

    # --- branches ---------------------------------------------------------------------------------------------

    def open_branch(self, name: str, description: str = "") -> str:
        """A new workspace made from the tested version. The analyst only ever edits this."""
        return self.client.create_branch(self.doc.did, self.tags.source["tested_version"], name, description)["id"]

    def _parts(self, ref: DocRef) -> dict:
        # a version never changes, so its export is kept on disk and shared by every session; a branch is re-exported
        cached = self.cache / f"{ref.did}-{ref.wvmid}-{ref.eid}.step" if ref.wvm == "v" else None
        if cached is not None and cached.exists():
            return self.tags.normalize(load_step(cached))
        data = self.client.export_step(ref, kind="assembly", interval=EXPORT_POLL_S)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_suffix(f".{os.getpid()}.tmp")          # write then rename: parallel sessions never read half
            tmp.write_bytes(data)
            tmp.replace(cached)
            return self.tags.normalize(load_step(cached))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "export.step"
            path.write_bytes(data)
            return self.tags.normalize(load_step(path))

    def before(self) -> dict:
        if self._before is None:
            self._before = self._parts(self.tested())
        return self._before

    def check_branch(self, workspace_id: str, quick: bool = False) -> BranchCheck:
        """Export the branch and judge it against the tested version. Refuses if the branch moved during the export.
        `quick` checks only what the change can affect (the analyst's iterations); the default is the full check."""
        mv = self.microversion(workspace_id)
        after = self._parts(self.branch(workspace_id, "assembly"))
        if self.microversion(workspace_id) != mv:
            return BranchCheck(mv, [], None, ["the branch changed while it was being checked; check it again"], [])
        before = self.before()
        changed = _changed(before, after)
        owners = sorted({o for o in (self.tags.owner(n) for n in changed) if o})
        target = owners[0] if len(owners) == 1 else None
        results = run(after, self.tags, before=before, target=target, quick=quick)
        return BranchCheck(mv, changed, target, failures(results), as_json(results))

    # --- CadBackend -------------------------------------------------------------------------------------------

    def read_params(self) -> dict[str, Any]:
        """Variables of the tested version and each control's parts: the starting point an analyst reads."""
        out: dict[str, Any] = {"rev": "A", "backend": "onshape", "document": str(self.tags.source["document"])}
        if self.tags.source.get("variables"):
            for v in self.client.get_variables(self._at("v", self.tags.source["tested_version"], "variables")):
                for item in v.get("variables", [v]):
                    out[f"variables.{item.get('name')}"] = item.get("expression")
        for c in self.tags.controls.values():
            out[f"controls.{c.id}"] = {"skill": c.skill, "parts": list(c.parts), "reprintable": list(c.reprintable)}
        return out

    def rules(self) -> str:
        t = self.tags
        return "\n".join([
            "Edit only your own Onshape branch; the tested version is never changed.",
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
            return ["an Onshape patch points at its branch (source); make the change in a branch with the CAD tools"]
        if patch.source.document_id != self.doc.did:
            return [f"the patch is for document {patch.source.document_id}, not {self.doc.did}"]
        result = self.check_branch(patch.source.workspace_id)
        if result.microversion != patch.source.microversion_id:
            return ["the branch has changed since this patch was made; check it again and resubmit"]
        return result.reasons

    def apply(self, patch: CADPatch) -> str:
        if self.require_approval and not patch.approved_by:
            raise ValueError("a teammate approves a patch before it is applied and printed (set approved_by)")
        problems = self.check(patch)
        if problems:
            raise ValueError("; ".join(problems))
        ws = patch.source.workspace_id
        version = self.client.create_version(self.doc.did, ws, f"Rev {patch.revision_to}",
                                             f"Fix approved by {patch.approved_by or 'the harness'}")
        result = self.check_branch(ws)
        out = self.out_dir / f"rev_{patch.revision_to}"
        out.mkdir(parents=True, exist_ok=True)
        ref = self._at("v", version["id"], "part_studio")
        by_name = {p.get("name"): p.get("partId") for p in self.client.list_parts(ref)}
        written = []
        for name in result.changed:
            if by_name.get(name):
                (out / f"{name}.stl").write_bytes(self.client.export_stl(ref, part_id=by_name[name]))
                written.append(f"{name}.stl")
        (out / "patch_result.json").write_text(json.dumps({
            "version": {"id": version["id"], "name": version.get("name")}, "url": self.url(ws), "changed": result.changed,
            "stl": written, "checks": result.results, "patch": patch.model_dump(mode="json")}, indent=2))
        return str(out)

    def faces(self, part: str, ref: DocRef | None = None) -> list[dict]:
        """One part's faces (largest first): id for feature queries, kind, area, and its plane or axis, in mm.
        LookupError when the part isn't there or the FeatureScript fails. A version's faces never change, so they're
        kept on disk beside its export; a branch's are read live."""
        ref = ref or self._at("v", self.tags.source["tested_version"], "part_studio")
        cached = self.cache / f"{ref.did}-{ref.wvmid}-{ref.eid}-faces-{part}.json" if ref.wvm == "v" else None
        if cached is not None and cached.exists():
            return json.loads(cached.read_text())
        faces = self._read_faces(part, ref)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(faces))
        return faces

    def _read_faces(self, part: str, ref: DocRef) -> list[dict]:
        names = [part] + [part + s for s in self.tags.ignore_suffixes]
        result = self.client.eval_featurescript(ref, FACES_FS.replace("NAMES", json.dumps(names)))
        errors = [n.get("message") for n in result.get("notices") or [] if n.get("level") == "ERROR"]
        if errors:
            raise LookupError(f"FeatureScript failed: {errors[0]}")
        faces = decode_fs_value(result.get("result")) or []
        if not faces:
            raise LookupError(f"no part named {part} in the Part Studio; list_controls has the names")
        rnd = lambda v: round(v, 4) if isinstance(v, float) else [round(x, 4) for x in v] if isinstance(v, list) else v  # noqa: E731
        return [{k: rnd(v) for k, v in f.items()} for f in sorted(faces, key=lambda f: -float(f.get("area") or 0))]

    def describe(self, control: str, max_faces: int = 12) -> str:
        """What the analyst would otherwise spend its first calls finding out about the failing control, measured on
        the tested version (its branch starts identical): the parts, their boxes, a sliding fit's gap, and the faces of
        the parts it may reprint (ids usable in feature queries on the branch)."""
        from ..parametric.geom import distance
        c = self.tags.controls.get(control)
        if c is None:
            return ""
        parts = self.before()
        lines = [f"Control {c.id}: skill {c.skill}; parts {', '.join(c.parts)}; may reprint {', '.join(c.reprintable) or 'nothing'}"
                 + (f"; it drives {', '.join(c.actuates)}" if c.actuates else "")]
        for name in dict.fromkeys([*c.parts, *c.actuates]):
            if name in parts:
                bb = parts[name].BoundingBox()
                lines.append(f"- {name}: box X {bb.xmin:.2f}..{bb.xmax:.2f}, Y {bb.ymin:.2f}..{bb.ymax:.2f}, Z {bb.zmin:.2f}..{bb.zmax:.2f} mm")
        if c.fit and all(p in parts for p in c.fit):
            lines.append(f"- gap between {c.fit[0]} and {c.fit[1]} at rest: {distance(parts[c.fit[0]], parts[c.fit[1]]):.3f} mm")
        for name in c.reprintable:
            try:
                fs = self.faces(name)
            except LookupError:
                continue
            shown = [f for f in fs if f.get("kind") == "cylinder"] + [f for f in fs if f.get("kind") != "cylinder"]
            lines.append(f"- faces of {name} ({len(fs)}; cylinders first, then largest):")
            lines += [f"    {json.dumps(f)}" for f in shown[:max_faces]]
        return "\n".join(lines)

    def source(self, workspace_id: str, microversion: str) -> CadSource:
        return CadSource(document_id=self.doc.did, workspace_id=workspace_id, microversion_id=microversion,
                         base_version_id=self.tags.source["tested_version"],
                         element_id=self.tags.source["part_studio"], url=self.url(workspace_id))
