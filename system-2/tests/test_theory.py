"""The device theory: a hypothesis validates, tests derive from it, and a failed enabler blocks rather than passes."""
import pytest
from pydantic import ValidationError

from rav_harness import theory as t

HYPOTHESIS = {
    "controls": [
        {"id": "power", "primitive": "flip", "returns": "latching"},
        {"id": "start", "primitive": "press"},
        {"id": "level", "primitive": "turn", "returns": "continuous", "range": {"low": 1, "high": 9, "direction": "clockwise raises"}},
        {"id": "lid_handle", "primitive": "hook_pull", "returns": "latching"},
    ],
    "indicators": [{"id": "screen", "kind": "text_display", "shows": ["level"], "vocabulary": ["LID"]}],
    "mechanisms": [{"id": "lid", "kind": "hinge", "operated_by": "lid_handle"}],
    "containers": [{"id": "bay", "kind": "well", "sensed": True}],
    "objects": [{"id": "cup", "fits": ["bay"]}],
    "state": [{"name": "level_value", "range": {"low": 1, "high": 9}, "default": 5}, {"name": "mode", "values": ["off", "ready", "on"], "is_mode": True}],
    "relations": [
        {"kind": "enables", "source": "power", "target": "*", "when": {"subject": "power", "value": "on"}},
        {"kind": "drives", "source": "level", "target": "level_value", "mapping": "1 to 9 over the sweep"},
        {"kind": "displays", "source": "screen", "target": "level_value"},
        {"kind": "interlocks", "source": "lid", "target": "start", "when": {"subject": "lid", "value": "open"}, "message": "LID"},
        {"kind": "requires", "source": "bay", "target": "start"},
    ],
    "procedures": [{"name": "run", "steps": [{"primitive": "flip", "target": "power"}, {"primitive": "press", "target": "start"}]}],
}


def test_derives_a_test_per_property_and_subject():
    h = t.DeviceHypothesis.model_validate(HYPOTHESIS)
    keys = {i.key for i in t.derive_tests(h)}
    for k in ("actuates:start", "returns_to_default:start", "respects_range:level", "gives_feedback:level", "interlock_holds:lid:start",
              "interlock_releases:lid:start", "requirement_holds:bay:start", "mapping_matches:level:level_value", "default_on_power:level_value",
              "accepts_object:bay:cup", "mechanism_range:lid", "message_documented:screen", "procedure_completes:run", "enable_holds:power:*"):
        assert k in keys, k
    assert "returns_to_default:power" not in keys  # a toggle latches


def test_a_failed_enabler_blocks_instead_of_passing():
    intents = t.derive_tests(t.DeviceHypothesis.model_validate(HYPOTHESIS))
    report = t.coverage(intents, {"actuates:power": "failed"})
    assert report.blocked["actuates:start"] == ["actuates:power"]
    assert "actuates:start" not in report.tested and report.fraction < 0.1


def test_relations_must_name_known_pieces():
    with pytest.raises(ValidationError):
        t.DeviceHypothesis.model_validate({"relations": [{"kind": "drives", "source": "ghost", "target": "nothing"}]})


def test_schema_exports_for_structured_output():
    schema = t.DeviceHypothesis.model_json_schema()
    assert "relations" in schema["properties"]
