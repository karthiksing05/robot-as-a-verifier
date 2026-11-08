"""The local CadQuery analyst end to end, offline: a scripted stand-in for `claude -p` drives the real rav-cad-local
tools in the analyst's workspace, and the fix loop approves and applies what it submits."""
import json
import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("cadquery")
yaml = pytest.importorskip("yaml")
pytest.importorskip("mcp")
pytestmark = pytest.mark.cad

from rav_cad.generic import bench  # noqa: E402
from rav_cad.local import LocalCadBackend  # noqa: E402
from rav_cad.local.backend import parametric_sources  # noqa: E402
from rav_cad.local.mcp_server import LocalSession, ToolError  # noqa: E402
from rav_cad.parametric.build import build  # noqa: E402
from rav_cad.parametric.spec import Spec  # noqa: E402
from rav_contracts import TestRequest  # noqa: E402
from rav_harness.analyst import cad_command, make_local_analyst  # noqa: E402
from rav_harness.loop import fix_and_retest  # noqa: E402
from rav_harness.mock import mock_system_1  # noqa: E402
from rav_harness.runlog import read_events  # noqa: E402
from test_local_backend import WIDEN  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUEST = TestRequest(request_id="t", product="box", revision="A")
DIAG = dict(confidence=0.7, hypotheses=[{"cause": "see root cause", "p": 0.8}], evidence=["from the run"], predicted="passes")


class ScriptedLocalSession:
    """Stands in for `claude -p --mcp-config ...`: opens the session the config describes, in-process, and runs each
    finding's script of tool calls against it."""
    def __init__(self, backend, scripts):
        self.backend, self.scripts, self.commands = backend, scripts, []

    def __call__(self, cmd, stdin, timeout_s):
        self.commands.append((cmd, stdin))
        server = json.loads(open(cmd[cmd.index("--mcp-config") + 1]).read())["mcpServers"]["rav-cad-local"]
        a = server["args"]
        arg = lambda flag: a[a.index(flag) + 1]   # noqa: E731
        assert json.loads(pathlib.Path(arg("--sources")).read_text())["button_2 insert"].count("def ") > 0
        session = LocalSession(self.backend, arg("--workspace"), arg("--out"), arg("--target"), a[a.index("--verify") + 1:])
        for name, kwargs in self.scripts[arg("--target")]:
            try:
                session.log(name, kwargs, True, getattr(session, name)(**kwargs))
            except ToolError as e:
                session.log(name, kwargs, False, str(e))
        out = {"type": "result", "is_error": False, "result": "done", "stop_reason": "end_turn", "duration_ms": 20000,
               "usage": {"input_tokens": 8000, "output_tokens": 900}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


SCRIPTS = {
    "button_2": [("get_part", {"part": "button_2 insert"}),
                 ("write_part", {"part": "button_2 insert", "code": "import os"}),     # refused, nothing changes
                 ("write_part", {"part": "button_2 insert", "code": WIDEN}),
                 ("check", {}),
                 ("submit_fix", {"root_cause": "the bores leave 0.15 mm; the stem binds", **DIAG})],
    "door": [("list_controls", {}),
             ("submit_fix", {"root_cause": "needs a person to redesign the handle", "no_cad_fix": True, **DIAG})],
}


@pytest.fixture
def setup(tmp_path):
    built = build(Spec.load(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml"))
    tags = tmp_path / "tags.yaml"
    tags.write_text(yaml.safe_dump(bench.tags_dict(built)))
    backend = LocalCadBackend(tags, bench.parts(built), out_dir=tmp_path / "out", product="appliance",
                              require_approval=False, sources=parametric_sources(built))
    return backend, tags


def test_the_loop_applies_the_new_geometry_as_rev_b(setup, tmp_path):
    backend, tags = setup
    runner = ScriptedLocalSession(backend, SCRIPTS)
    before, after = fix_and_retest(mock_system_1, REQUEST, make_local_analyst(backend, tags, run=runner, binary="claude"),
                                   backend, log_root=str(tmp_path / "runs"), parallel=True)
    assert before.reward.value == 0.6 and after is not None and after.reward.value == 1.0
    rev_b = tmp_path / "out" / "rev_B"
    assert {p.name for p in rev_b.iterdir()} == {"assembly.step", "button_2 insert.stl", "button_2 insert.py",
                                                "edits.jsonl", "patch_result.json"}
    events = read_events(tmp_path / "runs" / "t-revA" / "events.jsonl")
    patches = [e.payload for e in events if e.type == "patch_proposed"]
    assert [p["backend"] for p in patches] == ["local"] and patches[0]["edits"][0]["op"] == "write_part"
    calls = [e.payload["tool"] for e in events if e.type == "tool_call" and e.payload["tool"].startswith("cad.")]
    assert {"cad.get_part", "cad.write_part", "cad.check", "cad.submit_fix", "cad.list_controls"} <= set(calls)
    prompt = runner.commands[0][1]
    assert "Control " in prompt and "Your branch: " in prompt


def test_the_command_only_offers_the_local_tools(tmp_path):
    cmd = cad_command("claude", str(tmp_path / "mcp.json"), "claude-opus-5-5", "high", 5, server="rav-cad-local",
                      system="x")
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__rav-cad-local" and cmd[cmd.index("--tools") + 1] == ""
