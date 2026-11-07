"""The CadQuery backend and the parametric appliance model. Needs `uv sync --extra cad`; skipped without it."""
import json
import pathlib
import shutil

import pytest

pytest.importorskip("cadquery")
pytestmark = pytest.mark.cad

from rav_cad import CadQueryBackend  # noqa: E402
from rav_cad.parametric import checks, gauge, patch  # noqa: E402
from rav_cad.parametric.build import build, export, features_json  # noqa: E402
from rav_cad.parametric.spec import Spec  # noqa: E402
from rav_contracts import CADPatch, ParamChange  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REV_A = ROOT / "subjects/appliance/cad/appliance.rev_a.yaml"
EXAMPLES = ROOT / "cad/examples"
FIX = {"edits": [{"param": "features.button_2.clearance", "old": 0.15, "new": 0.40}], "reason": "binds"}
DOOR_FIX = {"param": "features.door.handle_style", "old": "tab", "new": "bar"}


@pytest.fixture(scope="module")
def rev_a():
    return Spec.load(REV_A)


def failed(spec, **kw):
    return {r.name for r in checks.run(build(spec), **kw) if not r.ok}


def cad_patch(param, old, new, **kw):
    return CADPatch(file=str(REV_A), revision_from="A", revision_to="B",
                    changes=[ParamChange(param=param, from_value=old, to_value=new)], **kw)


# --- the model -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("spec", [REV_A, EXAMPLES / "flat_box.yaml", EXAMPLES / "panel_demo.yaml"])
def test_examples_build_and_pass(spec):
    rows = checks.run(build(Spec.load(spec)))
    assert checks.ok(rows), checks.table([r for r in rows if not r.ok])


def test_measured_clearance_matches_parameter(rev_a):
    rows = {r.name: r for r in checks.run(build(rev_a), interference=False)}
    assert "measured 0.150" in rows["button_2: clearance"].detail
    assert "measured 0.400" in rows["button_1: clearance"].detail


def test_button_fix_reprints_only_the_insert(rev_a):
    r = patch.apply(rev_a, FIX)
    assert r.accepted, r.reasons
    assert r.new_rev == "B" and r.changed_parts == ["button_2__insert"]
    assert 0 < r.cost["minutes"] < 40


@pytest.mark.parametrize("style", ["bar", "push_latch"])
def test_door_fixes_reprint_only_the_handle(rev_a, style):
    r = patch.apply(rev_a, {**DOOR_FIX, "new": style})
    assert r.accepted, r.reasons
    assert r.changed_parts == ["door__handle"]


@pytest.mark.parametrize("bad, why", [
    ({"param": "features.button_2.clearance", "old": 0.15, "new": 0.70}, "posture allows 0.25"),
    ({"edits": [{"param": "features.button_2.clearance", "old": 0.15, "new": 0.40},
                {"param": "features.button_1.clearance", "old": 0.40, "new": 0.35}]}, "allows 1 per patch"),
    ({"param": "features.button_2.clearance", "old": 0.40, "new": 0.50}, "stale"),
    ({"param": "features.button_2.clearence", "old": 0.15, "new": 0.40}, "unknown parameter"),
])
def test_bad_patches_refused(rev_a, bad, why):
    r = patch.apply(rev_a, bad, interference=False)
    assert not r.accepted and any(why in reason for reason in r.reasons), r.reasons


def test_moving_a_control_flags_the_shell(rev_a):
    r = patch.apply(rev_a, {"param": "features.button_1.u", "old": -35, "new": -33}, interference=False)
    assert r.accepted and r.changed_parts == ["shell"] and "SHELL" in r.summary()


def test_checks_catch_bad_designs(rev_a):
    assert "button_1 / button_2: fingertip room" in failed(rev_a.with_edits({"features.button_1.u": -18}),
                                                           interference=False)
    assert "door: on its face" in failed(rev_a.with_edits({"features.door.open_u": 140}), interference=False)
    assert "door: design rules" in failed(rev_a.with_edits({"features.door.handle_style": "bar",
                                                            "features.door.handle_bar_gap": 10}), interference=False)
    assert "button_3: no interference" in failed(rev_a.with_edits({"features.button_3.switch_gap": -0.5}))
    crowded = rev_a.model_copy(update={"limits": rev_a.limits.model_copy(update={"bare_patch": 60})})
    assert "slope: bare patch for touch taps" in failed(crowded, interference=False)


