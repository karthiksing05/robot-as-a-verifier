"""The analysts. The model analyst runs against a scripted client here, so these need no network or API key;
test_live_model_finds_both_planted_faults is the one that calls the real API, and only when asked to."""
import json
import os
import pathlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from rav_cad import ParamsBackend
from rav_contracts import RootCause, TestRequest
from rav_harness.analyst import build_prompt, cli_analyst, model_analyst, rule_analyst, similar_controls
from rav_harness.loop import AnalystContext, _outcomes, fix_and_retest, run_test
from rav_harness.mock import mock_system_1
from rav_harness.runlog import RunLog, read_events
from rav_harness.trace import Tracer

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUEST = TestRequest(request_id="t", product="box", revision="A")

# A CadQuery-shaped parameter list (dotted paths), small enough to read
PARAMS = {"rev": "A", "shell.wall": 3.5, "features.display.module": "lcd1602",
          **{f"features.button_{i}.{k}": v for i in (1, 2, 3) for k, v in (("clearance", 0.15 if i == 2 else 0.40), ("travel", 1.2))},
          "features.door.handle_style": "tab", "features.door.gap": 0.5}


def fake_check(patch):
    """Stands in for CadQueryBackend.check: the posture's step limit, and the three handle styles."""
    c = patch.changes[0]
    if c.param.endswith(".clearance") and abs(c.to_value - c.from_value) > 0.25 + 1e-9:
        return [f"{c.param} changes by {abs(c.to_value - c.from_value):g} mm; the posture allows 0.25"]
    if c.param.endswith("handle_style") and c.to_value not in ("tab", "bar", "push_latch"):
        return [f"handle style must be 'tab', 'bar' or 'push_latch', got {c.to_value!r}"]
    return []


@pytest.fixture
def run(tmp_path):
    """Rev A on the mock: two findings (button_2 binds, the door needs a pinch) and every step's measurements."""
    log = RunLog("t-revA", tmp_path)
    report = run_test(mock_system_1("A"), REQUEST, log)
    return SimpleNamespace(log=log, findings={f.target: f for f in report.findings}, outcomes=_outcomes(log))


def context(run, target, params=PARAMS, check=fake_check, tracer=True):
    t = Tracer(run.log, caller="model") if tracer else None
    return AnalystContext(run.findings[target], params, run.outcomes, check, "Change one parameter.", t)


# --- a scripted client ------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=SimpleNamespace(input_tokens=900, output_tokens=60))


def use(name, n=1, **args):
    return SimpleNamespace(type="tool_use", id=f"tu{n}", name=name, input=args)


def text(t):
    return SimpleNamespace(type="text", text=t)


def submit(change, n=1, **kw):
    return use("submit_diagnosis", n, root_cause=kw.get("cause", "bore clearance too small, the cap binds"),
               confidence=kw.get("confidence", 0.8), hypotheses=[{"cause": "clearance too small", "p": 0.8}],
               evidence=["6.0 N at 0.3 mm"], change=change)


def events(run, type_):
    return [e.payload for e in read_events(run.log.path) if e.type == type_]


# --- the rule analyst -----------------------------------------------------------------------------------------

def test_rule_analyst_takes_names_and_values_from_read_params(run, tmp_path):
    flat = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path)).read_params()
    _, patch = rule_analyst(context(run, "button_2", params=flat))
    assert patch.backend == "params"
    assert (patch.changes[0].param, patch.changes[0].from_value) == ("button_clearance[1]", 0.15)
    # a dotted path listed by the backend wins, and from_value is whatever the backend says, not a remembered 0.15
    _, patch = rule_analyst(context(run, "button_2", params={**PARAMS, "rev": "B", "features.button_2.clearance": 0.25}))
    assert patch.backend == "cadquery" and (patch.revision_from, patch.revision_to) == ("B", "C")
    assert (patch.changes[0].param, patch.changes[0].from_value) == ("features.button_2.clearance", 0.25)


# --- what the model is shown --------------------------------------------------------------------------------------

def test_prompt_compares_similar_controls_when_the_run_tested_them(run):
    ctx = context(run, "button_2")
    assert similar_controls(ctx) == ["button_1", "button_3"]
    prompt = build_prompt(ctx)
    assert "The same kind of control, tested in this run" in prompt and "button_1: passed" in prompt
    assert "features.button_1.clearance = 0.4" in prompt and "features.button_2.clearance = 0.15" in prompt
    assert "features.door.handle_style" not in prompt          # only the target, its siblings and the shell


