"""The generic, robot-centred checks, on our CadQuery appliance exported as a named STEP assembly. No network."""
import pytest

pytest.importorskip("cadquery")
pytestmark = pytest.mark.cad

from rav_cad.generic import Tags, bench, failures, load_step, run, save_step  # noqa: E402
from rav_cad.generic.tags import clean_name  # noqa: E402
from rav_cad.parametric.build import build  # noqa: E402
from rav_cad.parametric.spec import Spec  # noqa: E402
import pathlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = Spec.load(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml")


@pytest.fixture(scope="module")
def rev_a():
    b = build(SPEC)
    return bench.parts(b), bench.tags(b)


def judge(rev_a, edits, target):
    """A fix as the backend judges it: the edited model against the tested one, for one control. Motion is read from
    the edited model, as the Onshape backend reads it from the new revision's mates."""
    before, _ = rev_a
    b = build(SPEC.with_edits(edits))
    return failures(run(bench.parts(b), bench.tags(b), before=before, target=target))


# --- the product file ------------------------------------------------------------------------------------------

def test_step_round_trip_keeps_names_and_places(rev_a, tmp_path):
    parts, tags = rev_a
    loaded = load_step(save_step(parts, tmp_path / "rev_a.step"))
    assert set(loaded) == set(parts)
    a, b = parts["button_2 insert"].BoundingBox(), loaded["button_2 insert"].BoundingBox()
    assert abs(a.center.x - b.center.x) < 1e-3 and abs(a.center.z - b.center.z) < 1e-3
    assert failures(run(loaded, tags)) == failures(run(parts, tags))          # same verdicts from the file


def test_tag_file_names_are_checked_against_the_model(rev_a):
    parts, tags = rev_a
    assert tags.missing(set(parts)) == []
    results = run({k: v for k, v in parts.items() if k != "button_2 insert"}, tags)
    assert not results[0].ok and "button_2 insert" in results[0].detail


def test_tag_file_rules():
    assert clean_name("button_2 cap <1>") == "button_2 cap"
    with pytest.raises(ValueError, match="pull is needed"):
        Tags.from_dict({"controls": {"door": {"skill": "pull", "parts": ["door"]}}})
    with pytest.raises(ValueError, match="skill must be"):
        Tags.from_dict({"controls": {"x": {"skill": "pinch", "parts": ["x"]}}})
    with pytest.raises(ValueError, match="parts is empty"):
        Tags.from_dict({"controls": {"x": {"skill": "press"}}})
    t = Tags.from_dict({"controls": {"b": {"parts": ["b cap <1>"], "moving": "b cap <1>",
                                           "motion": {"type": "slide", "axis": [0, 0, -2], "travel": 1}}}})
    assert t.controls["b"].moving == ("b cap",) and t.controls["b"].motion.axis == (0.0, 0.0, -1.0)


# --- Rev A, as the robot found it ---------------------------------------------------------------------------------

def test_rev_a_fails_on_both_planted_faults_and_nothing_else(rev_a):
    parts, tags = rev_a
    failed = failures(run(parts, tags))
    assert any(f.startswith("button_2: sliding clearance: 0.15 mm") for f in failed)
    assert any(f.startswith("door: opens with a hooked fingertip") for f in failed)
    assert all(f.startswith(("button_2:", "door:")) for f in failed)


# --- judging fixes --------------------------------------------------------------------------------------------------

def test_the_button_fix_passes_and_the_door_is_not_held_against_it(rev_a):
    before, tags = rev_a
    results = run(bench.parts(build(SPEC.with_edits({"features.button_2.clearance": 0.40}))), tags, before=before, target="button_2")
    assert failures(results) == []
    assert any(r.known and r.name.startswith("door:") for r in results)


def test_the_bar_handle_fixes_the_door(rev_a):
    assert judge(rev_a, {"features.door.handle_style": "bar"}, "door") == []


def test_a_push_latch_is_refused_because_the_fingertip_cant_hook_it(rev_a):
    failed = judge(rev_a, {"features.door.handle_style": "push_latch"}, "door")
    assert any(f.startswith("door: opens with a hooked fingertip") for f in failed)


def test_a_fix_that_leaves_its_own_fault_still_fails(rev_a):
    assert any("sliding clearance" in f for f in judge(rev_a, {"features.button_2.clearance": 0.25}, "button_2"))


@pytest.mark.parametrize("edits, target, expected", [
    ({"shell.wall": 4.0}, "button_2", "fix leaves the body alone"),
    ({"features.button_2.clearance": 0.40, "features.button_3.clearance": 0.35}, "button_2", "fix stays within one control"),
    ({"features.button_2.travel": 6.0}, "button_2", "button_2: moves freely: hits button_2 holder"),
    ({"features.button_2.u": 22.0}, "button_2", "parts don't overlap at rest"),
])
def test_bad_fixes_are_refused_with_a_reason(rev_a, edits, target, expected):
    assert any(f.startswith(expected) for f in judge(rev_a, edits, target))


def test_a_fix_that_changes_nothing_is_refused(rev_a):
    before, tags = rev_a
    assert any(f.startswith("fix changes something") for f in failures(run(before, tags, before=before, target="button_2")))
