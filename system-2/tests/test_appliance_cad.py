"""The CAD loop on the authored sim appliances: tags from the device file, the fit model against every authored travel,
a patched device for the sim, matching the robot's controls to the CAD's, and fix_run with a scripted analyst. Offline,
no model. Needs the appliances built (python system-1/sim/tools/build.py); skipped otherwise."""
import json
import math
import pathlib

import pytest

cq = pytest.importorskip("cadquery")
yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.cad

from rav_cad.appliance import cad_parts, derived_params, patched_device, tags_dict  # noqa: E402
from rav_cad.generic import Tags, failures, run  # noqa: E402
from rav_contracts import CADPatch, RootCause  # noqa: E402
from rav_harness.match import register  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
APPLIANCES = REPO / "appliances"
BINDS = {"interval-timer": ("button_1", "bezel_min"), "label-printer": ("button_1", "bezel_feed"),
         "wall-thermostat": ("button_2", "bezel_down")}


def built(name):
    if not (APPLIANCES / name / "build" / "revA.step").is_file():
        pytest.skip(f"{name} isn't built: python system-1/sim/tools/build.py")
    return APPLIANCES / name


def authored_params(cfg, rev):
    out = {}
    for fault, opts in cfg["faults"].items():
        out.update(opts[cfg["revs"][rev][fault]].get("params") or {})
    return out


@pytest.mark.parametrize("name", sorted(BINDS))
def test_the_fit_model_gives_every_authored_travel(name):
    """Each sliding button's travel from its geometry equals what the device file says, in Rev A and in Rev B."""
    d = built(name)
    cfg = yaml.safe_load((d / "device.yaml").read_text())
    for rev in ("A", "B"):
        derived = derived_params(cfg, rev, cad_parts(d, rev))
        assert derived, "every bind fault drives a $travel"
        want = authored_params(cfg, rev)
        assert {k: v["value"] for k, v in derived.items()} == {k: want[k] for k in derived}


@pytest.mark.parametrize("name", ["interval-timer", "wall-thermostat"])
def test_tags_fail_rev_a_on_its_bind_and_pass_rev_b(name):
    d = built(name)
    control, bezel = BINDS[name]
    tags = Tags.from_dict(tags_dict(d, "A"))
    assert bezel in tags.controls[control].reprintable and "housing" in tags.fixed
    a = failures(run(tags.normalize(cad_parts(d, "A")), tags))
    assert len(a) == 1 and a[0].startswith(f"{control}: sliding clearance")
    assert failures(run(tags.normalize(cad_parts(d, "B")), tags)) == []


def test_a_patched_device_swaps_the_part_and_derives_its_travel(tmp_path):
    d = built("interval-timer")
    fixed_bezel = cad_parts(d, "B")["bezel_min_revB"]
    out = patched_device(d, "A", {"bezel_min": fixed_bezel}, tmp_path / "dev")
    assert out["travel"] == {"min_travel": {"from": 0.1, "to": 0.3, "clearance_from": 0.1, "clearance_to": 0.6}}
    cfg = yaml.safe_load(pathlib.Path(out["device"]).read_text())
    assert cfg["params"] == {"min_travel": 0.3} and cfg["revs"] == yaml.safe_load((d / "device.yaml").read_text())["revs"]
    meshes = tmp_path / "dev" / "build" / "meshes_revA"
    entry = json.loads((meshes / "manifest.json").read_text())["bezel_min_revA"]
    assert not meshes.is_symlink() and entry["volume"] == pytest.approx(fixed_bezel.Volume())
    assert (tmp_path / "dev" / "build" / "meshes_revB").is_symlink()
    assert (tmp_path / "dev" / "manual.md").is_file() and (tmp_path / "dev" / "verify.yaml").is_file()
    original = json.loads((d / "build" / "meshes_revA" / "manifest.json").read_text())["bezel_min_revA"]
    assert original["volume"] != pytest.approx(fixed_bezel.Volume())   # the authored device is untouched