def test_prompt_for_a_lone_control_drops_the_comparison(run):
    ctx = context(run, "door")
    assert similar_controls(ctx) == []
    prompt = build_prompt(ctx)
    assert "The same kind of control" not in prompt
    assert "No similar control was tested" in prompt and "lower confidence" in prompt
    assert "features.door.handle_style = 'tab'" in prompt and "features.button_1.clearance" not in prompt


# --- the model analyst, scripted ----------------------------------------------------------------------------------

def test_model_analyst_first_time_right(run):
    client = FakeClient(reply(submit({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "about 4 N"})))
    cause, patch = model_analyst(context(run, "button_2"), client=client)
    c = patch.changes[0]
    assert (c.param, c.from_value, c.to_value) == ("features.button_2.clearance", 0.15, 0.40)
    assert patch.backend == "cadquery" and (patch.revision_from, patch.revision_to) == ("A", "B") and patch.verify_with == ["s2"]
    assert cause.finding == run.findings["button_2"].id and cause.confidence == 0.8
    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5" and request["tool_choice"] == {"type": "auto"}
    assert events(run, "model_turn")[0]["tokens_in"] == 900
    assert [e["tool"] for e in events(run, "tool_call")] == ["submit_diagnosis"]


def test_model_analyst_fixes_a_change_the_check_refuses(run):
    client = FakeClient(
        reply(use("check_patch", 1, param="features.button_2.clearance", to_value=0.70)),
        reply(submit({"param": "features.button_2.clearance", "to_value": 0.70, "predicted": "x"}, n=2)),
        reply(submit({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "about 4 N"}, n=3)))
    _, patch = model_analyst(context(run, "button_2"), client=client)
    assert patch.changes[0].to_value == 0.40
    probe = client.requests[1]["messages"][-1]["content"][0]
    assert probe["content"].startswith("refused:") and "posture allows 0.25" in probe["content"] and "is_error" not in probe
    refused = client.requests[2]["messages"][-1]["content"][0]
    assert refused["is_error"] and "the CAD check refuses this change" in refused["content"]
    assert [e.get("error_kind") for e in events(run, "tool_call")] == [None, "bad_args", None]


def test_model_analyst_unknown_parameter_is_the_models_error(run):
    client = FakeClient(reply(use("check_patch", 1, param="features.button_2.diameter", to_value=17)),
                        reply(submit({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "x"}, n=2)))
    _, patch = model_analyst(context(run, "button_2"), client=client)
    assert patch is not None
    call = events(run, "tool_call")[0]
    assert (call["error_kind"], call["layer"]) == ("unknown_target", "model")


def test_model_analyst_lone_control(run):
    client = FakeClient(reply(submit({"param": "features.door.handle_style", "to_value": "bar", "predicted": "hook and pull"},
                                     cause="the tab needs a pinch", confidence=0.6)))
    cause, patch = model_analyst(context(run, "door"), client=client)
    assert (patch.changes[0].param, patch.changes[0].from_value, patch.changes[0].to_value) == ("features.door.handle_style", "tab", "bar")
    assert "No similar control was tested" in client.requests[0]["messages"][0]["content"]


def test_model_analyst_can_say_no_cad_fix(run):
    client = FakeClient(reply(submit(None, cause="force and travel look normal; the switch wiring is suspect")))
    cause, patch = model_analyst(context(run, "button_2"), client=client)
    assert patch is None and "wiring" in cause.root_cause


def test_fix_loop_skips_a_finding_with_no_cad_fix(tmp_path):
    params = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path))
    nothing = lambda ctx: (RootCause(finding=ctx.finding.id, evidence=[], hypotheses=[], root_cause="the arm slipped", confidence=0.5), None)  # noqa: E731
    before, after = fix_and_retest(mock_system_1, REQUEST, nothing, params, log_root=str(tmp_path))
    assert after is None and params.read_params()["button_clearance"][1] == 0.15
    texts = [e.payload["text"] for e in read_events(tmp_path / "t-revA" / "events.jsonl") if e.type == "message"]
    assert sum("no CAD fix" in t for t in texts) == 2


def test_model_analyst_falls_back_to_rules_when_the_api_fails(run):
    anthropic = pytest.importorskip("anthropic")
    client = FakeClient(anthropic.APIConnectionError(request=None))
    _, patch = model_analyst(context(run, "button_2"), client=client)
    assert patch.changes[0].param == "features.button_2.clearance"           # the rule analyst's answer
    turn = events(run, "model_turn")[0]
    assert (turn["error_kind"], turn["layer"]) == ("api_error", "pipeline")


