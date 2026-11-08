"""The CAD tools (rav-cad MCP server) the analyst uses on its branch, against the fake Onshape. No network."""
import asyncio
import json

import pytest

pytest.importorskip("cadquery")
pytest.importorskip("yaml")
pytest.importorskip("mcp")
pytestmark = pytest.mark.cad

from onshape_fake import VID, FakeOnshape, write_tags  # noqa: E402
from rav_cad.onshape.backend import OnshapeBackend  # noqa: E402
from rav_cad.onshape.mcp_server import CadSession, ToolError, build_server  # noqa: E402


@pytest.fixture(scope="module")
def tag_file(tmp_path_factory):
    return write_tags(tmp_path_factory.mktemp("tags") / "onshape.yaml")


@pytest.fixture
def tools(tag_file, tmp_path):
    fake = FakeOnshape()
    backend = OnshapeBackend(tag_file, client=fake, out_dir=tmp_path / "out", cache_dir=tmp_path / "cache")
    ws = backend.open_branch("fix door")
    session = CadSession(backend, ws, tmp_path / "analyst", target="door", verify_with=["s4"])
    server = build_server(session)

    def call(tool, **args):
        """What the model gets back: the tool's data, or its error message as a RuntimeError."""
        try:
            result = asyncio.run(server.call_tool(tool, args))
        except ToolError as e:
            raise RuntimeError(str(e)) from None
        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        if result.is_error:
            raise RuntimeError(" ".join(texts))
        payload = result.structured_content
        if isinstance(payload, dict) and set(payload) == {"result"}:
            return payload["result"]
        if payload is not None:
            return payload
        if len(texts) == 1 and len(result.content) == 1:
            return json.loads(texts[0])
        return result.content
    return fake, session, call


def calls(session):
    return [json.loads(line) for line in (session.out / "calls.jsonl").read_text().splitlines()]


def test_the_server_offers_the_cad_tools(tools):
    _, session, _ = tools
    names = {t.name for t in asyncio.run(build_server(session).list_tools())}
    assert {"list_controls", "get_features", "update_feature", "add_feature", "delete_feature", "set_variable",
            "measure_gap", "render", "check", "submit_fix"} <= names


def test_fix_the_door_on_the_branch_then_submit(tools):
    fake, session, call = tools
    assert call("list_controls")["target"] == "door"
    handle = next(f for f in call("get_features", name_contains="handle"))
    assert handle["params"]["style"] == "tab"
    assert call("update_feature", feature_id=handle["id"], params={"style": "bar"})["status"] == "OK"
    result = call("check")
    assert result["ok"] and result["changed"] == ["door insert"] and result["control"] == "door"
    done = call("submit_fix", root_cause="the tab needs a pinch", confidence=0.7, hypotheses=[{"cause": "no hook", "p": 0.8}],
                evidence=["6 N, 0.5 mm"], predicted="the fingertip hooks the bar")
    assert done["submitted"] and done["changed"] == ["door insert"]
    out = json.loads((session.out / "result.json").read_text())
    patch = out["patch"]
    assert patch["backend"] == "onshape" and patch["source"]["base_version_id"] == VID and patch["verify_with"] == ["s4"]
    assert patch["edits"] == [{"op": "update_feature", "target": "FdoorHandle", "summary": "door handle: style 'tab' -> 'bar'"}]
    assert fake.versions[VID] == {}                                             # the tested version is untouched
    assert [c["tool"] for c in calls(session)][-3:] == ["update_feature", "check", "submit_fix"]


def test_submit_needs_a_passing_check_on_the_branch_as_it_is(tools):
    _, session, call = tools
    with pytest.raises(RuntimeError, match="check"):
        call("submit_fix", root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")
    call("update_feature", feature_id="FdoorHandle", params={"style": "push_latch"})
    assert not call("check")["ok"]                                              # a push latch can't be hooked
    with pytest.raises(RuntimeError, match="check"):
        call("submit_fix", root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")
    call("update_feature", feature_id="FdoorHandle", params={"style": "bar"})
    assert call("check")["ok"]
    call("set_variable", name="button_2_clearance", expression="0.4 mm")       # an edit after the check
    with pytest.raises(RuntimeError, match="changed after the last check"):
        call("submit_fix", root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")


def test_no_cad_fix_needs_no_check(tools):
    _, session, call = tools
    assert call("submit_fix", root_cause="the reed switch is unplugged", confidence=0.6, hypotheses=[], evidence=[],
                predicted="", no_cad_fix=True)["patch"] is None
    assert json.loads((session.out / "result.json").read_text())["patch"] is None


def test_mistakes_come_back_as_errors_the_model_can_read(tools):
    _, session, call = tools
    with pytest.raises(RuntimeError, match="no parameter diameter"):
        call("update_feature", feature_id="FdoorHandle", params={"diameter": "3 mm"})
    with pytest.raises(RuntimeError, match="no feature"):
        call("get_feature", feature_id="Fnope")
    with pytest.raises(RuntimeError, match="no part"):
        call("measure_gap", part_a="door insert", part_b="door hinge")
    assert [c["ok"] for c in calls(session)] == [False, False, False]


def test_measure_render_and_variables(tools):
    _, _, call = tools
    assert call("measure_gap", part_a="button_2 moving", part_b="button_2 insert")["gap_mm"] == pytest.approx(0.0, abs=0.2)
    assert call("part_size", part="door insert")["size_mm"][0] > 10
    image = call("render")
    assert any(getattr(c, "type", "") == "image" for c in image)
    assert call("set_variable", name="button_2_clearance", expression="0.4 mm") == {"variable": "button_2_clearance", "from": "0.15 mm", "to": "0.4 mm"}
    with pytest.raises(RuntimeError, match="no variable"):
        call("set_variable", name="nope", expression="1 mm")


def test_added_and_deleted_features_are_recorded(tools):
    _, session, call = tools
    added = call("add_feature", definition={"btType": "BTMFeature-134", "featureType": "fillet", "name": "soften edge"})
    assert added["status"] == "OK"
    call("delete_feature", feature_id=added["feature"])
    assert [e.op for e in session.edits] == ["add_feature", "delete_feature"]


def test_a_session_spends_few_onshape_calls(tag_file, tmp_path):
    """Onshape rate-limits the feature-tree endpoint tightly and caps a free account at 2,500 calls a year, so a
    session reads the tree once, re-reads it only after its own edits, and checks versions with the cheap call."""
    import collections

    class Counting(FakeOnshape):
        def __init__(self):
            super().__init__()
            self.count = collections.Counter()

        def __getattribute__(self, name):
            attr = object.__getattribute__(self, name)
            if callable(attr) and not name.startswith("_") and name not in ("edit", "count"):
                object.__getattribute__(self, "count")[name] += 1
            return attr

    fake = Counting()
    backend = OnshapeBackend(tag_file, client=fake, out_dir=tmp_path / "out", cache_dir=tmp_path / "cache")
    ws = backend.open_branch("fix door")
    s = CadSession(backend, ws, tmp_path / "analyst", target="door")
    s.list_controls()
    s.get_features("handle")
    s.get_features()
    s.get_feature("FdoorHandle")
    s.update_feature("FdoorHandle", {"style": "bar"})
    s.get_features()
    assert s.check()["ok"]
    s.submit_fix(root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")
    assert fake.count["get_features"] == 2            # once before the edit, once after it
    assert fake.count["current_microversion"] == 3    # around the check's export, and at submit
    assert fake.count["export_step"] == 2             # the branch, and the tested version once (then cached)