def _scene_from(tags, yaw_deg, shift, noise=0.0, extra=()):
    a = math.radians(yaw_deg)
    R = [[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]
    rot = lambda v: [sum(R[i][k] * v[k] for k in range(3)) for i in range(3)]  # noqa: E731
    out = []
    for k, (cid, c) in enumerate(tags["controls"].items()):
        p = [x + s + noise * ((-1) ** k) for x, s in zip(rot(c["contact"]), shift)]
        out.append({"id": f"seen_{k}", "kind": "button", "pos_mm": p, "normal": rot([-v for v in c["approach"]]), "truth": cid})
    return out + list(extra)


def test_robot_controls_are_matched_to_cad_controls_by_place():
    d = built("interval-timer")
    tags = tags_dict(d, "A")
    display = {"id": "display_1", "kind": "display", "pos_mm": [250, 0, -20], "normal": [-1, 0, 0]}
    scene = _scene_from(tags, 180.0, [313.3, 0.0, -61.7], noise=1.5, extra=[display])
    reg = register(scene, tags)
    assert reg["matches"] == {s["id"]: s["truth"] for s in scene if "truth" in s}
    assert reg["yaw_deg"] == pytest.approx(180.0, abs=1.0) and reg["residual_mm"] < 5.0   # ±1.5 mm per axis of made-up noise


def test_any_turn_on_the_desk_and_a_missed_control():
    """The device turned 37 deg, one button not detected: the other two still land on the right CAD controls."""
    d = built("interval-timer")
    tags = tags_dict(d, "A")
    scene = _scene_from(tags, 37.0, [280.0, -15.0, -50.0], noise=0.8)[1:]
    reg = register(scene, tags)
    assert reg["matches"] == {s["id"]: s["truth"] for s in scene}
    assert reg["yaw_deg"] == pytest.approx(360 - 37.0, abs=6.0)   # robot frame -> CAD frame; two points along a row pin it loosely


WIDEN_MIN = """
ax = cq.Vector(0.7071068, 0, 0.7071068)
o = cq.Vector(42.5, -42.0, 76.5)
result = old.cut(cq.Solid.makeCylinder(5.6, 4.0, o - ax * 1.0, ax))
"""


def _write_run(folder, scene, findings, record):
    folder.mkdir(parents=True)
    lines = [{"seq": 1, "t": 0, "run_id": folder.name, "type": "scene_ready", "payload": {"frame": "arm_base", "controls": scene}}]
    for i, f in enumerate(findings):
        lines.append({"seq": 2 + i, "t": 1, "run_id": folder.name, "type": "finding", "payload": f})
    (folder / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (folder.parent / "results.json").write_text(json.dumps({"results": [record]}))


def test_fix_run_matches_diagnoses_applies_and_builds_the_patched_device(tmp_path, monkeypatch):
    from rav_harness import cadloop
    d = built("interval-timer")
    tags = tags_dict(d, "A")
    scene = _scene_from(tags, 180.0, [313.3, 0.0, -61.7], noise=1.0)
    min_id = next(s["id"] for s in scene if s["truth"] == "button_1")
    sec_id = next(s["id"] for s in scene if s["truth"] == "button_2")
    finding = lambda fid, target: {"id": fid, "severity": "high", "target": target, "label": "stuck",  # noqa: E731
                                   "what_happened": "no reading changed", "step_ids": ["s1"], "event_seqs": [1]}
    run_dir = tmp_path / "eval" / "001-rules-interval-timer-A"
    _write_run(run_dir, scene + [{"id": "display_1", "kind": "display", "pos_mm": [250, 0, -20], "normal": [-1, 0, 0]}],
               [finding("F1", min_id), finding("F2", sec_id), finding("F3", "display_1")],
               {"run_id": run_dir.name, "authored": "interval-timer", "rev": "A", "model": "rules"})
    seen = []

    def analyst_for(backend):
        def analyst(ctx):
            seen.append(ctx.finding.target)
            cause = lambda text: RootCause(finding=ctx.finding.id, evidence=[], hypotheses=[], root_cause=text, confidence=0.8)  # noqa: E731
            if ctx.finding.target != "button_1":
                return cause("the +SEC firmware adds the wrong step; no CAD change fixes that"), None
            ws = backend.open_branch(f"fix {ctx.finding.id}")
            backend.branch(ws).write_part("bezel_min", WIDEN_MIN)
            assert backend.check_branch(ws).reasons == []
            patch = CADPatch(file=backend.url(ws), revision_from="A", revision_to="B", changes=[], backend="local",
                             source=backend.source(ws, backend.microversion(ws)))
            return cause("the bezel's bore leaves 0.1 mm around the cap, so it binds"), patch
        return analyst

    real_backend = cadloop.__dict__.get("LocalCadBackend")
    captured = {}
    from rav_cad import local as local_mod
    original = local_mod.LocalCadBackend

    class Capturing(original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["backend"] = self

    monkeypatch.setattr(local_mod, "LocalCadBackend", Capturing)
    monkeypatch.setattr("rav_harness.analyst.make_local_analyst", lambda backend, tags: analyst_for(backend))
    retests = []
    monkeypatch.setattr(cadloop, "_retest", lambda *a, **kw: retests.append(a) or {"verdicts": {"F1": "fixed"}})
    summary = cadloop.fix_run(run_dir, parallel=False)
    assert real_backend is None and sorted(seen) == ["button_1", "button_2"]
    rows = {r["finding"]: r for r in summary["findings"]}
    assert rows["F1"]["cad_control"] == "button_1" and "folder" in rows["F1"]["applied"] and rows["F1"]["applied"]["by"] == "auto (sim)"
    assert rows["F2"]["patch"] is None and summary["not_cad"][0]["finding"] == "F3"
    assert summary["retest"] == {"verdicts": {"F1": "fixed"}}
    parts = retests[0][5]
    assert set(parts) == {"bezel_min"}
    built_dev = patched_device(d, "A", parts, tmp_path / "dev")
    assert built_dev["travel"]["min_travel"]["to"] == 0.3
    assert json.loads((run_dir / "cad" / "fix.json").read_text())["findings"][0]["finding"] == "F1"


def test_off_the_sim_the_loop_stops_at_proposals(tmp_path, monkeypatch):
    """A run that isn't on an authored appliance (the real arm): a STEP and tag file, nothing applied without --approve."""
    from rav_harness import cadloop
    d = built("interval-timer")
    tags_file = tmp_path / "tags.yaml"
    tags_file.write_text(yaml.safe_dump(tags_dict(d, "A")))
    tags = tags_dict(d, "A")
    scene = _scene_from(tags, 90.0, [250.0, 30.0, -40.0])
    min_id = next(s["id"] for s in scene if s["truth"] == "button_1")
    run_dir = tmp_path / "real" / "run-1"
    _write_run(run_dir, scene, [{"id": "F1", "severity": "high", "target": min_id, "label": "stuck", "what_happened": "x",
                                 "step_ids": ["s1"], "event_seqs": [1]}], {"run_id": "other"})

    def analyst_for(backend):
        def analyst(ctx):
            ws = backend.open_branch("fix")
            backend.branch(ws).write_part("bezel_min", WIDEN_MIN)
            return (RootCause(finding="F1", evidence=[], hypotheses=[], root_cause="tight bore", confidence=0.7),
                    CADPatch(file=backend.url(ws), revision_from="A", revision_to="B", changes=[], backend="local",
                             source=backend.source(ws, backend.microversion(ws))))
        return analyst

    monkeypatch.setattr("rav_harness.analyst.make_local_analyst", lambda backend, tags: analyst_for(backend))
    summary = cadloop.fix_run(run_dir, step=d / "build" / "revA.step", tags=tags_file)
    assert summary["approved_by"] is None and summary["findings"][0]["applied"] is None
    assert "approve" in summary["next"] and "retest" not in summary
