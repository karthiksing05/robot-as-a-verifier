"""Routines, stops and policies: how System 2 starts work and how System 1 reports back.

docs/system-boundary.md explains the rules these types carry. Keep this list short: every addition is more traffic.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import CheckResult, Contract, Control, Plan, SceneInventory, Skill, ControlKind, Step, StepVerdict

TOOLS = ("system_status", "scene_get", "evidence_get", "routine_start", "routine_wait", "routine_resume", "routine_stop")

RoutineName = Literal["explore", "run_plan", "home"]
StopKind = Literal["done", "checkpoint", "escalation", "safety_abort", "pipeline_error"]
EscalationCode = Literal["step_failed", "unexpected_response", "retries_exhausted", "perception_low_confidence",
                         "pose_unstable", "unknown_control", "survey_review", "scan_review"]
RoutineState = Literal["idle", "running", "paused"]


class EscalationPolicy(Contract):
    """How much System 1 does alone before it defers. Sent with every routine, so it can be tuned run by run."""
    name: str = "custom"
    retries_per_step: int = Field(default=0, ge=0, le=10)
    checkpoint_every: int | None = Field(default=1, ge=1)  # steps between checkpoints; None means only at the end
    confidence_floor: float = Field(default=0.5, ge=0.0, le=1.0)  # detections below this escalate
    review_survey: bool = False  # explore holds after its survey (survey_review) for a SurveyAnswer before it scans
    review_scan: bool = False  # and after its scan (scan_review) for each part's name and kind (Decision.labels) and what it missed
    survey_look_up_deg: float = Field(default=0.0, ge=-30.0, le=30.0)  # explore: every survey view tilted this far up (- down)


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
    measures: dict[str, Any] = Field(default_factory=dict)
    checks: list[CheckResult] = Field(default_factory=list)
    trace_ref: str  # the last attempt's
    attempt_refs: list[str] = Field(default_factory=list)  # earlier attempts' traces, when there were any


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


class ExpectedControl(Contract):
    name: str  # as the manual names it, such as START
    kind: str  # a ControlKind when it is one


class MissedControl(ExpectedControl):
    """A control the scan missed, marked on the scan_review stop's panel map: x, y are pixels in that image."""
    x: float
    y: float
    height_mm: float | None = None  # its top above the panel, used only where the scan has no height there


class SurveyAnswer(Contract):
    """System 2's answer to a survey_review stop. panel picks one of the stop's numbered candidate surfaces (None keeps
    System 1's pick). expect is what the manual says the device has: System 1 compares the scan with it and says where
    they differ, but never adds a control from it. also_look names other places on the device worth a look."""
    panel: int | None = None
    expect: list[ExpectedControl] = Field(default_factory=list)
    also_look: list[str] = Field(default_factory=list)


class Decision(Contract):
    """System 2's answer to a stop. It takes effect at the step boundary where the routine is holding."""
    kind: Literal["continue", "amend", "skip", "abort"] = "continue"
    steps: list[Step] = Field(default_factory=list)  # amend: replaces every remaining step
    targets: list[str] = Field(default_factory=list)  # skip: drop the remaining steps on these controls
    note: str | None = None
    survey: SurveyAnswer | None = None  # continue, at a survey_review stop
    # continue, at a scan_review stop: a part id's name and kind in the manual, or None when it isn't a control
    labels: dict[str, ExpectedControl | None] = Field(default_factory=dict)
    missed: list[MissedControl] = Field(default_factory=list)  # and controls it missed: System 1 adds them (source "model")


class ParamSpec(Contract):
    name: str
    required: bool = False
    min: float | None = None
    max: float | None = None
    nonzero: bool = False
    default: float | None = None
    unit: str = ""
    about: str = ""


class ActionSpec(Contract):
    """One skill the robot offers now: what it acts on and what it takes. Nothing outside this list can run."""
    skill: Skill
    kinds: list[ControlKind]
    params: list[ParamSpec] = Field(default_factory=list)
    about: str = ""


CHECK_METRICS = ("peak_force_n", "travel_mm", "duration_s", "contact_offset_mm", "lcd")  # and reading:<CHANNEL>


def _bounds(p: ParamSpec) -> str:
    low = "no minimum" if p.min is None else f"{p.min:g}"
    high = "no maximum" if p.max is None else f"{p.max:g}"
    return f"{low} to {high} {p.unit}".rstrip() + (", and can't be 0" if p.nonzero else "")


def check_steps(steps: list[Step], controls: list[Control], actions: list[ActionSpec]) -> list[str]:
    """Every way these steps are a bad request, from the contract alone: nothing moves and no robot is needed. What
    depends on where a part will be when the step runs (a stop, reach) stays a refusal at run time, because an earlier
    step in the plan may move it. A step on a pinch-only part isn't bad: it's a real refusal, and goes in the report."""
    problems: list[str] = []
    by_id = {c.id: c for c in controls}
    specs = {a.skill: a for a in actions}
    seen: set[str] = set()
    for s in steps:
        name = f"{s.id} ({s.skill} {s.target})"
        if s.id in seen:
            problems.append(f"{name}: step id {s.id} is used twice in this plan")
        seen.add(s.id)
        control = by_id.get(s.target)
        if control is None:
            problems.append(f"{name}: no control called {s.target}. Known: {', '.join(sorted(by_id)) or 'none, run explore first'}")
            continue
        if s.skill == "none":
            if not s.why:
                problems.append(f"{name}: skill none needs a why")
            continue
        spec = specs.get(s.skill)
        if spec is None:
            problems.append(f"{name}: {s.skill} isn't offered. Offered: {', '.join(sorted(specs))}")
            continue
        if control.grip == "pinch":
            continue
        if control.kind not in spec.kinds:
            takes = [a.skill for a in actions if control.kind in a.kinds]
            problems.append(f"{name}: {s.skill} can't act on a {control.kind}. It takes: {', '.join(takes) or 'nothing'}")
            continue
        known = {p.name: p for p in spec.params}
        for key, value in s.params.items():
            p = known.get(key)
            if p is None:
                problems.append(f"{name}: unknown param {key}. {s.skill} takes: {', '.join(known) or 'none'}")
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"{name}: {key} must be a number, got {value!r}")
            elif (p.min is not None and value < p.min) or (p.max is not None and value > p.max) or (p.nonzero and value == 0):
                problems.append(f"{name}: {key}={value:g} is outside {_bounds(p)}")
        for p in spec.params:
            if p.required and p.name not in s.params:
                problems.append(f"{name}: needs {p.name}")
        for c in s.check:
            if c.metric not in CHECK_METRICS and not c.metric.startswith("reading:"):
                problems.append(f"{name}: can't check {c.metric}. Metrics: {', '.join(CHECK_METRICS)}, reading:<CHANNEL>")
    return problems


class SceneReport(Contract):
    scene: SceneInventory | None = None
    fallback_plan: Plan | None = None  # rule-based, needs no model


class SystemStatus(Contract):
    state: RoutineState
    robot: str
    skills: list[str]
    actions: list[ActionSpec] = Field(default_factory=list)
    max_force_n: float | None = None  # the most a step may ask for
    check_metrics: list[str] = Field(default_factory=lambda: [*CHECK_METRICS, "reading:<CHANNEL>"])
    routine_id: str | None = None
    routine: RoutineName | None = None
    tools: list[str] = Field(default_factory=lambda: list(TOOLS))
