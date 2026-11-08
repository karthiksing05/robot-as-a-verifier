"""The agent loop: the model decides what to do next, and the tool belt enforces what it may. Every turn and call is traced,
so a failure can be traced to the layer that caused it. rav_harness.loop.run_test stays as the rule-based baseline.

    report = run_agent(system1, request, RunLog(id, "runs"), make_client("claude-haiku-5-5", run=id), approve=sim_auto_approve)
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rav_contracts import EscalationPolicy, Report, SteerCommand, TestRequest

from . import prompts
from .loop import Approver, Steering
from .manual import Manual
from .model import Image, Message, ModelClient, ModelError, ModelReply, ToolResult, Unavailable
from .runlog import RunLog
from .toolbelt import Ask, ToolBelt
from .trace import ToolRejected, Tracer

TEST_POLICY = EscalationPolicy(name="agent", retries_per_step=0, checkpoint_every=1, confidence_floor=0.5)  # each step reaches the record as it happens
Delta = Callable[[dict], None]


@dataclass
class AgentConfig:
    max_turns: int = 80
    max_tokens: int = 600_000
    max_seconds: float = 3600.0
    max_repeats: int = 6  # the same rejected call, in a run, before it counts as stuck
    keep_messages: int = 16  # older tool results shrink to a line, and older images go
    max_nudges: int = 4
    policy: EscalationPolicy = field(default_factory=lambda: TEST_POLICY)
    check_back: bool = True  # checkback.py: refuse plans that don't check back, and close the run with a look


def sim_auto_approve(kind: str, ref: str) -> str:
    """For evals on the sim only, and recorded on the run. run_agent refuses it for a real robot."""
    return "auto (sim)"


def robot_may_auto_approve(robot: str) -> bool:
    return robot in ("sim", "mock", "fake")


def _images_out(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        if m.role == "assistant":
            out.append({"role": "assistant", "text": m.reply.text, "thinking": m.reply.thinking,
                        "calls": [{"id": c.id, "name": c.name, "args": c.args} for c in m.reply.calls]})
        else:
            out.append({"role": "user", "text": m.text, "results": [{"name": r.call.name, "content": r.content, "error": r.is_error} for r in m.results],
                        "images": [i.caption for i in m.images]})
    return out


def _drop_thoughts(raw: Any) -> Any:
    if isinstance(raw, dict) and isinstance(raw.get("content"), list):
        return {**raw, "content": [b for b in raw["content"] if b.get("type") != "thinking"] or raw["content"]}
    if isinstance(raw, dict) and ("reasoning_content" in raw or "reasoning" in raw):
        return {k: v for k, v in raw.items() if k not in ("reasoning_content", "reasoning")}
    return raw


def trim(messages: list[Message], keep: int) -> list[Message]:
    """Older tool results shrink to a line and older images and thoughts go. The first message stays whole, and calls stay
    paired with their results, as the providers require."""
    if len(messages) <= keep + 1:
        return messages
    cut = len(messages) - keep
    out = [messages[0]]
    for m in messages[1:cut]:
        if m.role == "user":
            out.append(Message("user", m.text, [ToolResult(r.call, {"earlier": _brief(r.content)}, r.is_error) for r in m.results]))
        else:
            reply = m.reply
            out.append(Message("assistant", reply=ModelReply(model=reply.model, text=reply.text, calls=reply.calls, stop_reason=reply.stop_reason,
                                                             raw_message=_drop_thoughts(reply.raw_message))))
    return out + messages[cut:]


def _brief(content: dict) -> str:
    if "earlier" in content:
        return content["earlier"]
    keep = {k: content[k] for k in ("error", "stop", "status", "approved", "finished", "plan_id", "scene_version", "page") if k in content}
    return json.dumps(keep) if keep else "shortened: ask again if you need this"


def _steer_text(c: SteerCommand) -> str:
    extra = c.text or ""
    if c.kind == "skip":
        return prompts.OPERATOR_SKIP.format(target=c.target, text=extra)
    if c.kind == "prioritize":
        return prompts.OPERATOR_FIRST.format(target=c.target, text=extra)
    if c.kind == "add_step":
        return prompts.OPERATOR_ADD.format(step=c.step.model_dump_json(exclude_none=True) if c.step else "", text=extra)
    return prompts.OPERATOR.format(by=c.by, text=extra)


def _drain(steering: Steering, belt: ToolBelt, log: RunLog, wait: Callable[[], None] | None) -> tuple[list[str], bool]:
    """Everything the operator sent since the last turn, as text for the model. Waits out a pause. (lines, stop asked)"""
    lines, stop, paused = [], False, False
    while True:
        while steering.commands:
            c = steering.commands.popleft()
            note = ""
            if c.kind == "pause":
                paused, note = True, "paused before the model's next turn"
            elif c.kind == "resume":
                paused, note = False, "resumed"
            elif c.kind == "stop":
                stop, paused, note = True, False, "stopping"
            else:
                if c.kind == "skip" and c.target:
                    belt.skipped_by_operator.add(belt.canon.get(c.target, c.target))
                lines.append(_steer_text(c))
                note = "told the model"
                if c.kind == "message":
                    log.emit("message", {"role": "user", "text": c.text or "", "by": c.by})
            log.emit("steer_applied", {**c.model_dump(mode="json"), "note": note})
        if not paused:
            return lines, stop
        if wait is None:
            return lines, True
        wait()


def run_agent(system1, request: TestRequest, log: RunLog, client: ModelClient, approve: Approver = sim_auto_approve, steering: Steering | None = None,
              wait: Callable[[], None] | None = None, config: AgentConfig | None = None, manual: Manual | None = None, ask: Ask | None = None,
              on_delta: Delta | None = None) -> Report:
    config, steering = config or AgentConfig(), steering or Steering()
    tracer = Tracer(log, caller="model")
    tracer.stage = "MAP"
    log.emit("run_started", request)

    def state(name: str, detail: str = "") -> None:
        log.emit("agent_state", {"state": name, "detail": detail})

    belt = ToolBelt(system1, request, log, tracer, approve, steering, config.policy, manual, ask, state)
    belt.check_back = config.check_back
    if approve is sim_auto_approve and not robot_may_auto_approve(belt.status.robot):
        raise PermissionError(f"plans on {belt.status.robot} must be approved by a person")
    if approve is sim_auto_approve:
        log.emit("message", {"role": "harness", "text": "plans on this run are auto-approved: sim only"})

    # The brief holds the product's name and the instruction, and nothing from request.spec: that's for the record.
    brief = prompts.BRIEF.format(product=request.product, instruction=request.instruction,
                                 manual=prompts.MANUAL_YES.format(pages=len(manual.pages)) if manual else prompts.MANUAL_NO)
    messages = [Message("user", brief)]
    tools = belt.specs()
    start, tokens, turns, repeats, nudges = time.monotonic(), 0, 0, {}, 0
    new_input, status, stuck = brief, None, 0  # status: None until an operator stops the run

    def end(why: str, final: str = "aborted") -> Report:
        log.emit("message", {"role": "harness", "text": why})
        try:
            for _ in range(3):  # whatever's open: a routine running, or one holding at a stop
                if belt.holding:
                    belt._resume(_abort(why))
                elif belt.handle:
                    system1.routine_stop(belt.handle.routine_id)
                else:
                    break
                belt._wait()
        except Exception as e:  # noqa: BLE001 - the report still has to be written
            log.emit("message", {"role": "harness", "text": f"couldn't close the routine: {type(e).__name__}: {e}"})
        state("done", final)
        return belt.report(final)

    while True:
        lines, stop_asked = _drain(steering, belt, log, wait)
        if stop_asked:  # a stop wins over anything: the model gets no more turns
            belt.operator_note = "stopped by an operator"
            return end("stopped by an operator", "stopped")
        if lines:
            text = "\n".join(lines)
            messages.append(Message("user", text))
            new_input = text

        over = ("turn limit" if turns >= config.max_turns else "token limit" if tokens >= config.max_tokens else
                "time limit" if time.monotonic() - start >= config.max_seconds else None)
        if over:
            return end(f"the model used up its {over}")
        if stuck >= config.max_repeats:
            return end("the model kept repeating calls that were rejected")

        state("thinking")
        turn_id = f"turn-{tracer.turns + 1}"
        deltas = (lambda kind, text: on_delta({"type": "model_delta", "turn": turn_id, "kind": kind, "text": text})) if on_delta else None
        context = trim(messages, config.keep_messages)
        try:
            reply = client.generate(prompts.SYSTEM, context, tools, deltas)
        except (Unavailable, ModelError) as e:
            tracer.turn(getattr(client, "model", "model"), input=new_input, error=str(e), error_kind=e.kind)
            if status != "stopping":
                try:
                    belt.run_rules(str(e))
                except Exception as inner:  # noqa: BLE001 - the report still has to be written
                    log.emit("message", {"role": "harness", "text": f"the rule-based plan failed too: {type(inner).__name__}: {inner}"})
            state("done", "model unavailable")
            return belt.report("stopped" if status == "stopping" else "aborted" if belt.needs_recovery else "completed")
        turns += 1
        tokens += (reply.tokens_in or 0) + (reply.tokens_out or 0) + (reply.tokens_thinking or 0)
        cut = reply.stop_reason == "max_tokens" and not reply.calls
        turn = tracer.turn(reply.model, input=new_input, thinking=reply.thinking or None, text=reply.text or None, stop_reason=reply.stop_reason,
                           tokens_in=reply.tokens_in, tokens_out=(reply.tokens_out or 0) + (reply.tokens_thinking or 0), latency_ms=reply.latency_ms,
                           raw={"request": {"system": prompts.SYSTEM, "messages": _images_out(context)}, "response": reply.raw_message},
                           error="the reply was cut off before any tool call" if cut else None, error_kind="max_tokens" if cut else None)
        messages.append(Message("assistant", reply=reply))

        if not reply.calls:
            nudges += 1
            if nudges > config.max_nudges:
                return end("the model stopped calling tools before finishing")
            new_input = prompts.CUT_OFF if cut else prompts.NO_CALL
            messages.append(Message("user", new_input))
            continue

        results, images, shown = [], [], []
        for call in reply.calls:
            if any(c.kind == "stop" for c in steering.commands):  # nothing more runs once a stop is in
                results.append(ToolResult(call, {"error": "not run: an operator stopped the run"}, True))
                continue
            key = f"{call.name}:{json.dumps(call.args, sort_keys=True, default=str)}"
            try:
                if repeats.get(key, 0) >= 2:
                    raise ToolRejected("refused", prompts.REPEATED.format(n=repeats[key] + 1))
                content = belt.run(call, turn)
                images += belt.images
                results.append(ToolResult(call, content))
            except ToolRejected as e:
                repeats[key] = repeats.get(key, 0) + 1
                stuck += 1 if repeats[key] > 1 else 0
                results.append(ToolResult(call, {"error": str(e)}, True))
            except Exception as e:  # noqa: BLE001 - ours, and already in the trace as the pipeline's: the model hears and goes on
                results.append(ToolResult(call, {"error": f"the harness or robot failed: {type(e).__name__}: {e}"}, True))
            shown.append(f"{call.name} -> {json.dumps(results[-1].content, default=str)[:300]}")
        messages.append(Message("user", results=results, images=images))
        new_input = "\n".join(shown)

        if belt.finished:
            state("done", status or "completed")
            final = "stopped" if status == "stopping" else "aborted" if belt.needs_recovery else "completed"
            return belt.report(final)


def _abort(why: str):
    from rav_contracts import Decision
    return Decision(kind="abort", note=why)


__all__ = ["AgentConfig", "Image", "run_agent", "sim_auto_approve"]
