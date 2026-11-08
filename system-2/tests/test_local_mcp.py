"""The local CAD tools (rav-cad-local MCP server): the analyst writes CadQuery for a new part, checks it, submits.
Offline."""
import asyncio
import json
import pathlib

import pytest

cq = pytest.importorskip("cadquery")
yaml = pytest.importorskip("yaml")
pytest.importorskip("mcp")
pytestmark = pytest.mark.cad

from rav_cad.generic import bench  # noqa: E402
from rav_cad.local import LocalCadBackend  # noqa: E402
from rav_cad.local.backend import parametric_sources  # noqa: E402
from rav_cad.local.mcp_server import LocalSession, ToolError, build_server  # noqa: E402
from rav_cad.parametric.build import build  # noqa: E402
from rav_cad.parametric.spec import Spec  # noqa: E402
from test_local_backend import WIDEN  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built():
    return build(Spec.load(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml"))


@pytest.fixture
def tools(built, tmp_path):
    tags = tmp_path / "tags.yaml"
    tags.write_text(yaml.safe_dump(bench.tags_dict(built)))
    backend = LocalCadBackend(tags, bench.parts(built), out_dir=tmp_path / "out", product="appliance",
                              sources=parametric_sources(built))
    ws = backend.open_branch("fix button_2")
    session = LocalSession(backend, ws, tmp_path / "analyst", target="button_2", verify_with=["s2"])
    server = build_server(session)

    def call(tool, **args):
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
    return session, call


def calls(session):
    return [json.loads(line) for line in (session.out / "calls.jsonl").read_text().splitlines()]


def test_the_server_offers_the_local_tools(tools):
    session, _ = tools
    names = {t.name for t in asyncio.run(build_server(session).list_tools())}
    assert names == {"list_controls", "measure_gap", "part_size", "check", "submit_fix", "get_part", "write_part",
                     "reset_part", "list_faces", "render"}


def test_write_a_new_bore_check_and_submit(tools):
    session, call = tools
    assert call("list_controls")["target"] == "button_2"
    part = call("get_part", part="button_2 insert")
    assert part["reprintable"] and part["your_code"] is None and "def build" in part["reference_source"]
    assert any(f["kind"] == "cylinder" and f["radius"] == 5.15 for f in call("list_faces", part="button_2 insert")["list"])
    with pytest.raises(RuntimeError, match="check"):
        call("submit_fix", root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")
    wrote = call("write_part", part="button_2 insert", code=WIDEN)
    assert wrote["volume_mm3"] < wrote["volume_before_mm3"]
    assert call("measure_gap", part_a="button_2 moving", part_b="button_2 insert")["gap_mm"] == pytest.approx(0.4, abs=0.01)
    result = call("check")
    assert result["ok"] and result["changed"] == ["button_2 insert"] and result["control"] == "button_2"
    done = call("submit_fix", root_cause="0.15 mm bore binds", confidence=0.8, hypotheses=[{"cause": "tight bore", "p": 0.8}],
                evidence=["stalls at 2 mm"], predicted="presses freely")
    assert done["submitted"]
    patch = json.loads((session.out / "result.json").read_text())["patch"]
    assert patch["backend"] == "local" and patch["source"]["document_id"] == "local:appliance"
    assert patch["verify_with"] == ["s2"] and [e["op"] for e in patch["edits"]] == ["write_part"]
    from rav_contracts import CADPatch
    assert session.backend.check(CADPatch(**patch)) == []
    assert [c["tool"] for c in calls(session)][-3:] == ["measure_gap", "check", "submit_fix"]


def test_refusals_come_back_as_errors_the_model_can_read(tools):
    session, call = tools
    with pytest.raises(RuntimeError, match="isn't reprintable"):
        call("write_part", part="shell", code="result = old")
    with pytest.raises(RuntimeError, match="the code failed, nothing changed: ImportError"):
        call("write_part", part="button_2 insert", code="import os")
    with pytest.raises(RuntimeError, match="no part"):
        call("get_part", part="button_9 insert")
    assert session.workspace.overridden() == [] and session.edits == []
    assert [c["ok"] for c in calls(session)] == [False, False, False]


def test_an_edit_after_the_check_blocks_submit_and_reset_undoes(tools):
    session, call = tools
    call("write_part", part="button_2 insert", code=WIDEN)
    assert call("check")["ok"]
    call("write_part", part="button_2 insert", code="result = old.translate((0, 0, 0.01))")
    with pytest.raises(RuntimeError, match="changed after the last check"):
        call("submit_fix", root_cause="x", confidence=0.5, hypotheses=[], evidence=[], predicted="x")
    assert call("reset_part", part="button_2 insert")["reset"] and session.workspace.overridden() == []
    image = call("render", highlight=["button_2 insert"])
    assert any(getattr(c, "type", "") == "image" for c in image)


def test_rendering_never_makes_untouched_parts_look_changed(tools):
    """Tessellating stores a mesh on a shape, which used to shift its box and make the check see every rendered part
    as changed (the lid session in the first live run could never pass)."""
    session, call = tools
    call("render")
    assert call("check")["changed"] == []
    session.parts()["shell"].tessellate(0.4, 0.3)
    assert call("check")["changed"] == []