def test_model_analyst_falls_back_when_the_model_declines(run):
    client = FakeClient(reply(text("I can't help with that."), stop="refusal"))
    _, patch = model_analyst(context(run, "door"), client=client)
    assert patch.changes[0].to_value == "push_latch"
    assert events(run, "model_turn")[0]["error_kind"] == "refused"


def test_model_analyst_gives_up_after_its_turns(run):
    client = FakeClient(reply(text("Thinking about it."), stop="end_turn"), reply(text("Still thinking."), stop="end_turn"))
    cause, patch = model_analyst(context(run, "button_2"), client=client, max_turns=2)
    assert patch is None and cause.confidence == 0.0 and "a person should look" in cause.root_cause
    assert client.requests[1]["messages"][-1] == {"role": "user", "content": "Finish by calling submit_diagnosis."}
    assert [t["error_kind"] for t in events(run, "model_turn")] == ["malformed", "malformed"]


def test_fix_loop_with_the_model_analyst_and_the_params_file(tmp_path):
    """The whole loop with the model analyst at the controls (scripted), patching the flat params file."""
    params = ParamsBackend(shutil.copy(ROOT / "subjects/appliance/cad/params.rev_a.json", tmp_path))
    client = FakeClient(reply(submit({"param": "button_clearance[1]", "to_value": 0.40, "predicted": "about 4 N"})),
                        reply(submit({"param": "handle_style", "to_value": "push_latch", "predicted": "flat push"}, n=2)))
    before, after = fix_and_retest(mock_system_1, REQUEST, lambda ctx: model_analyst(ctx, client=client), params, log_root=str(tmp_path))
    assert before.reward.value == 0.6 and after.reward.value == 1.0
    assert params.read_params()["button_clearance"][1] == 0.40 and params.read_params()["handle_style"] == "push_latch"
    log = read_events(tmp_path / "t-revA" / "events.jsonl")
    turns = [e.payload for e in log if e.type == "model_turn"]
    assert len(turns) == 2 and {t["stage"] for t in turns} == {"ANALYZE"} and [t["step"] for t in turns] == ["s2", "s4"]
    assert (tmp_path / "t-revA" / "model" / "turn-1.json").exists()


# --- the CLI analyst, scripted ---------------------------------------------------------------------------------------

class FakeClaude:
    """Stands in for `claude -p`: returns scripted JSON results (or raises), and keeps every command and stdin."""
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, cmd, stdin, timeout_s):
        self.calls.append((cmd, stdin))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        if isinstance(a, SimpleNamespace):
            return a
        out = {"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn", "duration_ms": 4200,
               "usage": {"input_tokens": 1500, "output_tokens": 300}, "result": json.dumps(a), "structured_output": a}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


def diagnosis(change, **kw):
    return {"root_cause": kw.get("cause", "bore clearance too small, the cap binds"), "confidence": kw.get("confidence", 0.8),
            "hypotheses": [{"cause": "clearance too small", "p": 0.8}], "evidence": ["6.0 N at 0.3 mm"], "change": change}


def test_cli_analyst_first_time_right(run):
    claude = FakeClaude(diagnosis({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "about 4 N"}))
    cause, patch = cli_analyst(context(run, "button_2"), run=claude)
    c = patch.changes[0]
    assert (c.param, c.from_value, c.to_value, patch.backend) == ("features.button_2.clearance", 0.15, 0.40, "cadquery")
    cmd, stdin = claude.calls[0]
    assert cmd[1:4] == ["-p", "--output-format", "json"] and cmd[cmd.index("--tools") + 1] == ""
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"][0] == "root_cause"
    assert "The same kind of control, tested in this run" in stdin
    turn = events(run, "model_turn")[0]
    assert (turn["tokens_in"], turn["latency_ms"]) == (1500, 4200)
    assert (run.log.dir / "model" / "turn-1.json").exists()


def test_cli_analyst_asks_again_when_the_check_refuses(run):
    claude = FakeClaude(diagnosis({"param": "features.button_2.clearance", "to_value": 0.70, "predicted": "x"}),
                        diagnosis({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "about 4 N"}))
    _, patch = cli_analyst(context(run, "button_2"), run=claude)
    assert patch.changes[0].to_value == 0.40
    retry = claude.calls[1][1]
    assert "Your previous answer was refused" in retry and "posture allows 0.25" in retry and '"to_value": 0.7' in retry
    assert [e.get("error_kind") for e in events(run, "tool_call")] == ["bad_args", None]


def test_cli_analyst_unknown_parameter_then_fixed(run):
    claude = FakeClaude(diagnosis({"param": "features.button_2.diameter", "to_value": 17, "predicted": "x"}),
                        diagnosis({"param": "features.button_2.clearance", "to_value": 0.40, "predicted": "x"}))
    _, patch = cli_analyst(context(run, "button_2"), run=claude)
    assert patch.changes[0].param == "features.button_2.clearance"
    assert events(run, "tool_call")[0]["error_kind"] == "unknown_target"


