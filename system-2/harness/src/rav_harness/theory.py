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


# --- what a model sends -------------------------------------------------------------------------

def hypothesis_schema() -> dict[str, Any]:
    """DeviceHypothesis as a tool's parameter schema: every reference inlined and titles dropped, so any provider takes it."""
    raw = DeviceHypothesis.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(raw)


OP_WORDS = {"=": "==", "is": "==", "equals": "==", "eq": "==", "<>": "!=", "not": "!=", "ne": "!=", "change": "changes", "changed": "changes",
            "becomes": "==", "to": "==", "set": "==", "displays": "shows", "show": "shows", "contains": "shows", "reads": "shows", "lt": "<", "gt": ">", "le": "<=", "ge": ">=", "within": "in"}
_OPS = sorted([*Op.__args__, *OP_WORDS], key=len, reverse=True)  # type: ignore[attr-defined]
CONDITION_FIELDS = ("pre", "effects", "when")
PRIMITIVE_WORDS = {"push": "press", "button": "press", "tap": "press", "click": "press", "toggle": "flip", "switch": "flip", "rotate": "turn",
                   "twist": "turn", "dial": "turn", "knob": "turn", "slider": "slide", "latch": "push_latch", "pull": "hook_pull", "lift": "hook_pull",
                   "grab": "pick", "drop": "place", "insert": "place", "read": "observe", "look": "observe", "observe": "observe", "wait": "wait"}


def _condition_loc(loc: tuple) -> tuple | None:
    """The path to the condition that loc is in or at, if any: (..., "when") or (..., "pre", 2)."""
    for i in range(len(loc) - 1, -1, -1):
        if loc[i] in CONDITION_FIELDS:
            return loc[: i + 2] if loc[i] != "when" and i + 1 < len(loc) and isinstance(loc[i + 1], int) else loc[: i + 1]
    return None


def _condition(v: Any) -> Any:
    """A condition the way models write one: "lid == closed", {"lid": "closed"}, {"name": ..., "value": ...}."""
    import re

    if isinstance(v, str):
        for op in _OPS:
            m = re.match(rf"^\s*(.+?)\s*{re.escape(op)}\s*(.*?)\s*$" if not op.isalpha() else rf"^\s*(.+?)\s+{op}\s*(.*?)\s*$", v)
            if m and m.group(1):
                return {"subject": m.group(1), "op": OP_WORDS.get(op, op), "value": m.group(2) or None}
        return {"subject": v.strip(), "op": "==", "value": True}
    if isinstance(v, dict):
        v = dict(v)
        for alias in ("name", "state", "variable", "target", "what", "field"):
            if "subject" not in v and alias in v:
                v["subject"] = v.pop(alias)
        if "subject" not in v and len(v) == 1:
            ((k, val),) = v.items()
            return {"subject": k, "op": "==", "value": val}
        if "subject" not in v:
            extra = [k for k in v if k not in ("op", "value")]
            if extra:
                v["subject"] = extra[0]
                v.setdefault("value", v.pop(extra[0]))
        if isinstance(v.get("op"), str):
            v["op"] = OP_WORDS.get(v["op"].strip().lower(), v["op"].strip())
        return {k: v[k] for k in ("subject", "op", "value") if k in v}
    return v


def _range(v: Any) -> Any:
    import re

    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return {"low": v[0], "high": v[-1]}
    if isinstance(v, str):
        m = re.match(r"^\s*(-?[\d.]+)\s*(?:-|to|\.\.|–)\s*(-?[\d.]+)\s*(.*)$", v)
        if m:
            return {"low": float(m.group(1)), "high": float(m.group(2)), **({"unit": m.group(3).strip()} if m.group(3).strip() else {})}
    if isinstance(v, dict):
        out = {k: v[k] for k in ("low", "high", "unit", "direction") if k in v}
        for lo in ("min", "from", "start"):
            if lo in v and "low" not in out:
                out["low"] = v[lo]
        for hi in ("max", "to", "end"):
            if hi in v and "high" not in out:
                out["high"] = v[hi]
        return out
    return v


def _at(root: Any, loc: tuple) -> tuple[Any, Any]:
    """The container holding loc's last key, and that key."""
    node = root
    for key in loc[:-1]:
        node = node[key]
    return node, loc[-1]


def _drop_item(root: Any, loc: tuple) -> str | None:
    """Removes the innermost list element on loc's path: one bad entry costs only itself."""
    for i in range(len(loc) - 1, -1, -1):
        if isinstance(loc[i], int):
            parent, key = _at(root, loc[: i + 1])
            if isinstance(parent, list) and key < len(parent):
                parent.pop(key)
                return ".".join(map(str, loc[: i + 1]))
    return None


