"""The types that cross between System 1 and System 2. Units: millimetres, newtons and degrees. System 1's internals
use metres and radians, and rav_server.sim_backend converts at the boundary. Frame: arm base, x forward, y left, z up.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- vocabularies -------------------------------------------------------------------------------

Skill = Literal[
    # implemented in system-1/sim/affordances.py
    "press", "flip", "slide", "turn", "push_latch",
    # planned (system-1/sim does not implement these yet)
    "press_hold", "hook_pull",
    # no motion: read a display or light with the camera
    "observe",
    # a part no skill may touch: the step records why and is skipped
    "none",
]
ControlKind = Literal["button", "slider", "dial", "toggle", "door", "knob", "display", "other"]
Status = Literal["passed", "failed", "observed", "skipped", "inconclusive"]
FailureLabel = Literal[
    "stuck", "wrong_behavior", "accessibility", "wrong_feedback", "no_actuation",
    "missing_control", "anomalous", "inconclusive", "unsafe",
]


# --- 2 what the robot found ---------------------------------------------------------------------

class Control(Contract):
    """One functional part. Maps from features.Part in the sim."""
    id: str
    kind: ControlKind
    pos_mm: tuple[float, float, float]
    normal: tuple[float, float, float]
    size_mm: tuple[float, float, float] | None = None
    motion: str = ""  # "translation", "rotation" or ""
    grip: Literal["tip", "pinch"] = "tip"
    label: str | None = None
    conf: float = 1.0
    source: Literal["scan", "cad", "manual", "mock"] = "scan"


class SceneInventory(Contract):
    """The test surface: the denominator of control coverage."""
    frame: str = "arm_base"
    controls: list[Control]
    unmatched_manual_controls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --- the plan -----------------------------------------------------------------------------------

class Check(Contract):
    metric: str
    op: Literal["<=", ">=", "==", "changed"]
    value: float | str | bool | None = None
    source: str | None = None  # e.g. "cobweb: push_button (n=46), mean + 2 sd"


class Step(Contract):
    id: str
    skill: Skill
    target: str  # Control.id
    params: dict[str, Any] = Field(default_factory=dict)
    quote: str | None = None  # the manual line this step comes from
    expected: str | None = None
    check: list[Check] = Field(default_factory=list)
    why: str | None = None  # why a step will be skipped


class Plan(Contract):
    plan_id: str
    steps: list[Step]
    source: Literal["rules", "model", "cached", "mock"] = "rules"


# --- what happened ------------------------------------------------------------------------------

class StepTrace(Contract):
    """The measurements of one attempt. Verdicts and the reward are recomputable from these."""
    step: str
    attempt: int = 1
    stop_reason: str | None = None
    duration_s: float | None = None
    peak_force_n: float | None = None
    travel_mm: float | None = None
    force_trace: list[tuple[float, float]] = Field(default_factory=list)  # (t_s, N)
    readout_change: dict[str, list[Any]] = Field(default_factory=dict)  # channel -> before ... after
    frames: list[str] = Field(default_factory=list)  # paths inside the run folder


class StepVerdict(Contract):
    step: str
    target: str
    attempt: int = 1
    status: Status
    label: FailureLabel | None = None
    reason: str
    channel: str | None = None  # the device readout this control drives
    decided_by: Literal["rule", "cobweb", "model", "safety"] = "rule"
    evidence: list[str] = Field(default_factory=list)
