"""The run's event log, and the commands a person can send into a run.

A run is one append-only events.jsonl. The Console renders it, live or replayed, so a bug report
can link back to the exact moment it came from, and frontend work needs no robot.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import (CADPatch, Contract, Finding, Plan, Report, RootCause, SceneInventory, Step, StepTrace,
                     StepVerdict, TestRequest)

EventType = Literal[
    "run_started", "scene_ready", "plan_ready", "approval_needed", "approved", "step_started",
    "step_finished", "finding", "root_cause", "patch_proposed", "patch_applied", "steer_applied",
    "message", "report_ready", "run_finished", "model_turn", "tool_call", "crossing", "plan_amended", "agent_state", "check_judged",
]

# Which layer an error belongs to. This split is the point of the trace: a bad decision is the model's to fix,
# and a broken call is ours. Whether the robot or the device is at fault comes from StepVerdict instead.
ModelErrorKind = Literal["bad_args", "unknown_tool", "unknown_target", "refused", "max_tokens", "malformed"]
PipelineErrorKind = Literal["timeout", "exception", "api_error"]
TraceLayer = Literal["model", "pipeline"]

# What each event's payload must validate as. None means free-form, documented on the emitter.
PAYLOADS: dict[str, type[Contract] | None] = {
    "run_started": TestRequest,
    "scene_ready": SceneInventory,
    "plan_ready": Plan,
    "approval_needed": None,  # {"kind": "plan" | "patch", "ref": id}
    "approved": None,         # {"kind": "plan" | "patch", "ref": id, "by": name}
    "step_started": Step,
    "step_finished": None,    # {"trace": StepTrace, "verdict": StepVerdict}
    "finding": Finding,
    "root_cause": RootCause,
    "patch_proposed": CADPatch,
    "patch_applied": CADPatch,
    "steer_applied": None,    # a SteerCommand as a dict, plus "note" saying what it changed
    "message": None,          # {"role": "user" | "harness" | "model", "text": str}
    "report_ready": Report,
    "run_finished": None,     # {"status": "completed" | "stopped" | "aborted"}
    "model_turn": None,       # a ModelTurn: checked by rav_harness.trace, which builds it
    "tool_call": None,        # a ToolCall: same
    "crossing": None,         # a Crossing: System 1 stopped and handed back to System 2
    "plan_amended": None,     # {"level": 0-3, "by": name or None, "steps": [Step.id], "why": str}
    "agent_state": None,      # {"state": "thinking" | "calling" | "arm" | "waiting_person" | "idle" | "done", "detail": str}
    "check_judged": None,     # {"step", "target", "failed": [CheckResult], "requires": [Check], "met": bool, "counted": bool, "why"}
}


# rav-agent also streams {"type": "model_delta", "turn": id, "kind": "thought" | "text", "text": str} to the Console while a
# turn is being written. These aren't events: they aren't logged, and the finished turn's model_turn is the record.


class ModelTurn(Contract):
    """One model response: what it was newly told, what it thought and said. Its calls are ToolCalls naming this id."""
    id: str
    model: str
    stage: str | None = None  # the run stage when it happened: SURVEY, SCAN, MAP, PLAN, TEST, REPORT
    step: str | None = None   # Step.id, when it's about one
    input: str | None = None  # only what's new this turn; `raw` has the whole context
    thinking: str | None = None
    text: str | None = None
    stop_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: float | None = None
    claims: dict[str, str] = Field(default_factory=dict)  # Step.id -> the status it says happened, checked against sensors
    error: str | None = None
    error_kind: ModelErrorKind | PipelineErrorKind | None = None
    layer: TraceLayer | None = None
    raw: str | None = None  # full request and response, relative to the run folder


class ToolCall(Contract):
    """One call across the robot's tool surface, by the model or by the rules that stand in for it."""
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    caller: Literal["model", "rules", "operator"] = "rules"
    turn: str | None = None  # the ModelTurn that made this call
    stage: str | None = None
    step: str | None = None
    ok: bool = True
    result: dict[str, Any] | None = None
    error: str | None = None
    error_kind: ModelErrorKind | PipelineErrorKind | None = None
    layer: TraceLayer | None = None
    duration_ms: float | None = None


class Crossing(Contract):
    """One stop that reached System 2. Counting these per run is how we measure how much the systems talk."""
    routine: str
    stop: str  # done, checkpoint, escalation, safety_abort or pipeline_error
    code: str | None = None  # the EscalationCode, for an escalation
    step: str | None = None
    target: str | None = None
    policy: str | None = None
    verdicts: int = 0  # how many finished steps this stop reported
    retries_resolved: int = 0


class RunEvent(Contract):
    seq: int
    t: float  # seconds since the run started
    run_id: str
    type: EventType
    payload: dict[str, Any]


class SteerCommand(Contract):
    """Sent by the Console. The harness applies it at the next step boundary, never inside a motion.

    "stop" takes effect at the boundary too. The E-stop on servo power is separate and always available."""
    kind: Literal["pause", "resume", "stop", "prioritize", "skip", "add_step", "message"]
    target: str | None = None  # Control.id for prioritize and skip
    step: Step | None = None   # for add_step
    text: str | None = None    # for message
    by: str = "operator"


class StepOutcome(Contract):
    """The step_finished payload."""
    trace: StepTrace
    verdict: StepVerdict


__all__ = ["EventType", "Crossing", "PAYLOADS", "ModelTurn", "RunEvent", "SteerCommand", "StepOutcome", "ToolCall", "TraceLayer", "Field"]