def parse_hypothesis(raw: Any, tries: int = 200) -> tuple[DeviceHypothesis, list[str]]:
    """Accepts the hypothesis a model sends, loosely: near misses are repaired, and an entry that can't be is left out.
    Returns what it kept and one line per repair, so the model can see what was read differently. Raises ValueError
    only when nothing usable is left."""
    import copy
    import json

    from pydantic import ValidationError

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as e:
            raise ValueError(f"the hypothesis isn't an object or JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError("the hypothesis must be an object with controls, indicators, state, relations, procedures ...")
    data, notes = copy.deepcopy(raw), []
    if isinstance(data.get("hypothesis"), dict):  # sent wrapped twice
        data = data["hypothesis"]
    for _ in range(tries):
        try:
            return DeviceHypothesis.model_validate(data), notes
        except ValidationError as e:
            errors = e.errors()
        err = errors[0]
        loc, kind = tuple(err["loc"]), err["type"]
        where = ".".join(map(str, loc)) or "the hypothesis"
        if not loc:  # a whole-hypothesis rule: a relation naming nothing, or an id used twice
            msg = str(err.get("msg", ""))
            if "relation" in msg and "names" in msg:
                name = msg.split("names ", 1)[1].split(",")[0].strip("'\" ")
                before = len(data.get("relations", []))
                data["relations"] = [r for r in data.get("relations", []) if name not in (r.get("source"), r.get("target"))]
                notes.append(f"left out {before - len(data['relations'])} relation(s) naming {name}, which is no piece or state")
                continue
            if "ids used twice" in msg:
                seen: set = set()
                for group in ("controls", "indicators", "mechanisms", "containers", "objects"):
                    kept = []
                    for p in data.get(group, []):
                        if p.get("id") in seen:
                            notes.append(f"left out a second {group[:-1]} called {p.get('id')}")
                            continue
                        seen.add(p.get("id"))
                        kept.append(p)
                    data[group] = kept
                continue
            raise ValueError(msg)
        cond = _condition_loc(loc)
        if cond is not None and len(loc) > len(cond):  # inside one condition: read the whole condition the way models write them
            holder, k = _at(data, cond)
            new = _condition(holder[k])
            if new != holder[k]:
                notes.append(f"read {'.'.join(map(str, cond))} as a condition: {new}")
                holder[k] = new
                continue
        parent, key = _at(data, loc)
        value = parent[key] if (isinstance(parent, dict) and key in parent) or (isinstance(parent, list) and isinstance(key, int) and key < len(parent)) else None
        field = next((k for k in reversed(loc) if isinstance(k, str)), "")
        fixed = False
        if cond == loc and kind in ("model_type", "dict_type"):
            new = _condition(value)
            if new != value:
                parent[key] = new
                notes.append(f"read {where} as a condition: {new}")
                fixed = True
        elif kind == "extra_forbidden":
            parent.pop(key)
            notes.append(f"ignored {where}: not a field there")
            fixed = True
        elif kind in ("model_type", "dict_type") and field == "range":
            new = _range(value)
            if new != value:
                parent[key] = new
                notes.append(f"read {where} as a range: {new}")
                fixed = True
        elif kind == "list_type" and value is not None:
            parent[key] = [s.strip() for s in value.split(",")] if isinstance(value, str) and "," in value else [value]
            notes.append(f"read {where} as a list")
            fixed = True
        elif kind == "string_type" and value is not None:
            parent[key] = value if isinstance(value, str) else json.dumps(value)
            notes.append(f"read {where} as text")
            fixed = True
        elif kind == "bool_parsing":
            parent[key] = bool(value) and str(value).strip().lower() not in ("no", "false", "none", "0", "unknown")
            notes.append(f"read {where} as {parent[key]}")
            fixed = True
        elif kind == "literal_error" and field == "op" and isinstance(value, str) and OP_WORDS.get(value.strip().lower()):
            parent[key] = OP_WORDS[value.strip().lower()]
            fixed = True
        elif kind == "literal_error" and field == "primitive" and isinstance(value, str) and PRIMITIVE_WORDS.get(value.strip().lower()):
            parent[key] = PRIMITIVE_WORDS[value.strip().lower()]
            notes.append(f"read {where} {value!r} as {parent[key]}")
            fixed = True
        elif kind == "literal_error" and field == "returns":
            parent.pop(key)
            notes.append(f"ignored {where}: {value!r} isn't one of momentary, latching, continuous")
            fixed = True
        elif kind == "missing" and field == "steps" and isinstance(parent, dict):
            parent["steps"] = []
            notes.append(f"{where}: no steps given")
            fixed = True
        if not fixed:
            dropped = _drop_item(data, loc)
            if dropped is None:
                raise ValueError(f"{where}: {err.get('msg')}")
            notes.append(f"left out {dropped}: {err.get('msg')} at {where}")
    raise ValueError("too many problems to repair")
