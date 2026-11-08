"""The analyst: from a finding and the run's measurements to a root cause and, when a design change can fix it, one CAD patch.

Four analysts with the same signature (loop.Analyst):

- `make_onshape_analyst(backend, tags)` lets the model fix the real Onshape model itself, on a branch of its own,
  through the rav-cad MCP tools (rav_cad/onshape/mcp_server.py): edit features or variables, check, repeat, submit.
  The patch points at the checked branch; the harness approves and the backend turns it into the new version.

- `rule_analyst` knows the two planted faults. It is the default for `rav mock` and the fallback when the model can't
  be reached, so the demo runs without Wi-Fi.
- `cli_analyst` asks the model through the `claude` CLI (`claude -p`), on the Claude Code login: no API key. Our code
  checks each answer and asks again with the reasons when the CAD check refuses it.
- `model_analyst` asks the model through the API (needs an API key). It sees the failing step, the same numbers for similar controls when the run tested
  any, the target's parameters and the backend's rules. It can test a change with `check_patch` before it commits
  with `submit_diagnosis`, and every turn and tool call is traced so the Console can tell a model mistake from ours.

The model names a parameter and a new value. Code fills in from_value (from read_params), the revisions, the file and
the backend, so none of those can be wrong or stale.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from rav_contracts import CADPatch, Hypothesis, ParamChange, RootCause, StepOutcome

from .loop import Analyst, AnalystContext
from .trace import ToolRejected, Tracer

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"   # fallbacks="default": a declined request reruns on another model
_INDEXED = re.compile(r"^(\w+)\[(\d+)\]$")


# --- shared helpers -------------------------------------------------------------------------------------------

def _current(params: dict[str, Any], name: str) -> Any:
    """The parameter's value now. Dotted paths for CadQuery; `name[i]` for the flat params file. KeyError if unknown."""
    if name in params:
        return params[name]
    m = _INDEXED.match(name)
    if m and isinstance(params.get(m[1]), list) and int(m[2]) < len(params[m[1]]):
        return params[m[1]][int(m[2])]
    raise KeyError(name)


def _patch(ctx: AnalystContext, change: ParamChange) -> CADPatch:
    cadquery = change.param.startswith(("features.", "shell."))
    rev = str(ctx.params.get("rev", "A"))
    file = f"subjects/appliance/cad/appliance.rev_{rev.lower()}.yaml" if cadquery else "subjects/appliance/cad/params.rev_a.json"
    return CADPatch(file=file, revision_from=rev, revision_to=chr(ord(rev) + 1), changes=[change],
                    verify_with=ctx.finding.step_ids, backend="cadquery" if cadquery else "params")


def _change(ctx: AnalystContext, param: str, to_value: Any, unit: str | None = None, predicted: str | None = None) -> ParamChange:
    return ParamChange(param=param, from_value=_current(ctx.params, param), to_value=to_value, unit=unit, predicted=predicted)


# --- the rule analyst -----------------------------------------------------------------------------------------

def _pick(params: dict[str, Any], dotted: str, legacy: str) -> str:
    """CadQueryBackend lists dotted paths; ParamsBackend only has the flat file, so the old name is its fallback."""
    return dotted if dotted in params else legacy