def test_door_swing_check_catches_a_wrong_hinge(rev_a):
    b = build(rev_a)
    pt, d, m = b.placed["door"].geom.swing
    b.placed["door"].geom.swing = (pt, (0, -d[1], 0), m)        # swing inward instead
    assert any(r.name == "door: swings open" and not r.ok for r in checks.run(b))


def test_features_json_and_exports(rev_a, tmp_path):
    b = build(rev_a)
    fj = features_json(b)
    b2 = next(f for f in fj["features"] if f["id"] == "button_2")
    assert b2["clearance_mm"] == 0.15 and {"approach", "contact", "actuate", "pressed"} <= set(b2["waypoints"])
    door = next(f for f in fj["features"] if f["id"] == "door")
    assert "hinge" in door and door["info"]["handle"]["needs"] == "pinch"
    names = {f.stem for f in export(b, tmp_path)}
    assert {"shell", "base", "fixture_1", "fixture_2", "button_2__holder", "door__door", "door__handle"} <= names
    assert (tmp_path / "assembly.glb").exists()


def test_gauge(rev_a, tmp_path):
    files = gauge.for_feature(rev_a, "button_2", tmp_path)
    assert {f.name for f in files} == {"gauge_plate.stl", "gauge_peg.stl"}


# --- the backend, through the team's CADPatch contract -------------------------------------------------

@pytest.fixture
def backend(tmp_path):
    spec = shutil.copy(REV_A, tmp_path / "appliance.rev_a.yaml")
    return CadQueryBackend(spec, out_dir=tmp_path / "out", interference=False)


def test_backend_reads_params(backend):
    params = backend.read_params()
    assert params["features.button_2.clearance"] == 0.15 and params["features.door.handle_style"] == "tab"


def test_backend_accepts_the_params_file_names(backend):
    assert backend.check(cad_patch("button_clearance[1]", 0.15, 0.40)) == []
    assert backend.check(cad_patch("handle_style", "tab", "push_latch")) == []


def test_backend_refuses_and_explains(backend):
    assert any("posture" in p for p in backend.check(cad_patch("button_clearance[1]", 0.15, 0.70)))
    stale = CADPatch(file="x", revision_from="B", revision_to="C",
                     changes=[ParamChange(param="button_clearance[1]", from_value=0.15, to_value=0.40)])
    assert any("starts from rev B" in p for p in backend.check(stale))


def test_backend_apply_needs_approval_then_writes_rev_b(backend, tmp_path):
    with pytest.raises(ValueError, match="approves"):
        backend.apply(cad_patch("button_clearance[1]", 0.15, 0.40))
    out = pathlib.Path(backend.apply(cad_patch("button_clearance[1]", 0.15, 0.40, approved_by="bayan")))
    assert (out / "button_2__insert.stl").exists() and not (out / "shell.stl").exists()
    assert json.loads((out / "patches.json").read_text())[0]["approved_by"] == "bayan"
    rev_b = tmp_path / "appliance.rev_b.yaml"
    assert Spec.load(rev_b).rev == "B" and Spec.load(rev_b).get("features.button_2.clearance") == 0.40
    assert backend.read_params()["rev"] == "B"


def test_fix_loop_runs_through_cadquery(backend, tmp_path):
    """The harness's own demo story (mock robot and analyst), with both fixes patching the real model."""
    from rav_contracts import TestRequest
    from rav_harness.loop import fix_and_retest
    from rav_harness.mock import mock_analyst, mock_system_1
    request = TestRequest(request_id="t", product="box", revision="A")
    backend.require_approval = False            # the harness approves through approve() and logs it
    before, after = fix_and_retest(mock_system_1, request, mock_analyst, backend, log_root=str(tmp_path / "runs"))
    assert before.reward.value == 0.6 and after.reward.value == 1.0
    params = backend.read_params()
    assert params["rev"] == "B" and params["features.button_2.clearance"] == 0.40
    assert params["features.door.handle_style"] == "push_latch"
    out = tmp_path / "out" / "rev_B"
    assert (out / "button_2__insert.stl").exists() and (out / "door__handle.stl").exists()
    from rav_harness.runlog import read_events
    proposed = [e for e in read_events(tmp_path / "runs" / "t-revA" / "events.jsonl") if e.type == "patch_proposed"]
    assert {e.payload["changes"][0]["param"] for e in proposed} == {"features.button_2.clearance", "features.door.handle_style"}
