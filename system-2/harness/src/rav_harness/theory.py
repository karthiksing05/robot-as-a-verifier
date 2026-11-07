"""A theory of devices: a small vocabulary of pieces, relations and procedures, and the properties worth testing on
each. A model writes its own hypothesis of a device in it (from the manual and the scan), and derive_tests() turns that
hypothesis into the tests the properties call for. See docs/device-theory.md.

This module describes devices in general. It never names a device or holds what is wrong with one.

    h = DeviceHypothesis.model_validate(model_output)
    intents = derive_tests(h)
    report = coverage(intents, done={"actuates:button_1": "passed", ...})
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Source = Literal["manual", "scan", "cad", "observed"]

# How a person operates a control. Each maps to a System 1 skill of the same name.
Primitive = Literal["press", "turn", "flip", "slide", "push_latch", "hook_pull", "pick", "place"]
Return = Literal["momentary", "latching", "continuous"]
IndicatorKind = Literal["text_display", "light", "led", "beeper", "flag"]
MechanismKind = Literal["hinge", "slide", "latch", "spring"]
ContainerKind = Literal["well", "slot", "tray", "cradle", "hopper"]
RelationKind = Literal["enables", "requires", "interlocks", "drives", "displays"]
Op = Literal["==", "!=", "<", "<=", ">", ">=", "in", "changes", "shows"]
PieceCategory = Literal["control", "indicator", "mechanism", "container", "object", "state"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- pieces -------------------------------------------------------------------------------------

class Range(Model):
    low: float | str
    high: float | str
    unit: str | None = None
    direction: str | None = None  # how the manual says it goes, e.g. "clockwise raises"


class Piece(Model):
    id: str
    label: str | None = None  # what the manual or the panel calls it
    where: str | None = None  # in words, e.g. "top right of the sloped panel"
    sources: list[Source] = Field(default_factory=list)


class Control(Piece):
    primitive: Primitive
    returns: Return = "momentary"
    range: Range | None = None
    detents: list[float | str] = Field(default_factory=list)
    grip: str | None = None  # what operating it takes, e.g. "fingertip under a lip", "pinch"


class Indicator(Piece):
    kind: IndicatorKind
    shows: list[str] = Field(default_factory=list)  # state variables it reports
    vocabulary: list[str] = Field(default_factory=list)  # messages the manual documents, for a text display or a light's colours


class Mechanism(Piece):
    kind: MechanismKind
    range: Range | None = None
    rest: str | None = None  # where it ends up on its own, e.g. "falls shut", "stays open past 90 deg"
    operated_by: str | None = None  # a control id


class Container(Piece):
    kind: ContainerKind
    accepts: list[str] = Field(default_factory=list)  # object ids
    sensed: bool = False


class Object(Piece):
    fits: list[str] = Field(default_factory=list)  # container ids


class StateVar(Model):
    name: str
    values: list[str] | None = None  # a set of values, or
    range: Range | None = None  # a numeric range
    default: Any = None  # at power-on
    persists: bool = False  # survives a power cycle
    is_mode: bool = False  # the device's mode: what procedures move between
    sources: list[Source] = Field(default_factory=list)


# --- relations and procedures -------------------------------------------------------------------

class Condition(Model):
    """subject op value: ("lid", "==", "closed"), ("display_1", "shows", "LID"), ("speed", "changes", None)."""
    subject: str
    op: Op = "=="
    value: Any = None


class Relation(Model):
    kind: RelationKind
    source: str  # piece id or state name
    target: str
    when: Condition | None = None  # enables / requires / interlocks: the state of source that matters
    mapping: str | None = None  # drives: e.g. "1000 + 5000 * fraction of sweep", or a table in words
    message: str | None = None  # interlocks: what the device shows when it blocks
    sources: list[Source] = Field(default_factory=list)


class Step(Model):
    primitive: Primitive | Literal["observe", "wait"]
    target: str
    params: dict[str, Any] = Field(default_factory=dict)
    pre: list[Condition] = Field(default_factory=list)
    effects: list[Condition] = Field(default_factory=list)


class Procedure(Model):
    name: str
    goal: str | None = None
    manual_ref: str | None = None  # section or page
    steps: list[Step]


class DeviceHypothesis(Model):
    """What a model believes about a device, before it tests anything."""
    name: str | None = None
    controls: list[Control] = Field(default_factory=list)
    indicators: list[Indicator] = Field(default_factory=list)
    mechanisms: list[Mechanism] = Field(default_factory=list)
    containers: list[Container] = Field(default_factory=list)
    objects: list[Object] = Field(default_factory=list)
    state: list[StateVar] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    procedures: list[Procedure] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def ids(self) -> set[str]:
        return ({p.id for p in [*self.controls, *self.indicators, *self.mechanisms, *self.containers, *self.objects]}
                | {s.name for s in self.state})

    @model_validator(mode="after")
    def _known_names(self) -> DeviceHypothesis:
        ids = self.ids()
        dup = [i for i in ids if sum(1 for p in [*self.controls, *self.indicators, *self.mechanisms, *self.containers, *self.objects] if p.id == i) > 1]
        if dup:
            raise ValueError(f"ids used twice: {sorted(dup)}")
        for r in self.relations:
            for name in (r.source, r.target):
                if name not in ids and name != "*":  # "*": every control, as a power switch enables them all
                    raise ValueError(f"relation {r.kind} names {name!r}, which is no piece or state")
        return self


# --- properties ---------------------------------------------------------------------------------

AppliesTo = Literal["control", "indicator", "mechanism", "container", "state", "relation", "procedure", "control_pair", "claim"]


class PropertyTemplate(Model):
    id: str
    applies_to: AppliesTo
    relation: RelationKind | None = None  # for applies_to="relation": which kind
    when: str | None = None  # a further filter, in words, and in applies() below
    statement: str  # with {subject} (and {other}, {target}) placeholders
    method: str  # what to do, in primitives
    oracle: str  # what evidence decides it
    failure: str  # the failure label a broken one gets (rav_interface FailureLabel)


PROPERTIES: list[PropertyTemplate] = [
    PropertyTemplate(id="actuates", applies_to="control", statement="Operating {subject} changes its reading or what it drives.",
                     method="the control's primitive, once, at its normal force limit", oracle="a reading changes during or after the step",
                     failure="no_actuation"),
    PropertyTemplate(id="gives_feedback", applies_to="control", when="it drives state that an indicator displays",
                     statement="Operating {subject} shows on {target}, as the manual says.",
                     method="operate, then observe the indicator", oracle="the indicator's text or colour after the step", failure="wrong_feedback"),
    PropertyTemplate(id="respects_range", applies_to="control", when="it has a range",
                     statement="{subject} reaches both ends of its range, and the values there are the manual's.",
                     method="operate to each end; observe at each", oracle="the value at each end", failure="wrong_behavior"),
    PropertyTemplate(id="returns_to_default", applies_to="control", when="it is momentary",
                     statement="{subject} springs back and its reading clears.", method="operate, release, wait a second",
                     oracle="the reading returns to its rest value", failure="stuck"),
    PropertyTemplate(id="operable_under_rules", applies_to="control",
                     statement="{subject} can be operated within the test's rules.", method="the control's primitive with the allowed effector",
                     oracle="the skill runs without refusing for grip or rules", failure="accessibility"),
    PropertyTemplate(id="reachable", applies_to="control", statement="The arm can reach and operate {subject} where the device stands.",
                     method="plan the approach; operate", oracle="the arm reaches the approach pose", failure="accessibility"),
    PropertyTemplate(id="needs_reposition", applies_to="control", when="it is out of reach where the device stands",
                     statement="{subject} comes into reach after moving the device as the manual or the operator allows.",
                     method="reposition the device, then operate", oracle="reach before and after the move", failure="accessibility"),
    PropertyTemplate(id="displays_matches", applies_to="relation", relation="displays",
                     statement="{subject} shows {target} in the manual's format.", method="observe after changing {target}",
                     oracle="the display text", failure="wrong_feedback"),
    PropertyTemplate(id="message_documented", applies_to="indicator", when="it has a vocabulary",
                     statement="Every message {subject} shows is in the manual, and every documented message can be made to show.",
                     method="drive the device into each documented condition; observe", oracle="the display text in each", failure="wrong_feedback"),
    PropertyTemplate(id="direction_matches", applies_to="relation", relation="drives",
                     statement="Moving {subject} the manual's way moves {target} the manual's way.",
                     method="operate a little one way; observe", oracle="the sign of the change", failure="wrong_behavior"),
    PropertyTemplate(id="mapping_matches", applies_to="relation", relation="drives",
                     statement="Positions of {subject} give the manual's values of {target}.", method="operate to a few positions; observe at each",
                     oracle="the values against the stated mapping", failure="wrong_behavior"),
    PropertyTemplate(id="enable_holds", applies_to="relation", relation="enables",
                     statement="With {subject} not enabling, {target} does nothing.", method="leave the enabler off; operate the target",
                     oracle="no change in the target's effect", failure="unsafe"),
    PropertyTemplate(id="requirement_holds", applies_to="relation", relation="requires",
                     statement="Without {subject}, {target} is refused.", method="leave the requirement unmet; operate the target",
                     oracle="the action does not happen", failure="unsafe"),
    PropertyTemplate(id="interlock_holds", applies_to="relation", relation="interlocks",
                     statement="While {subject} guards, {target} is blocked and the device says so.",
                     method="open the guard; operate the target; observe", oracle="the action does not happen, and the message shows", failure="unsafe"),
    PropertyTemplate(id="interlock_releases", applies_to="relation", relation="interlocks",
                     statement="With {subject} satisfied, {target} goes ahead.", method="satisfy the guard; operate the target",
                     oracle="the action happens", failure="wrong_behavior"),
    PropertyTemplate(id="default_on_power", applies_to="state", when="it has a documented default",
                     statement="After power-on, {subject} holds its documented default.", method="power on; observe",
                     oracle="the displayed or read value", failure="wrong_behavior"),
    PropertyTemplate(id="accepts_object", applies_to="container", statement="{other} seats fully in {subject}, and a sensed container reports it.",
                     method="pick the object; place it in the container", oracle="the seat reading, or the object's height", failure="wrong_behavior"),
    PropertyTemplate(id="mechanism_range", applies_to="mechanism", statement="{subject} opens to its stated range and rests where the manual says.",
                     method="operate it open; let go; observe", oracle="the angle or travel, and where it settles", failure="wrong_behavior"),
    PropertyTemplate(id="independent", applies_to="control_pair",
                     statement="Operating {subject} doesn't change what {other} drives.", method="operate one; watch the other's readings",
                     oracle="readings that should not change", failure="wrong_behavior"),
    PropertyTemplate(id="procedure_completes", applies_to="procedure",
                     statement="Following '{subject}' in order gives every effect the manual states.", method="each step, checking its effects",
                     oracle="each step's effects", failure="wrong_behavior"),
    PropertyTemplate(id="matches_manual", applies_to="claim", statement="The device does what the manual says: {subject}.",
                     method="whichever test exercises the claim", oracle="the evidence of that test", failure="wrong_behavior"),
]
BY_ID = {p.id: p for p in PROPERTIES}


class TestIntent(Model):
    """One property instantiated on one subject: what to test, not the steps. The model plans the steps."""
    __test__ = False  # not a pytest class
    key: str  # property:subject[:other]
    property: str
    subject: str
    other: str | None = None
    statement: str
    method: str
    oracle: str
    failure: str
    pre: list[Condition] = Field(default_factory=list)  # what has to hold before it can run
    blocked_by: list[str] = Field(default_factory=list)  # other intents' keys that must pass first


def _intent(p: PropertyTemplate, subject: str, other: str | None = None, target: str | None = None, pre=(), blocked_by=()) -> TestIntent:
    fill = {"subject": subject, "other": other or "", "target": target or other or ""}
    return TestIntent(key=":".join(x for x in (p.id, subject, other) if x), property=p.id, subject=subject, other=other,
                      statement=p.statement.format(**fill), method=p.method.format(**fill), oracle=p.oracle, failure=p.failure,
                      pre=list(pre), blocked_by=list(blocked_by))


def derive_tests(h: DeviceHypothesis) -> list[TestIntent]:
    """Every property that applies to the hypothesis, once per subject. Preconditions come from its enables, requires
    and interlocks relations, so a test behind a failed enabler shows as blocked rather than failed."""
    out: list[TestIntent] = []
    enablers: dict[str, list[Relation]] = {}
    for r in h.relations:
        if r.kind == "enables":
            enablers.setdefault(r.target, []).append(r)

    def gate(target: str) -> tuple[list[Condition], list[str]]:
        rs = [r for r in enablers.get(target, []) + enablers.get("*", []) if r.source != target]  # an enabler doesn't gate itself
        return [r.when for r in rs if r.when], [f"actuates:{r.source}" for r in rs]

    displayed = {s: r.source for r in h.relations if r.kind == "displays" for s in [r.target]}
    driven = {r.source: r.target for r in h.relations if r.kind == "drives"}
    for c in h.controls:
        pre, blocked = gate(c.id)
        for pid in ("actuates", "reachable", "operable_under_rules"):
            out.append(_intent(BY_ID[pid], c.id, pre=pre, blocked_by=blocked))
        if c.returns == "momentary" and c.primitive == "press":
            out.append(_intent(BY_ID["returns_to_default"], c.id, pre=pre, blocked_by=blocked))
        if c.range:
            out.append(_intent(BY_ID["respects_range"], c.id, pre=pre, blocked_by=blocked))
        shown_on = displayed.get(driven.get(c.id, ""))
        if shown_on:
            out.append(_intent(BY_ID["gives_feedback"], c.id, target=shown_on, pre=pre, blocked_by=blocked))
    for i in h.indicators:
        if i.vocabulary:
            out.append(_intent(BY_ID["message_documented"], i.id))
    for m in h.mechanisms:
        out.append(_intent(BY_ID["mechanism_range"], m.id))
    for k in h.containers:
        for o in k.accepts or [o.id for o in h.objects if k.id in o.fits]:
            out.append(_intent(BY_ID["accepts_object"], k.id, other=o))
    for s in h.state:
        if s.default is not None:
            out.append(_intent(BY_ID["default_on_power"], s.name))
    for r in h.relations:
        for p in PROPERTIES:
            if p.applies_to == "relation" and p.relation == r.kind:
                pre, blocked = gate(r.target) if r.kind != "enables" else ([], [])
                out.append(_intent(p, r.source, other=r.target, target=r.target, pre=pre, blocked_by=blocked))
    drivers = [c.id for c in h.controls if c.id in driven]
    for a in drivers:
        for b in drivers:
            if a != b and driven[a] != driven[b]:
                out.append(_intent(BY_ID["independent"], a, other=b))
    for proc in h.procedures:
        out.append(_intent(BY_ID["procedure_completes"], proc.name, pre=proc.steps[0].pre if proc.steps else []))
    seen, unique = set(), []
    for t in out:
        if t.key not in seen:
            seen.add(t.key)
            unique.append(t)
    return unique


Outcome = Literal["passed", "failed", "observed", "inconclusive"]


class Coverage(Model):
    tested: dict[str, Outcome] = Field(default_factory=dict)
    blocked: dict[str, list[str]] = Field(default_factory=dict)  # intent key -> the failed intents in its way
    untested: list[str] = Field(default_factory=list)

    @property
    def fraction(self) -> float:
        n = len(self.tested) + len(self.blocked) + len(self.untested)
        return len(self.tested) / n if n else 0.0


def coverage(intents: list[TestIntent], done: dict[str, Outcome]) -> Coverage:
    """done: intent key -> outcome, from the run's evidence. An intent whose blocker failed is blocked, not passed:
    re-test it once the blocker is fixed."""
    out = Coverage()
    for t in intents:
        if t.key in done:
            out.tested[t.key] = done[t.key]
            continue
        failed = [b for b in t.blocked_by if done.get(b) == "failed"]
        if failed:
            out.blocked[t.key] = failed
        else:
            out.untested.append(t.key)
    return out