def rule_analyst(ctx: AnalystContext) -> tuple[RootCause, CADPatch | None]:
    """The reasoning the real analyst has to produce from logs, for the two planted faults only."""
    finding = ctx.finding
    if finding.target == "button_2":
        name = _pick(ctx.params, "features.button_2.clearance", "button_clearance[1]")
        change = _change(ctx, name, 0.40, unit="mm", predicted="about 3 N with a click")
        cause = f"{name} = {change.from_value} mm is below printer wall growth, so the cap binds"
        hypotheses = [Hypothesis(cause="hole clearance too small", p=0.78, check=f"{change.from_value} mm against 0.40 mm on its siblings"),
                      Hypothesis(cause="switch failed", p=0.12, ruled_out="force rose before switch travel")]
    elif finding.target == "door":
        name = _pick(ctx.params, "features.door.handle_style", "handle_style")
        change = _change(ctx, name, "push_latch", predicted="opens with a flat pad under 3 N")
        cause = f"{name} = {change.from_value} offers nothing for a flat pad to push; the spec bans pinching"
        hypotheses = [Hypothesis(cause="no pad-operable handle", p=0.9, check="spec rule against the skill whitelist")]
    else:
        return RootCause(finding=finding.id, evidence=[finding.what_happened], hypotheses=[],
                         root_cause=f"no rule covers {finding.target}; a person should look", confidence=0.0), None
    root = RootCause(finding=finding.id, evidence=[finding.what_happened], hypotheses=hypotheses, root_cause=cause, confidence=0.9)
    return root, _patch(ctx, change)


# --- what the model sees ----------------------------------------------------------------------------------------

SYSTEM = """You diagnose why a robot's test of an appliance failed, and propose the smallest CAD change that fixes it.

The robot pressed, flipped, slid or turned each control and its sensors decided pass or fail; those verdicts are facts.
Your job is the cause. Work from the measurements: force, travel, why the move stopped, what the appliance reported.
Compare with similar controls when you are given them. When you aren't, judge the failing step against the control's
own parameters (for example measured travel against the designed travel), the rules, and the shape of the force trace
(force rising with almost no travel means something binds; full travel with no readout points at the switch or wiring).

Not every failure is a design problem. If the evidence points at perception, the arm, wiring or firmware, submit with
change set to null and say what a person should check.

The parameter must be one listed in the prompt. Change one parameter, within the limits."""

SYSTEM_API = SYSTEM + """

You may call check_patch to test a change against the rebuilt model before you commit. Finish by calling
submit_diagnosis exactly once."""

SYSTEM_CLI = SYSTEM + """

Answer with the diagnosis as JSON in the required shape. Your change is checked against the rebuilt model; if it is
refused you will get the reasons and can answer again."""


