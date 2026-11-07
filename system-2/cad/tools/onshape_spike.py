"""R5 spike (step 0, a gate): can we read and edit the real Onshape model through the API?

Run on a COPY of the appliance document only. All writes go to a new branch workspace made from a version, so
the original workspace is never touched.

    cd system-2 && .venv/bin/python cad/tools/onshape_spike.py                 # uses ONSHAPE_DEV_DOCUMENT_URL
    .venv/bin/python cad/tools/onshape_spike.py https://cad.onshape.com/documents/<did>/w/<wid>/e/<eid>

Steps: read the feature tree and mates; create a branch from a version; set a variable; update one feature
parameter; add a small feature; evaluate a FeatureScript distance; get a shaded view; export STEP and glTF;
create a version. It prints what worked and failed and records every call (auth stripped) under
tests/fixtures/onshape/spike/. Exported files go to tests/fixtures/onshape/spike_outputs/.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import pathlib
import sys
import traceback
from typing import Any, Callable

from rav_cad.onshape.client import (DocRef, FixtureRecorder, OnshapeClient, OnshapeError, decode_fs_value,
                                    parse_document_url)
from rav_cad.onshape.settings import OnshapeSettingsError, load_settings

SYSTEM2 = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = SYSTEM2 / "tests/fixtures/onshape"
PROBE_NAME = "rav_spike_probe"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

DISTANCE_FS = """
function(context is Context, queries is map)
{
    var bodies = evaluateQuery(context, qAllModifiableSolidBodies());
    if (size(bodies) < 2)
        return { "bodies" : size(bodies) };
    return { "bodies" : size(bodies),
             "distance" : evDistance(context, { "side0" : bodies[0], "side1" : bodies[1] }).distance };
}
"""


class Spike:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []
        self.state: dict[str, Any] = {}

    def step(self, name: str, fn: Callable[[], str | None], needs: tuple[str, ...] = ()) -> None:
        missing = [k for k in needs if k not in self.state]
        if missing:
            self.results.append((name, False, f"skipped: needs {', '.join(missing)}"))
            print(f"  -  {name}: skipped (needs {', '.join(missing)})")
            return
        try:
            detail = fn() or ""
            self.results.append((name, True, detail))
            print(f"  OK {name}{': ' + detail if detail else ''}")
        except OnshapeError as e:
            self.results.append((name, False, str(e)[:300]))
            print(f"  FAIL {name}: {str(e)[:300]}")
        except Exception as e:  # noqa: BLE001 - a spike reports everything and carries on
            self.results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=2)


def _quantity_params(feature: dict) -> list[dict]:
    return [p for p in feature.get("parameters", []) if p.get("btType") == "BTMParameterQuantity-147"]


def _find_feature(features: list[dict], feature_id: str | None, pred: Callable[[dict], bool]) -> dict | None:
    for f in features:
        if (feature_id and f.get("featureId") == feature_id) or (not feature_id and pred(f)):
            return f
    return None


def _probe_feature(template: dict | None, expression: str) -> dict:
    """An `assignVariable` feature: cloned from an existing one when we have it (safer parameter layout)."""
    if template:
        f = copy.deepcopy(template)
        for k in ("featureId", "nodeId"):
            f.pop(k, None)
        for p in f.get("parameters", []):
            p.pop("nodeId", None)
            if p.get("parameterId") == "name":
                p["value"] = PROBE_NAME
            elif p.get("parameterId") == "variableType":
                p["value"] = "LENGTH"
            elif p.get("parameterId") == "lengthValue":
                p["expression"] = expression
        f["name"] = PROBE_NAME
        return f
    return {"btType": "BTMFeature-134", "featureType": "assignVariable", "name": PROBE_NAME, "parameters": [
        {"btType": "BTMParameterEnum-145", "parameterId": "variableType", "enumName": "VariableType",
         "value": "LENGTH"},
        {"btType": "BTMParameterString-149", "parameterId": "name", "value": PROBE_NAME},
        {"btType": "BTMParameterQuantity-147", "parameterId": "lengthValue", "expression": expression},
    ]}


# --- scratch mode: a throwaway document, so the spike needs only API keys -------------------------------------

TOP_PLANE = "JDC"   # deterministic id of the Top plane in every Part Studio


def _seed_features(height_var: str) -> tuple[dict, dict, Callable[[str], dict]]:
    """A length variable, a sketch with two separate circles, and an extrude of both by the variable: two parts."""
    var = _probe_feature(None, "10 mm")
    for p in var["parameters"]:
        if p.get("parameterId") == "name":
            p["value"] = height_var
    var["name"] = height_var

    def circle(eid: str, x: float) -> dict:
        return {"btType": "BTMSketchCurve-4", "entityId": eid, "centerId": f"{eid}.center",
                "geometry": {"btType": "BTCurveGeometryCircle-115", "radius": 0.01, "xCenter": x, "yCenter": 0.0,
                             "xDir": 1.0, "yDir": 0.0, "clockwise": False}}
    sketch = {"btType": "BTMSketch-151", "featureType": "newSketch", "name": "rav sketch", "constraints": [],
              "parameters": [{"btType": "BTMParameterQueryList-148", "parameterId": "sketchPlane",
                              "queries": [{"btType": "BTMIndividualQuery-138", "deterministicIds": [TOP_PLANE]}]}],
              "entities": [circle("c1", 0.0), circle("c2", 0.03)]}

    def extrude(sketch_id: str) -> dict:
        return {"btType": "BTMFeature-134", "featureType": "extrude", "name": "rav extrude", "parameters": [
            {"btType": "BTMParameterEnum-145", "parameterId": "bodyType", "enumName": "ExtendedToolBodyType", "value": "SOLID"},
            {"btType": "BTMParameterEnum-145", "parameterId": "operationType", "enumName": "NewBodyOperationType", "value": "NEW"},
            {"btType": "BTMParameterQueryList-148", "parameterId": "entities",
             "queries": [{"btType": "BTMIndividualSketchRegionQuery-140", "featureId": sketch_id}]},
            {"btType": "BTMParameterEnum-145", "parameterId": "endBound", "enumName": "BoundingType", "value": "BLIND"},
            {"btType": "BTMParameterQuantity-147", "parameterId": "depth", "expression": f"#{height_var}"}]}
    return var, sketch, extrude


def create_scratch(c: OnshapeClient, s: Spike, stamp: str, args: argparse.Namespace) -> str | None:
    """Create a private throwaway document, seed two parts, put them in its Assembly; return its Part Studio URL."""
    def create() -> str:
        # free Onshape accounts can only create public documents; it holds two plain cylinders and is trashed after
        d = c.post_json("documents", {"name": f"rav spike scratch {stamp}", "isPublic": args.public,
                                      "description": "Throwaway document made by the R5 spike; safe to delete"},
                        label="create_document")
        s.state["scratch_did"], s.state["scratch_wid"] = d["id"], d["defaultWorkspace"]["id"]
        els = c.list_elements(DocRef(d["id"], "w", d["defaultWorkspace"]["id"]))
        ps = next(e for e in els if e.get("elementType") == "PARTSTUDIO")
        s.state["scratch_ps"] = ps["id"]
        asm = next((e for e in els if e.get("elementType") == "ASSEMBLY"), None)
        if asm:
            s.state["scratch_asm"] = asm["id"]
        return f"document {d['id']} ({', '.join(e.get('elementType', '?') for e in els)})"

    def seed() -> str:
        ref = DocRef(s.state["scratch_did"], "w", s.state["scratch_wid"], s.state["scratch_ps"])
        var, sketch, extrude = _seed_features("rav_height")
        out = []
        for feature in (var, sketch):
            ft = c.get_features(ref)
            r = c.add_feature(ref, feature, ft.get("serializationVersion"), ft.get("sourceMicroversion"))
            out.append(f"{feature['name']}: {r.get('featureState', {}).get('featureStatus')}")
            if feature is sketch:
                s.state["sketch_id"] = r["feature"]["featureId"]
        ft = c.get_features(ref)
        r = c.add_feature(ref, extrude(s.state["sketch_id"]), ft.get("serializationVersion"), ft.get("sourceMicroversion"))
        out.append(f"rav extrude: {r.get('featureState', {}).get('featureStatus')}")
        parts = c.list_parts(ref)
        s.state["scratch_parts"] = [p.get("name") for p in parts]
        return "; ".join(out) + f"; parts: {', '.join(s.state['scratch_parts'])}"

    def place() -> str:
        did, wid = s.state["scratch_did"], s.state["scratch_wid"]
        c.post_json(f"assemblies/d/{did}/w/{wid}/e/{s.state['scratch_asm']}/instances",
                    {"documentId": did, "elementId": s.state["scratch_ps"], "isWholePartStudio": True,
                     "includePartTypes": ["PARTS"]}, label="insert_instance")
        d = c.assembly_definition(DocRef(did, "w", wid, s.state["scratch_asm"]))
        return f"{len(d.get('rootAssembly', {}).get('instances', []))} instances in the Assembly"

    def base_version() -> str:
        # a new document already has an empty "Start" version; the branch has to start from the seeded parts
        v = c.create_version(s.state["scratch_did"], s.state["scratch_wid"], f"rav spike base {stamp}", "seeded parts")
        args.version_id = v["id"]
        return f"version {v['id']}"

    s.step("create a scratch document", create)
    s.step("add features: variable, sketch, extrude", seed, needs=("scratch_ps",))
    s.step("place the parts in the Assembly", place, needs=("scratch_asm", "scratch_parts"))
    s.step("version the seeded document", base_version, needs=("scratch_parts",))
    if "scratch_ps" not in s.state:
        return None
    return f"https://cad.onshape.com/documents/{s.state['scratch_did']}/w/{s.state['scratch_wid']}/e/{s.state['scratch_ps']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("document_url", nargs="?", help="Part Studio URL (default: ONSHAPE_DEV_DOCUMENT_URL)")
    ap.add_argument("--version-id", help="branch from this version (default: newest, or a new one)")
    ap.add_argument("--variable", metavar="NAME=EXPR",
                    help="variable to set, e.g. 'button_clearance=0.4 mm' (default: rewrite the first one as is)")
    ap.add_argument("--update", metavar="FEATURE_ID:PARAM_ID=EXPR",
                    help="feature parameter to update (default: first length parameter, rewritten as is)")
    ap.add_argument("--keep-probe", action="store_true", help="don't delete the added probe feature")
    ap.add_argument("--scratch", action="store_true",
                    help="make a throwaway document with two seeded parts instead of using one (needs only the keys)")
    ap.add_argument("--keep", action="store_true", help="with --scratch: leave the document instead of trashing it")
    ap.add_argument("--public", action="store_true",
                    help="with --scratch: make the document public (free Onshape accounts can't create private ones)")
    ap.add_argument("--fixtures", type=pathlib.Path, default=FIXTURES / "spike")
    ap.add_argument("--out", type=pathlib.Path, default=FIXTURES / "spike_outputs")
    args = ap.parse_args(argv)

    try:
        settings = load_settings()
    except OnshapeSettingsError as e:
        print(f"Onshape keys missing: {e}\nFill in the repo-root .env (see .env.example), then run this again.")
        return 2
    url = None if args.scratch else (args.document_url or settings.dev_document_url)
    if not url and not args.scratch:
        print("No document: pass a Part Studio URL, set ONSHAPE_DEV_DOCUMENT_URL in the repo-root .env, "
              "or use --scratch to make a throwaway one.")
        return 2

    recorder = FixtureRecorder(args.fixtures, redact=[settings.access_key, settings.secret_key])
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    s = Spike()

    with OnshapeClient(settings, recorder=recorder) as c:
        try:
            return _run(c, s, args, url, stamp, recorder)
        finally:
            if args.scratch and "scratch_did" in s.state and not args.keep:
                try:
                    c.request("DELETE", f"documents/{s.state['scratch_did']}", label="delete_document")
                    print(f"\nScratch document {s.state['scratch_did']} moved to the trash.")
                except Exception as e:  # noqa: BLE001
                    print(f"\nCouldn't trash scratch document {s.state['scratch_did']}: {e}. Delete it in Onshape.")


def _run(c: OnshapeClient, s: Spike, args: argparse.Namespace, url: str | None, stamp: str, recorder: FixtureRecorder) -> int:
    if args.scratch:
        print("Scratch mode: making a throwaway document")
        url = create_scratch(c, s, stamp, args)
        if not url:
            return _report(s, recorder, args)
    src = parse_document_url(url)
    if src.wvm != "w" or not src.eid:
        print("Use a workspace URL that opens a Part Studio: .../documents/<did>/w/<wid>/e/<eid>")
        return 2
    print(f"Onshape spike on document {src.did} (element {src.eid}), fixtures -> {args.fixtures}")
    # --- reads on the original workspace ---
    def read_elements() -> str:
        els = c.list_elements(DocRef(src.did, src.wvm, src.wvmid))
        s.state["elements"] = els
        asm = [e for e in els if e.get("elementType") == "ASSEMBLY"]
        vs = [e for e in els if e.get("elementType") == "VARIABLESTUDIO"]
        if asm:
            s.state["assembly_eid"] = asm[0]["id"]
        if vs:
            s.state["varstudio_eid"] = vs[0]["id"]
        return ", ".join(f"{e.get('elementType')}:{e.get('name')}" for e in els)

    def read_features() -> str:
        ft = c.get_features(src)
        s.state["features_src"] = ft
        n = len(ft.get("features", []))
        return (f"{n} features, serializationVersion={ft.get('serializationVersion')}, "
                f"sourceMicroversion={ft.get('sourceMicroversion')}")

    def read_mates() -> str:
        ref = src.with_element(s.state["assembly_eid"])
        d = c.assembly_definition(ref)
        mates = c.mate_features(ref)
        kinds = sorted({m.get("featureType", "?") for m in mates})
        n_inst = len(d.get("rootAssembly", {}).get("instances", []))
        return f"{n_inst} instances, {len(mates)} mate features ({', '.join(kinds)})"

    s.step("list elements", read_elements)
    s.step("read feature tree", read_features)
    s.step("read assembly + mates", read_mates, needs=("assembly_eid",))

    # --- branch from a version ---
    def pick_version() -> str:
        if args.version_id:
            s.state["version_id"] = args.version_id
            return f"given {args.version_id}"
        versions = c.list_versions(src.did)
        if versions:
            v = max(versions, key=lambda v: v.get("createdAt", ""))
            s.state["version_id"] = v["id"]
            return f"{len(versions)} versions, newest '{v.get('name')}' {v['id']}"
        v = c.create_version(src.did, src.wvmid, f"rav spike base {stamp}")
        s.state["version_id"] = v["id"]
        return f"no versions; created base version {v['id']}"

    def branch() -> str:
        ws = c.create_branch(src.did, s.state["version_id"], f"rav-spike-{stamp}",
                             "R5 spike branch (safe to delete)")
        s.state["branch"] = src.with_workspace(ws["id"])
        ft = c.get_features(s.state["branch"])
        s.state["features"] = ft
        return f"workspace {ws['id']} ({len(ft.get('features', []))} features)"

    s.step("list/create version", pick_version)
    s.step("create branch from version", branch, needs=("version_id",))

    def fresh() -> dict:
        ft = c.get_features(s.state["branch"])
        s.state["features"] = ft
        return ft

    # --- set a variable ---
    def set_variable() -> str:
        name, _, expr = (args.variable or "").partition("=")
        b: DocRef = s.state["branch"]
        if "varstudio_eid" in s.state:
            ref = b.with_element(s.state["varstudio_eid"])
            current = c.get_variables(ref)
            table = (current[0].get("variables", []) if current and isinstance(current[0], dict)
                     and "variables" in current[0] else current)
            vars_ = [{k: v[k] for k in ("name", "type", "expression", "description") if k in v} for v in table]
            if not vars_ and not name:
                raise RuntimeError("Variable Studio is empty; pass --variable NAME=EXPR")
            target = next((v for v in vars_ if v["name"] == name), None) if name else vars_[0]
            if target is None:
                target = {"name": name, "type": "LENGTH", "expression": expr}
                vars_.append(target)
            if expr:
                target["expression"] = expr.strip()
            c.set_variables(ref, vars_)
            return f"Variable Studio: {target['name']} = {target['expression']}"
        ft = fresh()
        var_feats = [f for f in ft.get("features", []) if f.get("featureType") == "assignVariable"]

        def var_name(f: dict) -> str:
            return next((p.get("value") for p in f.get("parameters", []) if p.get("parameterId") == "name"), "")
        f = next((f for f in var_feats if var_name(f) == name), None) if name else (var_feats or [None])[0]
        if f is None:
            raise RuntimeError("no Variable Studio and no matching variable feature; pass --variable NAME=EXPR")
        f = copy.deepcopy(f)
        q = next((p for p in _quantity_params(f) if p.get("expression")), None)
        if q is None:
            raise RuntimeError(f"variable {var_name(f)} has no expression parameter")
        if expr:
            q["expression"] = expr.strip()
        r = c.update_feature(b, f["featureId"], f, ft.get("serializationVersion"), ft.get("sourceMicroversion"))
        return (f"variable feature {var_name(f)} = {q['expression']} -> "
                f"{r.get('featureState', {}).get('featureStatus')}")

    s.step("set a variable", set_variable, needs=("branch",))

    # --- update one feature parameter ---
    def update_param() -> str:
        ft = fresh()
        fid = pid = expr = None
        if args.update:
            head, _, expr = args.update.partition("=")
            fid, _, pid = head.partition(":")
        f = _find_feature(ft.get("features", []), fid,
                          lambda f: f.get("featureType") != "assignVariable" and any(
                              p.get("expression") for p in _quantity_params(f)))
        if f is None:
            raise RuntimeError("no feature with a length/quantity parameter found; pass --update")
        f = copy.deepcopy(f)
        q = next((p for p in _quantity_params(f) if (p.get("parameterId") == pid if pid else p.get("expression"))),
                 None)
        if q is None:
            raise RuntimeError(f"parameter {pid} not found on {f.get('name')}")
        old = q.get("expression")
        q["expression"] = expr.strip() if expr else old
        r = c.update_feature(s.state["branch"], f["featureId"], f, ft.get("serializationVersion"),
                             ft.get("sourceMicroversion"))
        status = r.get("featureState", {}).get("featureStatus")
        return f"{f.get('name')}.{q.get('parameterId')}: {old} -> {q['expression']} ({status})"

    s.step("update a feature parameter", update_param, needs=("branch",))

    # --- add a small feature (a variable), then delete it unless --keep-probe ---
    def add_probe() -> str:
        ft = fresh()
        template = next((f for f in ft.get("features", []) if f.get("featureType") == "assignVariable"), None)
        r = c.add_feature(s.state["branch"], _probe_feature(template, "1 mm"), ft.get("serializationVersion"),
                          ft.get("sourceMicroversion"))
        s.state["probe_id"] = r["feature"]["featureId"]
        return f"{PROBE_NAME} {s.state['probe_id']} ({r.get('featureState', {}).get('featureStatus')})"

    def delete_probe() -> str:
        c.delete_feature(s.state["branch"], s.state["probe_id"])
        return f"deleted {s.state['probe_id']}"

    s.step("add a small feature", add_probe, needs=("branch",))
    if not args.keep_probe:
        s.step("delete the feature", delete_probe, needs=("probe_id",))

    # --- measure, look, export ---
    def featurescript() -> str:
        r = c.eval_featurescript(s.state["branch"], DISTANCE_FS)
        val = decode_fs_value(r.get("result"))
        if r.get("notices"):
            print(f"     notices: {r['notices'][:3]}")
        return f"{val} (lengths in mm)"

    def shaded() -> str:
        png = c.shaded_view(s.state["branch"])
        (args.out / "shaded_view.png").write_bytes(png)
        return f"{len(png)} bytes, png={png.startswith(PNG_MAGIC)}"

    def step_export() -> str:
        data = c.export_step(s.state["branch"])
        (args.out / "branch.step").write_bytes(data)
        return f"{len(data)} bytes, header={data[:13]!r}"

    def gltf_export() -> str:
        data = c.export_gltf(s.state["branch"])
        (args.out / "branch.gltf").write_bytes(data)
        return f"{len(data)} bytes"

    s.step("evaluate FeatureScript distance", featurescript, needs=("branch",))
    s.step("shaded view PNG", shaded, needs=("branch",))
    s.step("export STEP (translation)", step_export, needs=("branch",))
    s.step("export glTF", gltf_export, needs=("branch",))

    def make_version() -> str:
        v = c.create_version(src.did, s.state["branch"].wvmid, f"rav spike {stamp}",
                             "R5 spike: edits made through the API")
        return f"version {v['id']} '{v.get('name')}'"

    s.step("create a version on the branch", make_version, needs=("branch",))

    # --- what the backend relies on: the Assembly as a STEP of named parts, read by our loader ---
    def assembly_step() -> str:
        from rav_cad.generic import load_step
        ref = s.state["branch"].with_element(s.state["assembly_eid"])
        data = c.export_step(ref, kind="assembly")
        path = args.out / "assembly.step"
        path.write_bytes(data)
        parts = load_step(path)
        sizes = {n: [round(v, 1) for v in (sh.BoundingBox().xlen, sh.BoundingBox().ylen, sh.BoundingBox().zlen)]
                 for n, sh in parts.items()}
        return f"{len(parts)} named parts: {sizes}"

    s.step("export the Assembly as STEP and load its parts", assembly_step, needs=("branch", "assembly_eid"))

    return _report(s, recorder, args)


def _report(s: Spike, recorder: FixtureRecorder, args: argparse.Namespace) -> int:
    ok = sum(1 for _, good, _ in s.results if good)
    print(f"\n{ok}/{len(s.results)} steps worked. {recorder.count} calls recorded in {args.fixtures}")
    for name, good, detail in s.results:
        if not good:
            print(f"  failed: {name}: {detail}")
    return 0 if ok == len(s.results) else 1


if __name__ == "__main__":
    sys.exit(main())
