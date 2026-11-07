"""rav-cad: the CAD tools the analyst uses to fix the product in Onshape, bound to one branch.

    python -m rav_cad.onshape.mcp_server --tags subjects/appliance/onshape.yaml --workspace <wid> --out <dir> \
        [--target door] [--verify s4]

The server can only write to the branch it was started on; the tested version is never touched. Every edit is kept
as a CadEdit for the patch, and every call is appended to <out>/calls.jsonl (the harness turns those into tool_call
events, since this runs inside the analyst's own process). submit_fix writes <out>/result.json, which the harness
reads back. A fix can only be submitted when check() passed on the branch exactly as it is now.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image

from rav_contracts import CADPatch, CadEdit, Hypothesis, RootCause

from ..parametric.geom import distance
from .backend import BranchCheck, OnshapeBackend

MAX_FEATURES = 120


def _param_value(p: dict) -> Any:
    for key in ("expression", "value"):
        if key in p:
            return p[key]
    if "queries" in p:
        return f"<selection of {len(p['queries'])}>"
    return f"<{p.get('btType', 'parameter')}>"


def summarize(feature: dict, states: dict) -> dict:
    fid = feature.get("featureId")
    return {"id": fid, "name": feature.get("name"), "type": feature.get("featureType"),
            "suppressed": bool(feature.get("suppressed")), "status": (states.get(fid) or {}).get("featureStatus", "OK"),
            "params": {p.get("parameterId"): _param_value(p) for p in feature.get("parameters", [])}}


class CadSession:
    """Everything one analyst run can do to its branch."""

    def __init__(self, backend: OnshapeBackend, workspace: str, out: str | pathlib.Path, target: str | None = None,
                 verify_with: list[str] | None = None):
        self.backend, self.ws, self.target = backend, workspace, target
        self.verify_with = verify_with or []
        self.out = pathlib.Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.edits: list[CadEdit] = []
        self.last_check: BranchCheck | None = None
        self._parts_cache: tuple[str, dict] | None = None

    # -- helpers --

    def log(self, tool: str, args: dict, ok: bool, result: Any) -> None:
        line = {"t": time.time(), "tool": tool, "args": args, "ok": ok, "result": result if isinstance(result, (str, dict, list)) else str(result)}
        with (self.out / "calls.jsonl").open("a") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def ref(self, element: str = "part_studio"):
        return self.backend.branch(self.ws, element)

    def tree(self) -> dict:
        return self.backend.client.get_features(self.ref())

    def feature(self, tree: dict, feature_id: str) -> dict:
        f = next((f for f in tree.get("features", []) if f.get("featureId") == feature_id), None)
        if f is None:
            raise ToolError(f"no feature {feature_id!r}; call get_features for the ids")
        return f

    def status(self, feature_id: str) -> str:
        return ((self.tree().get("featureStates") or {}).get(feature_id) or {}).get("featureStatus", "OK")

    def parts(self) -> dict:
        mv = self.backend.microversion(self.ws)
        if not self._parts_cache or self._parts_cache[0] != mv:
            self._parts_cache = (mv, self.backend._parts(self.ref("assembly")))
        return self._parts_cache[1]

    def write_result(self, data: dict) -> None:
        (self.out / "result.json").write_text(json.dumps(data, indent=2, default=str))

    # -- what the tools do --

    def list_controls(self) -> dict:
        t = self.backend.tags
        return {"target": self.target, "fixed": list(t.fixed), "controls": {
            c.id: {"skill": c.skill, "parts": list(c.parts), "reprintable": list(c.reprintable), "moving": list(c.moving),
                   "motion": c.motion.__dict__ if c.motion else None} for c in t.controls.values()}}

    def get_features(self, name_contains: str | None = None) -> list[dict]:
        tree = self.tree()
        states = tree.get("featureStates") or {}
        out = [summarize(f, states) for f in tree.get("features", [])
               if not name_contains or name_contains.lower() in str(f.get("name", "")).lower()]
        return out[:MAX_FEATURES]

    def get_feature(self, feature_id: str) -> dict:
        return self.feature(self.tree(), feature_id)

    def update_feature(self, feature_id: str, params: dict[str, Any]) -> dict:
        tree = self.tree()
        f = copy.deepcopy(self.feature(tree, feature_id))
        by_id = {p.get("parameterId"): p for p in f.get("parameters", [])}
        unknown = [k for k in params if k not in by_id]
        if unknown:
            raise ToolError(f"{feature_id} has no parameter {', '.join(unknown)}; it has {', '.join(map(str, by_id))}")
        before = {}
        for k, v in params.items():
            p = by_id[k]
            # keep the field the parameter already uses: quantities hold an expression, enums and booleans a value
            key = "expression" if "expression" in p else "value" if "value" in p else ("expression" if isinstance(v, str) else "value")
            before[k] = p.get(key)
            p[key] = v
        self.backend.client.update_feature(self.ref(), feature_id, f, tree.get("serializationVersion"), tree.get("sourceMicroversion"))
        status = self.status(feature_id)
        self.edits.append(CadEdit(op="update_feature", target=feature_id, summary=f"{f.get('name')}: " + ", ".join(
            f"{k} {before[k]!r} -> {params[k]!r}" for k in params)))
        return {"feature": feature_id, "status": status, "note": "" if status == "OK" else "the feature fails to regenerate; fix or revert it"}

    def add_feature(self, definition: dict) -> dict:
        tree = self.tree()
        resp = self.backend.client.add_feature(self.ref(), definition, tree.get("serializationVersion"), tree.get("sourceMicroversion"))
        fid = ((resp or {}).get("feature") or {}).get("featureId") or definition.get("featureId", "?")
        status = ((resp or {}).get("featureState") or {}).get("featureStatus") or self.status(fid)
        self.edits.append(CadEdit(op="add_feature", target=fid, summary=f"added {definition.get('featureType')} '{definition.get('name', '')}'"))
        return {"feature": fid, "status": status}

    def delete_feature(self, feature_id: str) -> dict:
        name = self.feature(self.tree(), feature_id).get("name")
        self.backend.client.delete_feature(self.ref(), feature_id)
        self.edits.append(CadEdit(op="delete_feature", target=feature_id, summary=f"deleted '{name}'"))
        return {"deleted": feature_id}

    def get_variables(self) -> list[dict]:
        if not self.backend.tags.source.get("variables"):
            return []
        rows = self.backend.client.get_variables(self.ref("variables"))
        return [v for r in rows for v in r.get("variables", [r])]

    def set_variable(self, name: str, expression: str) -> dict:
        if not self.backend.tags.source.get("variables"):
            raise ToolError("this product has no Variable Studio; edit features instead")
        current = self.get_variables()
        row = next((v for v in current if v.get("name") == name), None)
        if row is None:
            raise ToolError(f"no variable {name!r}; there are {', '.join(v.get('name', '?') for v in current)}")
        old = row.get("expression")
        updated = [{**v, "expression": expression} if v.get("name") == name else v for v in current]
        self.backend.client.set_variables(self.ref("variables"), [
            {k: v[k] for k in ("name", "type", "expression", "description") if k in v} for v in updated])
        self.edits.append(CadEdit(op="variable", target=name, summary=f"{name}: {old} -> {expression}"))
        return {"variable": name, "from": old, "to": expression}

    def measure_gap(self, part_a: str, part_b: str) -> dict:
        parts = self.parts()
        missing = [p for p in (part_a, part_b) if p not in parts]
        if missing:
            raise ToolError(f"no part {', '.join(missing)}; parts are: {', '.join(sorted(parts))}")
        return {"part_a": part_a, "part_b": part_b, "gap_mm": round(distance(parts[part_a], parts[part_b]), 3)}

    def part_size(self, part: str) -> dict:
        parts = self.parts()
        if part not in parts:
            raise ToolError(f"no part {part}; parts are: {', '.join(sorted(parts))}")
        bb = parts[part].BoundingBox()
        return {"part": part, "size_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
                "min": [round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2)], "max": [round(bb.xmax, 2), round(bb.ymax, 2), round(bb.zmax, 2)]}

    def render(self) -> bytes:
        return self.backend.client.shaded_view(self.ref())

    def check(self) -> dict:
        self.last_check = self.backend.check_branch(self.ws)
        c = self.last_check
        return {"ok": not c.reasons, "reasons": c.reasons, "changed": c.changed, "control": c.target, "microversion": c.microversion}

    def submit_fix(self, root_cause: str, confidence: float, hypotheses: list[dict], evidence: list[str],
                   predicted: str, no_cad_fix: bool = False) -> dict:
        try:
            cause = RootCause(finding=self.target or "?", evidence=evidence, hypotheses=[Hypothesis(**h) for h in hypotheses],
                              root_cause=root_cause, confidence=float(confidence))
        except Exception as e:  # noqa: BLE001 - shown to the model
            raise ToolError(f"the diagnosis doesn't match its schema: {e}") from None
        if no_cad_fix:
            self.write_result({"cause": cause.model_dump(mode="json"), "patch": None})
            return {"submitted": True, "patch": None}
        c = self.last_check
        if c is None or c.reasons:
            raise ToolError("call check() and get it to pass before submitting a fix")
        mv = self.backend.microversion(self.ws)
        if mv != c.microversion:
            raise ToolError("the branch changed after the last check; call check() again")
        patch = CADPatch(file=self.backend.url(self.ws), revision_from="A", revision_to="B", changes=[], backend="onshape",
                         verify_with=self.verify_with, source=self.backend.source(self.ws, mv), edits=self.edits,
                         constraints_checked=[r["name"] for r in c.results if r["ok"]])
        self.write_result({"cause": cause.model_dump(mode="json"), "patch": patch.model_dump(mode="json"),
                           "predicted": predicted, "changed": c.changed})
        return {"submitted": True, "changed": c.changed, "url": self.backend.url(self.ws)}


def build_server(s: CadSession) -> MCPServer:
    mcp = MCPServer("rav-cad", instructions=(
        "CAD tools for fixing the product in Onshape. You work on your own branch; the version the robot tested is "
        "never changed. Look (list_controls, get_features, render, measure), edit (update_feature, add_feature, "
        "delete_feature, set_variable), then check(). Repeat until check() passes, then submit_fix(). If no CAD change "
        "can fix the finding, submit_fix with no_cad_fix=true."))

    def traced(name: str, args: dict, fn):
        try:
            result = fn()
        except ToolError as e:
            s.log(name, args, False, str(e))
            raise
        except Exception as e:  # noqa: BLE001 - Onshape errors go back to the model to read
            s.log(name, args, False, f"{type(e).__name__}: {e}")
            raise ToolError(f"{type(e).__name__}: {e}") from e
        s.log(name, args, True, result if not isinstance(result, (bytes, Image)) else "<image>")
        return result

    @mcp.tool(description="The product's controls: which parts belong to each, which you may reprint, how they move. "
                          "`target` is the control the finding is about.")
    def list_controls() -> dict:
        return traced("list_controls", {}, s.list_controls)

    @mcp.tool(description="The Part Studio's features on your branch: id, name, type, status and parameters. "
                          "Filter by part of the name.")
    def get_features(name_contains: str | None = None) -> list[dict]:
        return traced("get_features", {"name_contains": name_contains}, lambda: s.get_features(name_contains))

    @mcp.tool(description="One feature's full Onshape definition, to read before editing or as a template for add_feature.")
    def get_feature(feature_id: str) -> dict:
        return traced("get_feature", {"feature_id": feature_id}, lambda: s.get_feature(feature_id))

    @mcp.tool(description="Change parameters of an existing feature. Values are Onshape expressions with units, e.g. "
                          "{'depth': '4.5 mm'}. Returns whether the feature still regenerates.")
    def update_feature(feature_id: str, params: dict[str, Any]) -> dict:
        return traced("update_feature", {"feature_id": feature_id, "params": params}, lambda: s.update_feature(feature_id, params))

    @mcp.tool(description="Add a feature (sketch, extrude, fillet, ...) as an Onshape feature definition (BTMFeature JSON). "
                          "Copy the shape of an existing one from get_feature.")
    def add_feature(definition: dict[str, Any]) -> dict:
        return traced("add_feature", {"definition": definition}, lambda: s.add_feature(definition))

    @mcp.tool(description="Delete a feature from your branch.")
    def delete_feature(feature_id: str) -> dict:
        return traced("delete_feature", {"feature_id": feature_id}, lambda: s.delete_feature(feature_id))

    @mcp.tool(description="The Variable Studio's variables (name, type, expression).")
    def get_variables() -> list[dict]:
        return traced("get_variables", {}, s.get_variables)

    @mcp.tool(description="Set one variable's expression, e.g. set_variable('button_2_clearance', '0.4 mm').")
    def set_variable(name: str, expression: str) -> dict:
        return traced("set_variable", {"name": name, "expression": expression}, lambda: s.set_variable(name, expression))

    @mcp.tool(description="The smallest gap in mm between two parts on your branch, at rest (assembly positions).")
    def measure_gap(part_a: str, part_b: str) -> dict:
        return traced("measure_gap", {"part_a": part_a, "part_b": part_b}, lambda: s.measure_gap(part_a, part_b))

    @mcp.tool(description="A part's bounding box on your branch, in mm.")
    def part_size(part: str) -> dict:
        return traced("part_size", {"part": part}, lambda: s.part_size(part))

    @mcp.tool(description="An isometric picture of your branch's Part Studio, to see what you changed.")
    def render() -> Image:
        return traced("render", {}, lambda: Image(data=s.render(), format="png"))

    @mcp.tool(description="Run every robot-centred check on your branch against the tested version: valid printable "
                          "parts, only one control's reprintable parts changed, nothing overlaps, moving parts move "
                          "freely, the fingertip reaches each control and can hook a pull control. Returns the reasons it "
                          "fails, or ok.")
    def check() -> dict:
        return traced("check", {}, s.check)

    @mcp.tool(description="Finish. Needs a passing check() on the branch as it is now, unless no_cad_fix is true (the "
                          "fault is perception, the arm, wiring or firmware). hypotheses: [{cause, p, check?, ruled_out?}].")
    def submit_fix(root_cause: str, confidence: float, hypotheses: list[dict[str, Any]], evidence: list[str],
                   predicted: str, no_cad_fix: bool = False) -> dict:
        args = {"root_cause": root_cause, "confidence": confidence, "no_cad_fix": no_cad_fix}
        return traced("submit_fix", args, lambda: s.submit_fix(root_cause, confidence, hypotheses, evidence, predicted, no_cad_fix))

    return mcp


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav-cad-mcp", description=__doc__.splitlines()[0])
    ap.add_argument("--tags", required=True, help="the product's onshape.yaml")
    ap.add_argument("--workspace", required=True, help="the branch workspace id to edit")
    ap.add_argument("--out", required=True, help="where calls.jsonl and result.json go")
    ap.add_argument("--target", default=None, help="the control the finding is about")
    ap.add_argument("--verify", nargs="*", default=[], help="step ids to rerun on the new revision")
    args = ap.parse_args(argv)
    session = CadSession(OnshapeBackend(args.tags), args.workspace, args.out, args.target, args.verify)
    build_server(session).run("stdio")


if __name__ == "__main__":
    main()
