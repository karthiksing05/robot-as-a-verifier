"""The types that cross between System 1 and System 2. Units: millimetres, newtons and degrees. System 1's internals
use metres and radians, and rav_server.sim_backend converts at the boundary. Frame: arm base, x forward, y left, z up.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- vocabularies -------------------------------------------------------------------------------

Skill = Literal[
    # implemented in system-1/core/affordances.py
    "press", "flip", "slide", "turn", "push_latch",
    # planned (system-1/core does not implement this yet)
    "press_hold",
    # system-1/core/manipulate.py, offered only by a rig that can do them (SystemStatus.actions says which)
    "hook_pull", "pick", "place",
    # system-1/hardware/centrifuge_skills.py: the real arm's MC-6 lid, rack cover and tube, offered by RealBackend
    "lid_open", "lid_close", "rack_open", "rack_close", "tube_find", "tube_pick", "tube_place",
    # system-1/hardware/microwave_skills.py: the MW-1 microwave's buttons and door, offered only with the microwave
    "mw_press", "door_open", "door_close",
    # move the whole device on the desk: a normal step, on the control called DEVICE_CONTROL
    "reposition",
    # no motion: read a display or light with the camera
    "observe",
    # a part no skill may touch: the step records why and is skipped
    "none",
]
ControlKind = Literal["button", "slider", "dial", "toggle", "door", "knob", "display", "handle", "well", "object", "other"]
Status = Literal["passed", "failed", "observed", "skipped", "inconclusive"]
FailureLabel = Literal[
    "stuck", "wrong_behavior", "accessibility", "wrong_feedback", "no_actuation",
    "missing_control", "anomalous", "inconclusive", "unsafe",
    # never a step's label: System 2's name for a control that failed and also passed, so its Finding says so
    "intermittent",
]


DEVICE_CONTROL = "device"  # the control a reposition step targets. It's the device itself, so it isn't counted as a control to test

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
    source: Literal["scan", "cad", "manual", "model", "mock"] = "scan"  # model: added at a scan_review (Decision.missed)
    # what a plan needs to write a valid step, where the robot knows it. None: not known, or not this kind of control
    position: float | None = None  # slider: 0 to 1 along its travel
    travel_mm: float | None = None  # slider: full travel
    turn_range_deg: tuple[float, float] | None = None  # dial, knob: room from here to each stop
    detent_deg: float | None = None
    on: bool | None = None  # toggle
    latched: bool | None = None  # door


class SceneInventory(Contract):
    """The test surface: the denominator of control coverage."""
    frame: str = "arm_base"
    controls: list[Control]
    unmatched_manual_controls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    frames: list[str] = Field(default_factory=list)  # evidence_get refs: views of the device from the survey
    stale: bool = False  # the device moved since this was mapped, so its poses are old: run explore before any plan


# --- the plan -----------------------------------------------------------------------------------

TEXT_OPS = {"contains", "shows", "show", "displays", "display", "reads", "includes", "has", "in"}

class Check(Contract):
    metric: str
    op: Literal["<=", ">=", "==", "changed", "contains"]  # contains: the reading, as text, includes value (an LCD's)
    value: float | str | bool | None = None
    source: str | None = None  # e.g. "cobweb: push_button (n=46), mean + 2 sd"

    @field_validator("op", mode="before")
    @classmethod
    def _text_op(cls, v: Any) -> Any:
        """The words a model writes for a display's text (it sent "shows", and the plan was refused) mean contains."""
        return "contains" if isinstance(v, str) and v.strip().lower() in TEXT_OPS else v


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

class CheckResult(Contract):
    """One Step.check, as System 1 evaluated it from the measurements. Reported beside the verdict: it never changes it."""
    metric: str
    op: str
    value: float | str | bool | None = None
    actual: float | str | bool | None = None
    passed: bool | None = None  # None: this attempt didn't measure the metric


class Frame(Contract):
    """One camera image, fetched by reference through evidence_get. Never part of a stop."""
    ref: str
    mime: str = "image/jpeg"
    data_b64: str
    width: int
    height: int
    caption: str = ""


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
    measures: dict[str, Any] = Field(default_factory=dict)  # what separates a broken part from a robot that missed
    checks: list[CheckResult] = Field(default_factory=list)
    frames: list[str] = Field(default_factory=list)  # evidence_get refs


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
