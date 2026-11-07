"""The Onshape analyst end to end, offline: a scripted stand-in for `claude -p` drives the real rav-cad tools on the
analyst's branch of the fake Onshape, and the fix loop approves and applies what it submits."""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("cadquery")
pytest.importorskip("yaml")
pytest.importorskip("mcp")
pytestmark = pytest.mark.cad

from onshape_fake import VID, FakeOnshape, write_tags  # noqa: E402
from rav_cad.onshape.backend import OnshapeBackend  # noqa: E402
from rav_cad.onshape.mcp_server import CadSession, ToolError  # noqa: E402
from rav_contracts import TestRequest  # noqa: E402
from rav_harness.analyst import make_onshape_analyst, onshape_command  # noqa: E402
from rav_harness.loop import fix_and_retest  # noqa: E402
from rav_harness.mock import mock_system_1  # noqa: E402
from rav_harness.runlog import read_events  # noqa: E402

REQUEST = TestRequest(request_id="t", product="box", revision="A")
DIAG = dict(confidence=0.7, hypotheses=[{"cause": "see root cause", "p": 0.8}], evidence=["from the run"], predicted="passes")


class ScriptedCadSession:
    """Stands in for `claude -p --mcp-config ...`: starts the CAD session the config describes, in-process on the same
    backend, and runs each finding's script of tool calls against it."""
    def __init__(self, backend, scripts):
        self.backend, self.scripts, self.commands = backend, scripts, []

    def __call__(self, cmd, stdin, timeout_s):
        self.commands.append((cmd, stdin))
        server = json.loads(open(cmd[cmd.index("--mcp-config") + 1]).read())["mcpServers"]["rav-cad"]
        a = server["args"]
        arg = lambda flag: a[a.index(flag) + 1]   # noqa: E731
        session = CadSession(self.backend, arg("--workspace"), arg("--out"), arg("--target"), a[a.index("--verify") + 1:])
        for step in self.scripts[arg("--target")]:
            name, kwargs = step
            try:
                result = getattr(session, name)(**kwargs)
                session.log(name, kwargs, True, result)
            except ToolError as e:
                session.log(name, kwargs, False, str(e))
        out = {"type": "result", "is_error": False, "result": "done", "stop_reason": "end_turn", "duration_ms": 31000,
               "usage": {"input_tokens": 9000, "output_tokens": 1200}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


@pytest.fixture
def setup(tmp_path):
    tags = write_tags(tmp_path / "onshape.yaml")
    fake = FakeOnshape()
    backend = OnshapeBackend(tags, client=fake, out_dir=tmp_path / "out", cache_dir=tmp_path / "cache", require_approval=False)
    return fake, backend, tags


SCRIPTS = {
    "button_2": [("get_features", {"name_contains": "button_2"}),
                 ("update_feature", {"feature_id": "FbtnBore2", "params": {"clearance": "0.6 mm"}}),
                 ("check", {}),                                      # a first try; it settles on its siblings' 0.4 mm
                 ("update_feature", {"feature_id": "FbtnBore2", "params": {"clearance": "0.4 mm"}}),
                 ("check", {}),
                 ("submit_fix", {"root_cause": "the bore is 0.15 mm, siblings 0.4, so the stem binds", **DIAG})],
    "door": [("list_controls", {}),
             ("update_feature", {"feature_id": "FdoorHandle", "params": {"style": "push_latch"}}),
             ("check", {}),                                          # refused: a fingertip can't hook a push latch
             ("submit_fix", {"root_cause": "too early", **DIAG}),    # refused: the check didn't pass
             ("update_feature", {"feature_id": "FdoorHandle", "params": {"style": "bar"}}),
             ("check", {}),
             ("submit_fix", {"root_cause": "the tab needs a pinch; a bar can be hooked", **DIAG})],
}


def test_the_whole_loop_fixes_both_faults_in_onshape(setup, tmp_path):
    fake, backend, tags = setup
    runner = ScriptedCadSession(backend, SCRIPTS)
    analyst = make_onshape_analyst(backend, tags, run=runner, binary="claude")
    before, after = fix_and_retest(mock_system_1, REQUEST, analyst, backend, log_root=str(tmp_path / "runs"))
    assert before.reward.value == 0.6 and after is not None and after.reward.value == 1.0
    assert [c for c in fake.calls if c[0] == "create_version"] == [("create_version", "Rev B"), ("create_version", "Rev B")]
    assert fake.versions[VID] == {}                                       # the tested version is never edited

    events = read_events(tmp_path / "runs" / "t-revA" / "events.jsonl")
    patches = [e.payload for e in events if e.type == "patch_proposed"]
    assert [p["backend"] for p in patches] == ["onshape", "onshape"]
    assert patches[1]["edits"][-1]["summary"] == "door handle: style 'push_latch' -> 'bar'"
    calls = [e.payload for e in events if e.type == "tool_call"]
    assert [c["tool"] for c in calls if c["tool"].startswith("cad.")][:3] == ["cad.get_features", "cad.update_feature", "cad.check"]
    assert any(c["tool"] == "cad.submit_fix" and c.get("error_kind") == "bad_args" for c in calls)   # the early submit
    turns = [e.payload for e in events if e.type == "model_turn"]
    assert len(turns) == 2 and {t["stage"] for t in turns} == {"ANALYZE"} and turns[0]["tokens_out"] == 1200


def test_the_command_only_offers_the_cad_tools(setup, tmp_path):
    _, backend, tags = setup
    cmd = onshape_command("claude", str(tmp_path / "mcp.json"), "claude-opus-5-5", "high", 5)
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__rav-cad" and cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--max-budget-usd") + 1] == "5"


def test_a_session_without_submit_hands_the_finding_to_a_person(setup, tmp_path):
    fake, backend, tags = setup
    runner = ScriptedCadSession(backend, {"button_2": [("get_features", {})], "door": [("check", {})]})
    before, after = fix_and_retest(mock_system_1, REQUEST, make_onshape_analyst(backend, tags, run=runner, binary="claude"),
                                   backend, log_root=str(tmp_path / "runs"))
    assert after is None
    texts = [e.payload["text"] for e in read_events(tmp_path / "runs" / "t-revA" / "events.jsonl") if e.type == "message"]
    assert sum("ended without submit_fix" in t for t in texts) == 2


def test_no_onshape_access_means_no_patch_and_a_clear_reason(setup, tmp_path):
    _, backend, tags = setup
    backend.open_branch = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no network"))
    before, after = fix_and_retest(mock_system_1, REQUEST, make_onshape_analyst(backend, tags, run=lambda *a: None, binary="claude"),
                                   backend, log_root=str(tmp_path / "runs"))
    assert after is None
    events = read_events(tmp_path / "runs" / "t-revA" / "events.jsonl")
    assert any("couldn't open a branch to work on" in (e.payload.get("text") or "") for e in events if e.type == "model_turn")


def test_a_failed_cad_session_is_logged_as_the_pipelines_fault(setup, tmp_path):
    _, backend, tags = setup
    broken = lambda cmd, stdin, t: SimpleNamespace(returncode=1, stdout="", stderr="Not logged in")   # noqa: E731
    fix_and_retest(mock_system_1, REQUEST, make_onshape_analyst(backend, tags, run=broken, binary="claude"),
                   backend, log_root=str(tmp_path / "runs"))
    turns = [e.payload for e in read_events(tmp_path / "runs" / "t-revA" / "events.jsonl") if e.type == "model_turn"]
    assert turns and all((t["error_kind"], t["layer"]) == ("api_error", "pipeline") for t in turns)
