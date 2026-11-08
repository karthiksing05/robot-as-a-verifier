"""A fake Onshape for offline tests: its geometry is our CadQuery appliance.

A workspace (branch) is a set of spec edits; a version freezes one. Two features stand in for the Part Studio's tree
and map onto spec parameters, so the CAD tools' edits change real geometry the checks can judge. This tests our
plumbing, not Onshape's payloads: the R5 spike and its recorded fixtures cover those.
"""
from __future__ import annotations

import pathlib
import re
import tempfile

import yaml

from rav_cad.generic import bench, save_step
from rav_cad.parametric.build import build
from rav_cad.parametric.spec import Spec

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = Spec.load(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml")
DID, WID, VID = "d" * 24, "a" * 24, "f" * 24
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

# feature id -> (name, type, {parameter id: spec path})
FEATURES = {
    "FbtnBore2": ("button_2 bore", "extrude", {"clearance": "features.button_2.clearance"}),
    "FdoorHandle": ("door handle", "handleStyle", {"style": "features.door.handle_style"}),
}


def _num(expr):
    m = re.match(r"\s*([-\d.]+)\s*mm\s*$", str(expr))
    return float(m.group(1)) if m else expr


class FakeOnshape:
    def __init__(self):
        self.workspaces, self.versions, self.mv, self.calls = {}, {VID: {}}, {}, []
        self.added, self.variables = {}, [{"name": "button_2_clearance", "type": "LENGTH", "expression": "0.15 mm"}]

    def edit(self, ws, edits):
        self.workspaces[ws].update(edits)
        self.mv[ws] += 1

    def _edits(self, ref):
        return self.versions[ref.wvmid] if ref.wvm == "v" else self.workspaces[ref.wvmid]

    def create_branch(self, did, version_id, name, description=""):
        ws = f"{len(self.workspaces) + 1:024x}"
        self.workspaces[ws], self.mv[ws] = dict(self.versions[version_id]), 0
        self.calls.append(("create_branch", version_id))
        return {"id": ws}

    def current_microversion(self, did, workspace_id):
        return f"mv{workspace_id[-4:]}-{self.mv.get(workspace_id, 0)}"

    def get_features(self, ref, **params):
        edits = self._edits(ref)
        feats = []
        for fid, (name, ftype, pmap) in FEATURES.items():
            ps = []
            for pid, path in pmap.items():
                v = edits.get(path, SPEC.get(path))
                ps.append({"btType": "BTMParameterQuantity-147", "parameterId": pid, "expression": f"{v} mm"}
                          if isinstance(v, (int, float)) else {"btType": "BTMParameterEnum-145", "parameterId": pid, "value": v})
            feats.append({"btType": "BTMFeature-134", "featureId": fid, "name": name, "featureType": ftype, "parameters": ps})
        feats += [f for (w, _), f in self.added.items() if w == ref.wvmid]
        return {"features": feats, "featureStates": {f["featureId"]: {"featureStatus": "OK"} for f in feats},
                "serializationVersion": "1.2.3", "sourceMicroversion": f"mv{ref.wvmid[-4:]}-{self.mv.get(ref.wvmid, 0)}"}

    def update_feature(self, ref, feature_id, feature, serialization_version=None, source_microversion=None):
        assert ref.wvm == "w" and serialization_version and source_microversion
        pmap = FEATURES[feature_id][2]
        self.edit(ref.wvmid, {pmap[p["parameterId"]]: _num(p.get("expression", p.get("value"))) for p in feature["parameters"]})
        return {"feature": feature}

    def add_feature(self, ref, feature, serialization_version=None, source_microversion=None):
        fid = f"Fadded{len(self.added) + 1}"
        self.added[(ref.wvmid, fid)] = {**feature, "featureId": fid, "parameters": feature.get("parameters", [])}
        self.mv[ref.wvmid] += 1
        return {"feature": {"featureId": fid}, "featureState": {"featureStatus": "OK"}}

    def delete_feature(self, ref, feature_id):
        self.added.pop((ref.wvmid, feature_id), None)
        self.mv[ref.wvmid] += 1

    def export_step(self, ref, kind="partstudio", **kw):
        self.calls.append(("export_step", ref.wvm, kind))
        with tempfile.TemporaryDirectory() as tmp:
            return save_step(bench.parts(build(SPEC.with_edits(self._edits(ref)))), pathlib.Path(tmp) / "x.step").read_bytes()

    def create_version(self, did, workspace_id, name, description=""):
        vid = f"{len(self.versions) + 1:024x}"
        self.versions[vid] = dict(self.workspaces[workspace_id])
        self.calls.append(("create_version", name))
        return {"id": vid, "name": name}

    def list_parts(self, ref):
        return [{"name": n, "partId": f"P{i}"} for i, n in enumerate(bench.parts(build(SPEC.with_edits(self._edits(ref)))))]

    def export_stl(self, ref, part_id=None, **kw):
        return b"solid " + part_id.encode()

    def shaded_view(self, ref, *a, **kw):
        return PNG

    def get_variables(self, ref):
        return [{"variables": [dict(v) for v in self.variables]}]

    def set_variables(self, ref, variables):
        assert ref.wvm == "w"
        self.variables = variables
        self.mv[ref.wvmid] += 1


def write_tags(path: pathlib.Path, variables: bool = True) -> pathlib.Path:
    d = bench.tags_dict(build(SPEC))
    d["source"] = {"document": f"https://cad.onshape.com/documents/{DID}/w/{WID}", "assembly": "e" * 24,
                   "part_studio": "c" * 24, "tested_version": VID, **({"variables": "b" * 24} if variables else {})}
    path.write_text(yaml.safe_dump(d))
    return path
