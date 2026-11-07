"""The objects only System 2 uses: requests, findings, fixes and reports. The types that cross to System 1 live in
rav_interface and are re-exported here, so harness code has one place to import from.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from rav_interface.models import (Check, Contract, Control, ControlKind, FailureLabel, Plan, SceneInventory, Skill, Status,
                                  Step, StepTrace, StepVerdict)


Severity = Literal["high", "medium", "low"]


# --- 1 input ------------------------------------------------------------------------------------

class ManualRef(Contract):
    file: str
    pages: int | None = None


class TestRequest(Contract):
    __test__ = False  # not a pytest class
    request_id: str
    product: str
    project: str | None = None  # the Console project this run belongs to
    revision: str = "A"
    instruction: str = "Try every feature a first-time user would try."
    manual: ManualRef | None = None
    cad: str | None = None  # path to the parametric model, when there is one
    spec: dict[str, Any] = Field(default_factory=dict)  # limits and posture (spec.yaml)


# --- 3-4 the plan -------------------------------------------------------------------------------

class ValidationResult(Contract):
    plan_id: str
    valid: bool
    errors: list[str] = Field(default_factory=list)
    clamped: list[dict[str, Any]] = Field(default_factory=list)
    approved_by: str | None = None


# --- 7-9 what happened --------------------------------------------------------------------------

class ConceptMatch(Contract):
    step: str
    attempt: int = 1
    concept_path: list[str]
    concept_n: int
    predicted: dict[str, dict[str, float]]
    observed: dict[str, float | None]
    z: dict[str, float]
    verdict_hint: Literal["normal", "anomalous"] = "normal"


# --- 10-11 the fix ------------------------------------------------------------------------------

class Hypothesis(Contract):
    cause: str
    p: float
    check: str | None = None
    ruled_out: str | None = None


class RootCause(Contract):
    finding: str  # Finding.id
    evidence: list[str]
    hypotheses: list[Hypothesis]
    root_cause: str
    confidence: float


class ParamChange(Contract):
    param: str
    from_value: Any
    to_value: Any
    unit: str | None = None
    predicted: str | None = None


class CadSource(Contract):
    """Where an edited model lives in Onshape. The microversion is exactly what was checked, so it's what gets approved."""
    document_id: str
    workspace_id: str              # the fix's own branch; the tested revision is never edited
    microversion_id: str
    base_version_id: str           # the version the robot tested (Rev A)
    element_id: str | None = None  # the Part Studio or Assembly the checks exported
    url: str | None = None         # a link a person can open


class CadEdit(Contract):
    """One thing the analyst did to the model, for people to read. The model's state is the source's microversion."""
    op: Literal["variable", "update_feature", "add_feature", "delete_feature"]
    target: str                    # a variable name or feature id
    summary: str


class CADPatch(Contract):
    file: str
    revision_from: str
    revision_to: str
    changes: list[ParamChange]
    constraints_checked: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    verify_with: list[str] = Field(default_factory=list)  # Step ids to rerun
    backend: str = "params"  # "params", "cadquery", "onshape", or an MCP backend's name
    source: CadSource | None = None                      # set when the fix was made in Onshape
    edits: list[CadEdit] = Field(default_factory=list)   # what the analyst did in Onshape, in order


# --- 12 the report ------------------------------------------------------------------------------

class Finding(Contract):
    """A bug report. event_seqs and step_ids let the Console jump back to the exact failure."""
    id: str
    severity: Severity
    target: str
    label: FailureLabel
    what_happened: str
    manual_says: str | None = None
    user_impact: str | None = None
    concept: str | None = None
    step_ids: list[str]
    event_seqs: list[int] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confirmed: bool = True  # False until re-run when the run's posture is optimistic


class Coverage(Contract):
    detected: int
    passed: list[str]
    failed: list[str]
    observed: list[str]
    inconclusive: list[str]
    skipped: dict[str, str]  # control id -> reason

    @property
    def covered(self) -> int:
        return len(self.passed) + len(self.failed) + len(self.observed)


class Reward(Contract):
    value: float
    control_coverage: float
    pass_rate: float
    formula: str = "control_coverage x pass_rate_on_covered"


class Report(Contract):
    run_id: str
    product: str
    revision: str
    summary: str
    findings: list[Finding]
    coverage: Coverage
    reward: Reward