def _kind_of(params: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Feature id -> its parameter names. Features of one type share the same names, so this groups similar controls."""
    names: dict[str, set[str]] = {}
    for key, value in params.items():
        parts = key.split(".")
        if len(parts) == 3 and parts[0] == "features":
            names.setdefault(parts[1], set()).add(parts[2])
        elif len(parts) == 2 and parts[0] == "controls" and isinstance(value, dict):   # Onshape: from the tag file
            names.setdefault(parts[1], set()).add(f"skill:{value.get('skill')}")
    return {fid: frozenset(n) for fid, n in names.items()}


def similar_controls(ctx: AnalystContext) -> list[str]:
    """Other controls of the target's type that this run actually tested. Empty when there are none: a lone control."""
    kinds = _kind_of(ctx.params)
    target = ctx.finding.target
    tested = {o.verdict.target for o in ctx.outcomes}
    if target not in kinds:
        return []
    return sorted(fid for fid in tested if fid != target and kinds.get(fid) == kinds[target])


def _step_line(o: StepOutcome) -> str:
    t, v = o.trace, o.verdict
    curve = t.force_trace[:: max(1, len(t.force_trace) // 12)][:12]
    parts = [f"{v.step} {v.target}: {v.status}" + (f" ({v.label})" if v.label else ""),
             f"stop: {t.stop_reason}", f"peak {t.peak_force_n} N", f"travel {t.travel_mm} mm"]
    if curve:
        parts.append("force (s, N): " + ", ".join(f"({s:g}, {n:g})" for s, n in curve))
    parts.append(f"readout: {json.dumps(t.readout_change) if t.readout_change else 'no change'}")
    parts.append(f"verdict: {v.reason}")
    return "- " + "; ".join(parts)


def _params_for(params: dict[str, Any], features: list[str]) -> dict[str, Any]:
    if not any(k.startswith("features.") for k in params):     # the flat params file: small, send it whole
        return params
    keep = tuple(f"features.{f}." for f in features) + ("shell.",)
    return {k: v for k, v in params.items() if k.startswith(keep) or k == "rev"}


def build_prompt(ctx: AnalystContext) -> str:
    f = ctx.finding
    failing = [o for o in ctx.outcomes if o.verdict.step in f.step_ids]
    similar = similar_controls(ctx)
    sections = [f"Finding {f.id} on {f.target} ({f.label}, {f.severity}): {f.what_happened}"]
    if f.manual_says:
        sections.append(f"The manual says: {f.manual_says}")
    sections.append("The failing step:\n" + ("\n".join(_step_line(o) for o in failing) or "- (no measurements logged)"))
    if similar:
        rows = [o for o in ctx.outcomes if o.verdict.target in similar]
        sections.append("The same kind of control, tested in this run:\n" + "\n".join(_step_line(o) for o in rows))
    else:
        sections.append("No similar control was tested in this run, so there is nothing to compare against. Judge from "
                        "the failing step, the control's own parameters and the rules. Report a lower confidence, and "
                        "give your change as the single most likely fix to test: the retest on the new revision is the "
                        "real check, and the patch stays only if the score rises.")
    shown = _params_for(ctx.params, [f.target, *similar])
    sections.append("Parameters you may change, with their current values:\n" + "\n".join(f"{k} = {v!r}" for k, v in shown.items()))
    if ctx.rules:
        sections.append("Rules:\n" + ctx.rules)
    return "\n\n".join(sections)


TOOLS = [
    {"name": "check_patch",
     "description": "Test one parameter change against the rebuilt CAD model and its checks, without applying it. "
                    "Returns 'ok' or the reasons it would be refused. The current value is filled in for you.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["param", "to_value"],
                      "properties": {"param": {"type": "string", "description": "A parameter name exactly as listed"},
                                     "to_value": {"type": ["number", "string", "boolean"]}}}},
    {"name": "submit_diagnosis",
     "description": "Your final answer, called once. change is null when no CAD change fixes this finding.",
     "input_schema": {
         "type": "object", "additionalProperties": False,
         "required": ["root_cause", "confidence", "hypotheses", "evidence", "change"],
         "properties": {
             "root_cause": {"type": "string", "description": "One sentence: what is wrong and why it causes the failure"},
             "confidence": {"type": "number", "minimum": 0, "maximum": 1},
             "hypotheses": {"type": "array", "items": {
                 "type": "object", "additionalProperties": False, "required": ["cause", "p"],
                 "properties": {"cause": {"type": "string"}, "p": {"type": "number", "minimum": 0, "maximum": 1},
                                "check": {"type": "string", "description": "the measurement that supports it"},
                                "ruled_out": {"type": "string", "description": "why it was ruled out, if it was"}}}},
             "evidence": {"type": "array", "items": {"type": "string"}, "description": "The measurements you relied on"},
             "change": {"anyOf": [{"type": "null"}, {
                 "type": "object", "additionalProperties": False, "required": ["param", "to_value", "predicted"],
                 "properties": {"param": {"type": "string"}, "to_value": {"type": ["number", "string", "boolean"]},
                                "unit": {"type": "string"},
                                "predicted": {"type": "string", "description": "What the retest should measure after the fix"}}}]},
         }}},
]


# --- the model analyst --------------------------------------------------------------------------------------------

def _known(ctx: AnalystContext, param: Any) -> str:
    try:
        _current(ctx.params, str(param))
    except KeyError:
        raise ToolRejected("unknown_target", f"{param} is not a parameter of this model; use a name from the list") from None
    return str(param)


def _check_patch(ctx: AnalystContext, args: dict) -> str:
    if "param" not in args or "to_value" not in args:
        raise ToolRejected("bad_args", "check_patch needs param and to_value")
    patch = _patch(ctx, _change(ctx, _known(ctx, args["param"]), args["to_value"]))
    problems = ctx.check(patch)
    return "ok" if not problems else "refused: " + "; ".join(problems)


def _submit(ctx: AnalystContext, args: dict) -> tuple[RootCause, CADPatch | None]:
    try:
        root = RootCause(finding=ctx.finding.id, evidence=list(args.get("evidence") or [ctx.finding.what_happened]),
                         hypotheses=[Hypothesis(**h) for h in args.get("hypotheses", [])],
                         root_cause=args["root_cause"], confidence=float(args["confidence"]))
    except (KeyError, TypeError, ValueError, ValidationError) as e:
        raise ToolRejected("malformed", f"submit_diagnosis didn't match its schema: {e}") from None
    c = args.get("change")
    if c is None:
        return root, None
    if not isinstance(c, dict) or "param" not in c or "to_value" not in c:
        raise ToolRejected("malformed", "change needs param, to_value and predicted, or null")
    patch = _patch(ctx, _change(ctx, _known(ctx, c["param"]), c["to_value"], c.get("unit"), c.get("predicted")))
    problems = ctx.check(patch)
    if problems:
        raise ToolRejected("bad_args", "the CAD check refuses this change: " + "; ".join(problems)
                           + ". Fix it, or submit change null if no allowed change fixes the finding.")
    return root, patch


def _no_such_tool(name: str) -> str:
    raise ToolRejected("unknown_tool", f"there is no tool called {name}")


def _jsonable(value: Any) -> Any:
    """SDK objects to plain JSON for the saved turn, so a bad decision can be replayed against its exact context."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _call(tracer: Tracer | None, tool: str, args: dict, fn: Callable[[], Any], turn: str | None) -> Any:
    return tracer.call(tool, args, fn, turn=turn) if tracer else fn()


def _turn(tracer: Tracer | None, model: str, **fields: Any) -> str | None:
    return tracer.turn(model, **fields) if tracer else None


def _fallback(ctx: AnalystContext, model: str, kind: str, why: str) -> tuple[RootCause, CADPatch | None]:
    _turn(ctx.tracer, model, error_kind=kind, text=f"{why}; falling back to the rule analyst")
    return rule_analyst(ctx)


def model_analyst(ctx: AnalystContext, client: Any = None, model: str = MODEL, max_turns: int = 4,
                  effort: str = "high") -> tuple[RootCause, CADPatch | None]:
    """Asks the model for a root cause and at most one patch that passes the CAD check. See the module docstring."""
    try:
        import anthropic
        api_errors: tuple[type[Exception], ...] = (anthropic.APIError,)
    except ImportError:            # fine with an injected client (the tests); the real client needs the package
        anthropic, api_errors = None, ()
    if client is None:
        if anthropic is None:
            return _fallback(ctx, model, "api_error", "the anthropic package isn't installed (uv sync --extra model)")
        client = anthropic.Anthropic()

    prompt = build_prompt(ctx)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    new_input = prompt
    for _ in range(max_turns):
        request = {"model": model, "max_tokens": 16000, "system": SYSTEM_API, "tools": TOOLS, "tool_choice": {"type": "auto"},
                   "output_config": {"effort": effort}, "betas": [FALLBACK_BETA], "fallbacks": "default"}
        start = time.monotonic()
        try:
            response = client.beta.messages.create(messages=messages, **request)
        except api_errors as e:
            return _fallback(ctx, model, "api_error", f"{type(e).__name__}: {e}")
        latency = round((time.monotonic() - start) * 1000, 1)

        uses = [b for b in response.content if b.type == "tool_use"]
        text = "\n".join(b.text for b in response.content if b.type == "text") or None
        kind = ("refused" if response.stop_reason == "refusal" else "max_tokens" if response.stop_reason == "max_tokens"
                else None if uses else "malformed")
        usage = getattr(response, "usage", None)
        turn = _turn(ctx.tracer, model, input=new_input, text=text, stop_reason=response.stop_reason, error_kind=kind,
                     tokens_in=getattr(usage, "input_tokens", None), tokens_out=getattr(usage, "output_tokens", None),
                     latency_ms=latency, raw=_jsonable({"request": {**request, "messages": messages}, "response": response}))
        if response.stop_reason == "refusal":
            return _fallback(ctx, model, "refused", "the model declined")

        messages.append({"role": "assistant", "content": response.content})    # the whole content, thinking included
        if not uses:
            new_input = "Finish by calling submit_diagnosis."
            messages.append({"role": "user", "content": new_input})
            continue
        results = []
        for use in uses:
            args = use.input if isinstance(use.input, dict) else {}
            try:
                if use.name == "check_patch":
                    out = _call(ctx.tracer, "cad.check_patch", args, lambda a=args: _check_patch(ctx, a), turn)
                elif use.name == "submit_diagnosis":
                    return _call(ctx.tracer, "submit_diagnosis", args, lambda a=args: _submit(ctx, a), turn)
                else:
                    out = _call(ctx.tracer, use.name, args, lambda n=use.name: _no_such_tool(n), turn)
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": str(out)})
            except ToolRejected as e:
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": str(e), "is_error": True})
        new_input = "; ".join(r["content"] for r in results)
        messages.append({"role": "user", "content": results})

    return _gave_up(ctx, max_turns)


def _gave_up(ctx: AnalystContext, turns: int) -> tuple[RootCause, None]:
    return RootCause(finding=ctx.finding.id, evidence=[ctx.finding.what_happened], hypotheses=[],
                     root_cause=f"the analyst used its {turns} turns without a diagnosis that passes the checks; "
                                "a person should look", confidence=0.0), None


# --- the CLI analyst: the same model through `claude -p`, on the Claude Code login instead of an API key ---------

DIAGNOSIS_SCHEMA = TOOLS[1]["input_schema"]
Runner = Callable[[list[str], str, float], Any]   # (command, stdin, timeout_s) -> has returncode, stdout, stderr


def _run_claude(cmd: list[str], stdin: str, timeout_s: float) -> subprocess.CompletedProcess:
    # run from the temp folder so no project CLAUDE.md or settings shape the answer
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout_s, cwd=tempfile.gettempdir())


def claude_command(binary: str, model: str, effort: str) -> list[str]:
    """Headless Claude Code with every built-in tool and MCP server off: it only reads the prompt and answers."""
    return [binary, "-p", "--output-format", "json", "--json-schema", json.dumps(DIAGNOSIS_SCHEMA),
            "--system-prompt", SYSTEM_CLI, "--model", model, "--effort", effort, "--tools", "",
            "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"]


def cli_analyst(ctx: AnalystContext, run: Runner | None = None, model: str = MODEL, max_tries: int = 4,
                effort: str = "high", timeout_s: float = 300.0, binary: str | None = None) -> tuple[RootCause, CADPatch | None]:
    """Like model_analyst, through the `claude` CLI. The model can't call check_patch mid-thought here, so our code
    checks each answer and, if the check refuses it, asks again with the reasons, up to `max_tries` calls."""
    binary = binary or os.environ.get("RAV_CLAUDE_BIN") or shutil.which("claude")
    if run is None:
        if not binary:
            return _fallback(ctx, model, "api_error", "the claude CLI isn't on PATH (install Claude Code, or set RAV_CLAUDE_BIN)")
        run = _run_claude
    cmd = claude_command(binary or "claude", model, effort)

    base = build_prompt(ctx)
    prompt, new_input = base, base
    for _ in range(max_tries):
        start = time.monotonic()
        try:
            proc = run(cmd, prompt, timeout_s)
        except subprocess.TimeoutExpired:
            return _fallback(ctx, model, "timeout", f"claude -p gave no answer in {timeout_s:g} s")
        except OSError as e:
            return _fallback(ctx, model, "api_error", f"couldn't start claude: {e}")
        try:
            out = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            out = None
        if proc.returncode != 0 or not isinstance(out, dict) or out.get("is_error"):
            why = (out or {}).get("result") if isinstance(out, dict) else None
            return _fallback(ctx, model, "api_error",
                             f"claude -p failed (exit {proc.returncode}): {why or (proc.stderr or '').strip()[:500] or 'no output'}")

        answer = out.get("structured_output")
        usage = out.get("usage") or {}
        turn = _turn(ctx.tracer, model, input=new_input, text=json.dumps(answer) if answer is not None else out.get("result"),
                     stop_reason=out.get("stop_reason"), error_kind=None if isinstance(answer, dict) else "malformed",
                     tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
                     latency_ms=out.get("duration_ms") or round((time.monotonic() - start) * 1000, 1),
                     raw={"command": cmd, "stdin": prompt, "response": out})
        if not isinstance(answer, dict):
            feedback = "Your answer wasn't the JSON object in the required shape."
        else:
            try:
                return _call(ctx.tracer, "submit_diagnosis", answer, lambda a=answer: _submit(ctx, a), turn)
            except ToolRejected as e:
                feedback = str(e)
        new_input = f"Your previous answer was refused: {feedback}"
        prompt = (f"{base}\n\nYour previous answer:\n{json.dumps(answer)}\n\n{new_input}\n"
                  "Answer again with the corrected diagnosis.")

    return _gave_up(ctx, max_tries)


# --- the Onshape analyst: the model edits the real CAD on its own branch, through the rav-cad MCP tools ---------

SYSTEM_ONSHAPE = SYSTEM.replace("The parameter must be one listed in the prompt. Change one parameter, within the limits.", "") + """
You fix the product in Onshape yourself, with the rav-cad tools, on a branch of your own: the version the robot
tested is never changed. Work like an engineer at a CAD station:
1. list_controls and get_features to find the parts and features behind the failing control; measure_gap and
   part_size to measure what the evidence points at; render to look.
2. Make the smallest change that removes the root cause: update_feature, set_variable, or add_feature and
   delete_feature when a parameter can't express the fix. Change parts of the failing control only, and only parts
   it may reprint; never the body. Imported parts have no feature history: change them with features that act on
   their faces (for example Onshape's move-face offset, or an extrude that adds or removes material), selecting
   faces by the ids list_faces gives. get_features shows how existing features are written.
3. check() runs the robot's checks on your branch. Read its reasons, fix, and check again until it passes.
4. submit_fix with your root cause, confidence, hypotheses, evidence and what the retest should measure. If no CAD
   change can fix the finding (perception, the arm, wiring, firmware), submit_fix with no_cad_fix=true instead.
Finish with submit_fix; there is no other answer."""


SYSTEM_LOCAL = SYSTEM.replace("The parameter must be one listed in the prompt. Change one parameter, within the limits.", "") + """
You fix the product yourself by writing CadQuery code, with the rav-cad-local tools, in a workspace of your own: the
revision the robot tested is never changed. Work like an engineer at a CAD station:
1. list_controls to find the failing control's parts and which you may reprint; get_part and list_faces to see a
   part's shape (faces with their planes, cylinders and boxes); measure_gap and part_size to measure what the
   evidence points at; render to look.
2. Make the smallest change that removes the root cause with write_part: CadQuery code that sets `result` to the
   new solid for one reprintable part. Start from `old` (the part as it is, in the assembly frame) and change only
   what the fix needs: cut a wider bore, fuse a hook or lip, trim an edge. Place new geometry from the faces and
   boxes you measured. Change parts of the failing control only, never the body. If the code fails, read the error
   and fix the code.
3. check() runs the robot's checks on your workspace. Read its reasons, fix, and check again until it passes.
4. submit_fix with your root cause, confidence, hypotheses, evidence and what the retest should measure. If no CAD
   change can fix the finding (perception, the arm, wiring, firmware), submit_fix with no_cad_fix=true instead.
Finish with submit_fix; there is no other answer."""


def cad_command(binary: str, mcp_config: str, model: str, effort: str, budget_usd: float | None,
                server: str = "rav-cad", system: str = SYSTEM_ONSHAPE) -> list[str]:
    """Headless Claude Code with only one CAD server's tools: no built-in tools, no other MCP servers."""
    cmd = [binary, "-p", "--output-format", "json", "--mcp-config", mcp_config, "--strict-mcp-config",
           "--allowedTools", f"mcp__{server}", "--tools", "", "--system-prompt", system, "--model", model,
           "--effort", effort, "--no-session-persistence", "--disable-slash-commands"]
    return cmd + (["--max-budget-usd", f"{budget_usd:g}"] if budget_usd else [])


def onshape_command(binary: str, mcp_config: str, model: str, effort: str, budget_usd: float | None) -> list[str]:
    return cad_command(binary, mcp_config, model, effort, budget_usd)


def make_cad_analyst(backend: Any, tags_path: str | pathlib.Path, *, server: str, module: str, system: str,
                     open_ws: Callable[[Any, pathlib.Path], str], extra_args: Callable[[pathlib.Path], list[str]] | None = None,
                     run: Runner | None = None, model: str = MODEL, effort: str = "high", timeout_s: float = 900.0,
                     budget_usd: float | None = 5.0, binary: str | None = None, python: str = sys.executable) -> Analyst:
    """An analyst that fixes each finding itself with one CAD MCP server (`module`, named `server`), on a branch or
    workspace of its own made by `open_ws(finding, out_dir)`. `backend` is what the harness checks and applies with;
    `tags_path` is the product's tag file, which the server process loads too."""
    tags_path = str(pathlib.Path(tags_path).resolve())

    def cad_analyst(ctx: AnalystContext) -> tuple[RootCause, CADPatch | None]:
        exe = binary or os.environ.get("RAV_CLAUDE_BIN") or shutil.which("claude")
        if run is None and not exe:
            return _fallback_none(ctx, model, "api_error", "the claude CLI isn't on PATH (install Claude Code, or set RAV_CLAUDE_BIN)")
        f = ctx.finding
        base = ctx.tracer.log.dir if ctx.tracer else pathlib.Path(tempfile.mkdtemp())
        out = (pathlib.Path(base) / "cad" / f.id).resolve()      # absolute: claude runs from another folder
        out.mkdir(parents=True, exist_ok=True)
        try:
            ws = open_ws(f, out)
        except Exception as e:  # noqa: BLE001 - no network, no keys, no access: a person takes it from here
            return _fallback_none(ctx, model, "api_error", f"couldn't open a branch to work on: {type(e).__name__}: {e}")
        config = out / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {server: {"command": python, "args": [
            "-m", module, "--tags", tags_path, "--workspace", ws, "--out", str(out), "--target", f.target,
            *(extra_args(out) if extra_args else []), "--verify", *f.step_ids],
            "env": {"PYTHONPATH": _package_paths()}}}}, indent=2))
        cmd = cad_command(exe or "claude", str(config), model, effort, budget_usd, server=server, system=system)
        try:          # the failing control's parts and faces up front, so the model needn't spend calls finding them
            facts = backend.describe(f.target) if hasattr(backend, "describe") and not os.environ.get("RAV_NO_FACTS") else ""
        except Exception:  # noqa: BLE001 - the tools can still find all of this; it's only a head start
            facts = ""
        prompt = (build_prompt(ctx) + ("\n\nThe failing control in the CAD, measured on the tested version (your branch "
                                       "starts identical; face ids work on it):\n" + facts if facts else "")
                  + "\n\nYour branch: " + backend.url(ws))

        start = time.monotonic()
        (out / "prompt.txt").write_text(prompt)          # what the model was given, kept even if the session hangs
        limit = float(os.environ.get("RAV_ANALYST_TIMEOUT_S") or timeout_s)
        try:
            proc = (run or _run_claude)(cmd, prompt, limit)
        except subprocess.TimeoutExpired:
            return _fallback_none(ctx, model, "timeout", f"the CAD session gave no answer in {limit:g} s")
        except OSError as e:
            return _fallback_none(ctx, model, "api_error", f"couldn't start claude: {e}")
        try:
            done = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            done = {}
        usage = done.get("usage") or {}
        failed = proc.returncode != 0 or done.get("is_error")
        turn = _turn(ctx.tracer, model, input=prompt, text=done.get("result") or (proc.stderr or "")[:2000] or None,
                     stop_reason=done.get("stop_reason"), error_kind="api_error" if failed else None,
                     tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"),
                     latency_ms=done.get("duration_ms") or round((time.monotonic() - start) * 1000, 1),
                     raw={"command": cmd, "stdin": prompt, "response": done, "branch": backend.url(ws)})
        _replay_calls(ctx, out / "calls.jsonl", turn)

        result_file = out / "result.json"
        if not result_file.exists():
            why = "the CAD session failed" if failed else "the CAD session ended without submit_fix"
            return RootCause(finding=f.id, evidence=[f.what_happened], hypotheses=[],
                             root_cause=f"{why}; its branch is {backend.url(ws)}. A person should look.", confidence=0.0), None
        result = json.loads(result_file.read_text())
        cause = RootCause(**{**result["cause"], "finding": f.id})
        patch = CADPatch(**result["patch"]) if result.get("patch") else None
        return cause, patch

    return cad_analyst


