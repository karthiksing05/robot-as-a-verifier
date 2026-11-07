"""Routines, stops and policies: how System 2 starts work and how System 1 reports back.

docs/system-boundary.md explains the rules these types carry. Keep this list short: every addition is more traffic.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import Contract, Plan, SceneInventory, Step, StepVerdict

TOOLS = ("system_status", "scene_get", "evidence_get", "routine_start", "routine_wait", "routine_resume", "routine_stop")

RoutineName = Literal["explore", "run_plan", "home"]
StopKind = Literal["done", "checkpoint", "escalation", "safety_abort"]
EscalationCode = Literal["step_failed", "unexpected_response", "retries_exhausted", "perception_low_confidence",
                         "pose_unstable", "unknown_control"]
RoutineState = Literal["idle", "running", "paused"]


class EscalationPolicy(Contract):
    """How much System 1 does alone before it defers. Sent with every routine, so it can be tuned run by run."""
    name: str = "custom"
    retries_per_step: int = Field(default=0, ge=0, le=10)
    checkpoint_every: int | None = Field(default=1, ge=1)  # steps between checkpoints; None means only at the end
    confidence_floor: float = Field(default=0.5, ge=0.0, le=1.0)  # detections below this escalate


# Start with TETHERED, and loosen a setting only when the measurements hold up. The values are guesses until then.
TETHERED = EscalationPolicy(name="tethered", retries_per_step=0, checkpoint_every=1, confidence_floor=0.5)
BALANCED = EscalationPolicy(name="balanced", retries_per_step=2, checkpoint_every=None, confidence_floor=0.3)
AUTONOMOUS = EscalationPolicy(name="autonomous", retries_per_step=4, checkpoint_every=None, confidence_floor=0.1)
POLICIES = {p.name: p for p in (TETHERED, BALANCED, AUTONOMOUS)}


class RoutineHandle(Contract):
    routine_id: str
    routine: RoutineName


class StepSummary(Contract):
    """One finished step, small enough to read in a model's context. The full trace is at trace_ref."""
    verdict: StepVerdict
    attempts: int = 1
    peak_force_n: float | None = None
    travel_mm: float | None = None
    stop_reason: str | None = None
    readout_change: dict[str, list[Any]] = Field(default_factory=dict)
    trace_ref: str


class Escalation(Contract):
    """The mechanism with its numbers, never just a score."""
    code: EscalationCode
    step: str | None = None
    target: str | None = None
    tried: list[str] = Field(default_factory=list)
    measured: dict[str, Any] = Field(default_factory=dict)
    options: list[Literal["continue", "amend", "skip", "abort"]] = Field(default_factory=lambda: ["continue", "amend", "skip", "abort"])


class Checkpoint(Contract):
    """What routine_wait returns. stop is None when the wait timed out and the routine is still going."""
    routine_id: str
    stop: StopKind | None = None
    status: Literal["running", "paused", "completed", "stopped", "aborted"] = "running"
    steps_done: int = 0
    steps_total: int = 0
    retries_resolved: int = 0  # steps that passed only after a local retry, since the last stop
    verdicts: list[StepSummary] = Field(default_factory=list)  # since the last stop
    escalation: Escalation | None = None
    reason: str | None = None


class Decision(Contract):
    """System 2's answer to a stop. It takes effect at the step boundary where the routine is holding."""
    kind: Literal["continue", "amend", "skip", "abort"] = "continue"
    steps: list[Step] = Field(default_factory=list)  # amend: replaces every remaining step
    targets: list[str] = Field(default_factory=list)  # skip: drop the remaining steps on these controls
    note: str | None = None


class SceneReport(Contract):
    scene: SceneInventory | None = None
    fallback_plan: Plan | None = None  # rule-based, needs no model


class SystemStatus(Contract):
    state: RoutineState
    robot: str
    skills: list[str]
    routine_id: str | None = None
    routine: RoutineName | None = None
    tools: list[str] = Field(default_factory=lambda: list(TOOLS))
