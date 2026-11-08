"""The CAD step's inputs: replaying a recorded run into an analyst, the centrifuge's simulated run, the sliding hook
check and the list_faces tool. No network."""
import json
import pathlib
import shutil
import sys

import pytest

from rav_cad import ParamsBackend
from rav_harness.analyst import rule_analyst
from rav_harness.analyze import analyze_run
from rav_harness.runlog import read_events

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "fixtures/sample_run/sample-revA/events.jsonl"


def test_analyze_replays_each_finding_with_its_run(tmp_path):
    seen = []

    def analyst(ctx):
        seen.append((ctx.finding.target, sorted(o.verdict.target for o in ctx.outcomes), ctx.tracer.stage))
        return rule_analyst(ctx)

    cad = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path))
    out = analyze_run(SAMPLE, analyst, cad, log_root=tmp_path / "runs")
    rows = json.loads(out.read_text())
    assert [r["finding"]["target"] for r in rows] == ["button_2", "door"]
    assert seen[0][1] == ["button_1", "button_2", "button_3", "display", "door"] and seen[0][2] == "ANALYZE"
    assert rows[0]["patch"]["changes"][0]["to_value"] == 0.4
    assert cad.read_params()["button_clearance"][1] == 0.15                     # nothing is applied
    types = [e.type for e in read_events(out.parent / "events.jsonl")]
    assert types.count("root_cause") == 2 and types.count("patch_proposed") == 2 and "patch_applied" not in types


def test_analyze_can_take_one_finding(tmp_path):
    cad = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path))
    rows = json.loads(analyze_run(SAMPLE, rule_analyst, cad, log_root=tmp_path, only=["door"]).read_text())
    assert [r["finding"]["target"] for r in rows] == ["door"]


# --- the centrifuge's simulated run: realistic inputs, and nothing the robot couldn't know ----------------------

@pytest.fixture(scope="module")
def centrifuge_run(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "subjects/centrifuge"))
    import simulated_run
    return simulated_run.main(tmp_path_factory.mktemp("sim"))


def test_the_simulated_run_goes_through_the_harness(centrifuge_run):
    events = read_events(centrifuge_run)
    findings = [e.payload for e in events if e.type == "finding"]
    assert sorted(f["target"] for f in findings) == ["lid", "stop", "well_A"]
    assert {e.payload["verdict"]["target"] for e in events if e.type == "step_finished"} == {
        "power", "lid", "well_A", "start", "stop", "time", "dial"}
    report = json.loads((centrifuge_run.parent / "report.json").read_text())
    assert report["reward"]["value"] == pytest.approx(4 / 7, abs=0.01)


def test_the_simulated_findings_say_only_what_the_robot_measured(centrifuge_run):
    """A guard against leaking the answers: no causes, dimensions of parts, or revisions in what the analyst reads."""
    import re
    text = json.dumps([e.payload for e in read_events(centrifuge_run)]).lower()
    for word in ("clearance", "bore", "bezel", "lip", "overhang", "rev b", "revb", "15.6", "16.8", "0.15", "0.40",
                 "pinch tab", "insert"):
        assert not re.search(rf"(?<![a-z0-9_.]){re.escape(word)}(?![a-z0-9_])", text), word


# --- the sliding hook, on simple shapes ---------------------------------------------------------------------------

cq = pytest.importorskip("cadquery")


def _lid_tags(probe=None):
    from rav_cad.generic import Tags
    lid = {"skill": "pull", "parts": ["lid", "handle"], "reprintable": ["handle"], "moving": ["lid", "handle"],
           "slide_in": True, "contact": [60, 0, 97 + 1 + (probe or 12) / 2], "approach": [-1, 0, 0], "pull": [0, 0, 1]}
    if probe:
        lid["probe_d"] = probe
    return Tags.from_dict({"controls": {"lid": lid}})


def _shapes(hook: bool):
    box = lambda x0, x1, z0, z1: cq.Solid.makeBox(x1 - x0, 18, z1 - z0, pnt=cq.Vector(x0, -9, z0))   # noqa: E731
    handle = box(9, 20, 97, 111)
    if hook:
        handle = handle.fuse(box(20, 30, 107, 109.2)).clean()        # a lip 10 mm forward with 10 mm clear under it
    return {"lid": box(-50, 20, 94, 97), "handle": handle}


def _verdict(results):
    return {r.name.split(": ", 1)[1]: r.ok for r in results if r.name.startswith("lid: ")}


def test_a_sliding_fingertip_lifts_nothing_off_a_plain_tab():
    from rav_cad.generic import run
    v = _verdict(run(_shapes(hook=False), _lid_tags()))
    assert v == {"fingertip reaches the handle": True, "opens with a hooked fingertip": False}


def test_a_hook_lip_catches_a_probe_that_fits_under_it():
    from rav_cad.generic import run
    v = _verdict(run(_shapes(hook=True), _lid_tags(probe=8)))
    assert v == {"8 mm hook reaches the handle": True, "opens with a hooked 8 mm hook": True}


def test_a_12_mm_fingertip_cant_get_under_a_10_mm_lip():
    from rav_cad.generic import run
    assert _verdict(run(_shapes(hook=True), _lid_tags()))["opens with a hooked fingertip"] is False


# --- list_faces ----------------------------------------------------------------------------------------------------

def test_list_faces_matches_revision_suffixes_and_reports_errors(tmp_path):
    pytest.importorskip("mcp")
    from rav_cad.generic.tags import Tags
    from rav_cad.onshape.backend import OnshapeBackend
    from rav_cad.onshape.client import DocRef
    from rav_cad.onshape.mcp_server import CadSession, ToolError

    class Client:
        def __init__(self, result):
            self.result, self.scripts = result, []

        def eval_featurescript(self, ref, script):
            self.scripts.append(script)
            return self.result

    def backend(result):
        b = OnshapeBackend.__new__(OnshapeBackend)
        b.client, b.doc = Client(result), DocRef("d" * 24, "w", "a" * 24)
        b.tags = Tags(controls={}, ignore_suffixes=("_revA", "_revB"), source={"part_studio": "e" * 24, "tested_version": "f" * 24})
        return b

    faces = [{"id": "KF+o", "kind": "cylinder", "radius": 5.15, "area": 291.2, "axis": [0.7071, 0.0, 0.7071]},
             {"id": "KFWo", "kind": "plane", "area": 400.0, "normal": [0.7071, 0.0, 0.7071]}]
    b = backend({"result": faces, "notices": []})
    out = CadSession(b, "a" * 24, tmp_path).list_faces("bezel_stop")
    assert '["bezel_stop", "bezel_stop_revA", "bezel_stop_revB"]' in b.client.scripts[0]
    assert [f["id"] for f in out["list"]] == ["KFWo", "KF+o"]                   # largest first
    with pytest.raises(ToolError, match="no part named"):
        CadSession(backend({"result": [], "notices": []}), "a" * 24, tmp_path).list_faces("nope")
    with pytest.raises(ToolError, match="FeatureScript failed"):
        CadSession(backend({"notices": [{"level": "ERROR", "message": "parse"}]}), "a" * 24, tmp_path).list_faces("x")
