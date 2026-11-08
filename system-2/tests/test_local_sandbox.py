"""The local CAD workspace and the sandbox that runs the model's CadQuery code. Offline."""
import json

import pytest

cq = pytest.importorskip("cadquery")
pytestmark = pytest.mark.cad

from rav_cad.local import SandboxError, Workspace  # noqa: E402


@pytest.fixture
def ws(tmp_path):
    return Workspace.create(tmp_path / "ws", {"lid": cq.Workplane().box(10, 10, 10).val(),
                                              "base part": cq.Workplane().box(5, 5, 5).translate((20, 0, 0)).val()})


def test_good_code_replaces_the_part_and_changes_the_state(ws):
    s0 = ws.state()
    res = ws.write_part("lid", "result = old.cut(cq.Workplane().cylinder(20, 2).val())\n"
                               "print(round(parts['base part'].Volume()))")
    assert res["faces"] == 7 and res["volume_mm3"] < 1000 and res["printed"] == "125"
    assert ws.state() != s0 and ws.state() == ws.state()
    assert ws.overridden() == ["lid"] and ws.code("lid").startswith("result = old.cut")
    assert ws.parts()["lid"].Volume() == pytest.approx(res["volume_mm3"], rel=1e-3)
    assert ws.parts()["base part"].Volume() == pytest.approx(125)
    assert ws.reset_part("lid") and ws.state() == s0 and ws.code("lid") is None


def test_the_geom_helpers_and_numpy_are_available(ws):
    assert ws.write_part("lid", "from rav_cad.parametric import geom as g\nimport numpy\n"
                                "result = g.cyl(float(numpy.float64(3)), 0, 5)")["faces"] == 3


@pytest.mark.parametrize("code, reason", [
    ("import os", "not allowed"),
    ("import subprocess", "not allowed"),
    ("import rav_cad.local", "not allowed"),
    ("open('/etc/hosts').read()", "open"),
    ("__import__('socket')", "not allowed"),
    ("result = old.fuse(old.translate((50, 0, 0)))", "exactly one solid"),
    ("result = 3", "not a CadQuery shape"),
    ("x = 1", "must set `result`"),
    ("def f():\n    return 1 / 0\nf()", "part_code.py\", line 3"),
])
def test_bad_code_is_refused_with_a_reason_and_changes_nothing(ws, code, reason):
    s0 = ws.state()
    with pytest.raises(SandboxError, match=reason.replace("(", r"\(")):
        ws.write_part("lid", code)
    assert ws.state() == s0 and ws.overridden() == []
    last = json.loads((ws.root / "edits.jsonl").read_text().splitlines()[-1])
    assert last["op"] == "write_part" and not last["ok"]


def test_runaway_code_is_stopped(ws):
    with pytest.raises(SandboxError, match="longer than 8 s"):
        ws.write_part("lid", "while True:\n    pass", timeout_s=8)


def test_unknown_parts_are_named(ws):
    with pytest.raises(KeyError, match="parts are"):
        ws.write_part("door", "result = old")
    with pytest.raises(SandboxError, match="no part 'door'"):
        ws.write_part("lid", "result = parts['door']")


def test_a_workspace_reopens_from_its_folder(ws):
    ws.write_part("lid", "result = old.translate((0, 0, 1))")
    again = Workspace(ws.root)
    assert again.state() == ws.state() and again.parts()["lid"].BoundingBox().zmax == pytest.approx(6)