def make_onshape_analyst(backend: Any, tags_path: str | pathlib.Path, **kw: Any) -> Analyst:
    """Fixes each finding in Onshape, on a branch of the tested version (rav-cad tools)."""
    return make_cad_analyst(
        backend, tags_path, server="rav-cad", module="rav_cad.onshape.mcp_server", system=SYSTEM_ONSHAPE,
        open_ws=lambda f, out: backend.open_branch(f"fix {f.id} {f.target}", f"Analyst branch for finding {f.id}: {f.what_happened}"),
        **kw)


def make_local_analyst(backend: Any, tags_path: str | pathlib.Path, **kw: Any) -> Analyst:
    """Fixes each finding offline by writing CadQuery for new parts, in a local workspace (rav-cad-local tools).
    `backend` is a LocalCadBackend; its parametric sources, if any, are handed to the server as references."""
    def extra(out: pathlib.Path) -> list[str]:
        if not getattr(backend, "sources", None):
            return []
        path = out / "sources.json"
        path.write_text(json.dumps(backend.sources))
        return ["--sources", str(path)]
    return make_cad_analyst(
        backend, tags_path, server="rav-cad-local", module="rav_cad.local.mcp_server", system=SYSTEM_LOCAL,
        open_ws=lambda f, out: backend.open_branch("workspace", root=out), extra_args=extra, **kw)