def test_cli_analyst_no_cad_fix(run):
    claude = FakeClaude(diagnosis(None, cause="travel was full and force normal; check the switch wiring"))
    cause, patch = cli_analyst(context(run, "button_2"), run=claude)
    assert patch is None and "wiring" in cause.root_cause


@pytest.mark.parametrize("failure, kind", [
    (SimpleNamespace(returncode=1, stdout="", stderr="Not logged in. Run claude to sign in."), "api_error"),
    (SimpleNamespace(returncode=0, stdout=json.dumps({"is_error": True, "result": "usage limit reached"}), stderr=""), "api_error"),
    (subprocess.TimeoutExpired(cmd="claude", timeout=300), "timeout"),
    (FileNotFoundError("claude"), "api_error"),
])
def test_cli_analyst_falls_back_to_rules(run, failure, kind):
    _, patch = cli_analyst(context(run, "button_2"), run=FakeClaude(failure))
    assert patch.changes[0].param == "features.button_2.clearance"           # the rule analyst's answer
    turn = events(run, "model_turn")[0]
    assert (turn["error_kind"], turn["layer"]) == (kind, "pipeline")


def test_cli_analyst_without_the_cli_falls_back(run, monkeypatch):
    monkeypatch.delenv("RAV_CLAUDE_BIN", raising=False)
    monkeypatch.setattr("rav_harness.analyst.shutil.which", lambda _name: None)
    _, patch = cli_analyst(context(run, "door"))
    assert patch.changes[0].to_value == "push_latch"
    assert "isn't on PATH" in events(run, "model_turn")[0]["text"]


def test_cli_analyst_gives_up_after_its_tries(run):
    bad = {"param": "features.button_2.clearance", "to_value": 0.90, "predicted": "x"}
    cause, patch = cli_analyst(context(run, "button_2"), run=FakeClaude(diagnosis(bad), diagnosis(bad)), max_tries=2)
    assert patch is None and "a person should look" in cause.root_cause


# --- the real model, only when asked -------------------------------------------------------------------------------

@pytest.mark.model
@pytest.mark.skipif(not os.environ.get("RAV_MODEL_TESTS"), reason="set RAV_MODEL_TESTS=1 to call the real model")
def test_live_cli_finds_both_planted_faults(run, tmp_path):
    """The real model through `claude -p` on the Claude Code login, against the real CadQuery spec and its checks."""
    pytest.importorskip("cadquery")
    if not shutil.which("claude"):
        pytest.skip("the claude CLI isn't installed")
    from rav_cad import CadQueryBackend
    cad = CadQueryBackend(shutil.copy(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml", tmp_path), interference=False)
    found = {}
    for target in ("button_2", "door"):
        ctx = AnalystContext(run.findings[target], cad.read_params(), run.outcomes, cad.check, cad.rules(), Tracer(run.log, "model"))
        cause, patch = cli_analyst(ctx)
        turns = events(run, "model_turn")
        assert turns and turns[-1].get("error_kind") is None, f"fell back to the rules: {turns[-1]}"
        assert patch is not None and cad.check(patch) == [], cause.root_cause
        found[target] = (patch.changes[0].param, patch.changes[0].to_value, cause.confidence)
        print(f"\n{target}: {cause.root_cause}\n  -> {found[target]}")
    assert found["button_2"][0] == "features.button_2.clearance"
    assert found["door"][0] == "features.door.handle_style"

@pytest.mark.model
@pytest.mark.skipif(not os.environ.get("RAV_MODEL_TESTS"), reason="set RAV_MODEL_TESTS=1 to call the real API")
def test_live_model_finds_both_planted_faults(run, tmp_path):
    pytest.importorskip("anthropic")
    pytest.importorskip("cadquery")
    from rav_cad import CadQueryBackend
    cad = CadQueryBackend(shutil.copy(ROOT / "subjects/appliance/cad/appliance.rev_a.yaml", tmp_path), interference=False)
    found = {}
    for target in ("button_2", "door"):
        ctx = AnalystContext(run.findings[target], cad.read_params(), run.outcomes, cad.check, cad.rules(), Tracer(run.log, "model"))
        _, patch = model_analyst(ctx)
        assert patch is not None and cad.check(patch) == []
        found[target] = patch.changes[0].param
    assert found == {"button_2": "features.button_2.clearance", "door": "features.door.handle_style"}
