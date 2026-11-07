"""Records what a model decided and what each tool did, so a failure can be traced to the layer that caused it.

Errors the model caused (bad arguments, a part that doesn't exist) and errors the pipeline caused (a timeout, an
exception) are told apart when they happen, while the kind of error is still known. The Console reads the events back.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, get_args

from rav_contracts.events import ModelErrorKind, ModelTurn, ToolCall

from .runlog import RunLog

MODEL_ERRORS = set(get_args(ModelErrorKind))


class ToolRejected(Exception):
    """A tool refused the call because of what was asked: the error is the caller's. Sent back to the model to read."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def layer_of(kind: str | None) -> str | None:
    return None if kind is None else "model" if kind in MODEL_ERRORS else "pipeline"


def plain(value: Any, depth: int = 3) -> Any:
    """Keep a log line readable and JSON-safe, whatever a tool returned."""
    if hasattr(value, "item") and getattr(value, "ndim", 1) == 0:  # a numpy scalar
        value = value.item()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 2000 else f"{value[:2000]}... ({len(value)} characters)"
    if depth > 0 and isinstance(value, dict):
        return {str(k): plain(v, depth - 1) for k, v in list(value.items())[:40]}
    if depth > 0 and isinstance(value, (list, tuple)):
        return [plain(v, depth - 1) for v in value[:40]]
    if hasattr(value, "__len__"):
        return f"{type(value).__name__} of {len(value)}"
    return type(value).__name__


class Tracer:
    def __init__(self, log: RunLog, caller: str = "rules"):
        self.log, self.caller = log, caller
        self.stage: str | None = None
        self.step: str | None = None
        self.turns = self.calls = 0

    def turn(self, model: str, *, raw: dict | None = None, error_kind: str | None = None, **fields: Any) -> str:
        self.turns += 1
        turn_id = f"turn-{self.turns}"
        path = None
        if raw is not None:
            folder = self.log.dir / "model"
            folder.mkdir(exist_ok=True)
            (folder / f"{turn_id}.json").write_text(json.dumps(raw, indent=2, default=str) + "\n")
            path = f"model/{turn_id}.json"
        self.log.emit("model_turn", ModelTurn(id=turn_id, model=model, stage=self.stage, step=self.step, raw=path,
                                              error_kind=error_kind, layer=layer_of(error_kind), **fields).model_dump(mode="json"))
        return turn_id

    def call(self, tool: str, args: dict, fn: Callable[[], Any], *, turn: str | None = None, caller: str | None = None,
             summarize: Callable[[Any], Any] | None = None) -> Any:
        """Run one tool call and log it, then return its value or raise its error, as if this weren't here."""
        self.calls += 1
        fields = {"id": f"call-{self.calls}", "tool": tool, "args": plain(args), "turn": turn, "stage": self.stage, "step": self.step,
                  "caller": caller or ("model" if turn else self.caller)}
        start = time.monotonic()
        ms = lambda: round((time.monotonic() - start) * 1000, 1)  # noqa: E731
        try:
            value = fn()
        except Exception as e:  # logged, then raised. BaseExceptions, like a person stopping the run, aren't errors
            kind = e.kind if isinstance(e, ToolRejected) else "timeout" if isinstance(e, TimeoutError) else "exception"
            detail = str(e) if isinstance(e, ToolRejected) else f"{type(e).__name__}: {e}"
            self.log.emit("tool_call", ToolCall(**fields, ok=False, error=detail, error_kind=kind, layer=layer_of(kind), duration_ms=ms()).model_dump(mode="json"))
            raise
        shown = plain(summarize(value) if summarize else value)
        self.log.emit("tool_call", ToolCall(**fields, result=shown if isinstance(shown, dict) else {"value": shown}, duration_ms=ms()).model_dump(mode="json"))
        return value