def _package_paths() -> str:
    """Where our packages live, so the CAD server's own Python process finds them whatever its site setup does."""
    import importlib.util
    roots = []
    for name in ("rav_cad", "rav_contracts", "rav_interface", "rav_harness"):
        spec = importlib.util.find_spec(name)
        if spec and spec.origin:
            roots.append(str(pathlib.Path(spec.origin).resolve().parents[1]))
    return os.pathsep.join(dict.fromkeys(roots))


def _fallback_none(ctx: AnalystContext, model: str, kind: str, why: str) -> tuple[RootCause, None]:
    """The Onshape analyst can't run: say why in the trace and hand the finding to a person (no CadQuery mix-up)."""
    _turn(ctx.tracer, model, error_kind=kind, text=why)
    return RootCause(finding=ctx.finding.id, evidence=[ctx.finding.what_happened], hypotheses=[],
                     root_cause=f"{why}. A person should look.", confidence=0.0), None


def _replay_calls(ctx: AnalystContext, path: pathlib.Path, turn: str | None) -> None:
    """The MCP server ran inside the analyst's process; copy its calls into the run's trace as tool_call events."""
    if ctx.tracer is None or not path.exists():
        return
    for line in path.read_text().splitlines():
        c = json.loads(line)

        def replay(c=c):
            if not c["ok"]:
                raise ToolRejected("bad_args", str(c["result"]))
            return c["result"]
        try:
            _call(ctx.tracer, f"cad.{c['tool']}", c.get("args") or {}, replay, turn)
        except ToolRejected:
            pass
