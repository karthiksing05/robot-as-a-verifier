"""What the model can do, and the limits on it. Each tool checks its own preconditions and answers with an error the model
can read, so the model chooses the order and code enforces the rules. The harness stays the MCP client: the model never
polls or sees routine_wait, and gets no joint, waypoint or force command. Verdicts and the reward stay in plain code.

A new robot ability needs no tool here: it arrives as a skill in SystemStatus.actions, and the model plans it as a step.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from rav_contracts import (DEVICE_CONTROL, Check, Checkpoint, Control, Decision, EscalationPolicy, Plan, Report, RoutineHandle, SceneInventory,
                           Step, StepOutcome, StepVerdict, SystemStatus, TestRequest, check_steps)

from . import checkback as cb
from .amendments import APPROVE, classify
from .client import ToolFailed
from .commands import log_crossing, wait_for_stop
from .loop import MAX_UNSIGNED_AMENDMENTS, Approver, Steering
from .manual import Manual
from .model import Image, ToolRequest, ToolSpec
from .reward import coverage, reward
from .runlog import RunLog
from .trace import ToolRejected, Tracer
from .verdicts import findings_from, settle

Ask = Callable[[str], str | None]
CHECKLIST_SHOWN = 25  # untested keys shown on a stop


def _hypothesis_schema() -> dict:
    from .theory import hypothesis_schema

    return hypothesis_schema()


HYPOTHESIS_SCHEMA = _hypothesis_schema()
SAME_PLACE_MM = 30.0  # after a look, a control this close to where the layout says it was is the same control
FORCE_POINTS = 40
STAGE = {"look_at_device": "MAP", "get_scene": "MAP", "get_status": "MAP", "recover": "MAP", "read_manual": "PLAN", "record_hypothesis": "PLAN", "propose_plan": "PLAN",
         "ask_operator": "PLAN", "run_plan": "TEST", "answer_stop": "TEST", "get_evidence": "TEST", "finish_run": "REPORT"}
# How to tell the robot's trouble from the device's has one more source than a verdict: a scene is only true until the device moves.
STREAK, OFFSET_MM = 2, 3.0


def _value(text: Any) -> Any:
    """A check's value arrives as text, since one tool schema can't say "a number or a word" to every provider."""
    if not isinstance(text, str):
        return text
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(text)
    except ValueError:
        return text


def holds(check: Check, actual: Any) -> bool | None:
    """Whether a reading meets a check. None: nothing to compare."""
    if actual is None:
        return None
    if check.op == "==":
        return actual == check.value or str(actual) == str(check.value)
    if not isinstance(actual, (int, float)) or not isinstance(check.value, (int, float)):
        return None
    return actual <= check.value if check.op == "<=" else actual >= check.value if check.op == ">=" else None


def _thin(trace: list, n: int = FORCE_POINTS) -> list:
    return trace if len(trace) <= n else [trace[round(i * (len(trace) - 1) / (n - 1))] for i in range(n)]


def _middle(controls: list[Control]) -> list[float]:
    real = [c for c in controls if c.id != DEVICE_CONTROL] or controls
    return [sum(c.pos_mm[i] for c in real) / len(real) for i in range(3)]


def _control_view(c: Control) -> dict:
    return c.model_dump(mode="json", exclude_none=True, exclude={"source"})


class ToolBelt:
    def __init__(self, system1, request: TestRequest, log: RunLog, tracer: Tracer, approve: Approver, steering: Steering,
                 policy: EscalationPolicy, manual: Manual | None = None, ask: Ask | None = None, on_state: Callable[[str, str], None] | None = None,
                 wake_on_checkpoint: bool = False):
        self.system1, self.request, self.log, self.tracer, self.approve, self.steering = system1, request, log, tracer, approve, steering
        self.policy, self.manual, self.ask, self.wake_on_checkpoint = policy, manual, ask, wake_on_checkpoint
        self.on_state = on_state or (lambda state, detail: None)
        self.status: SystemStatus = system1.system_status()
        self.scene: SceneInventory | None = None
        self.fallback: Plan | None = None
        self.scene_version = 0
        self.scene_stale: str | None = None
        self.canon: dict[str, str] = {}  # the current scene's ids to the id each control first had
        self.controls: dict[str, Control] = {}  # by first id: every control ever seen, for the report
        self.ready: Plan | None = None  # approved, not yet started
        self.approved: list[Step] = []
        self.amendments = 0
        self.plans = 0
        self.steps: dict[str, Step] = {}
        self.requires: dict[str, list[Check]] = {}
        self.queue: deque[Step] = deque()
        self.handle: RoutineHandle | None = None
        self.holding = False
        self.needs_recovery: str | None = None
        self.verdicts: list[StepVerdict] = []
        self.seqs: dict[int, int] = {}
        self.readings: dict[str, Any] = {}
        self.skipped_by_operator: set[str] = set()
        self.tests_of: dict[str, list[str]] = {}  # step id -> checklist keys it gives evidence for
        self.intents: list = []  # the checklist from the model's hypothesis, if it recorded one
        self.checklist_nudged = False
        self.suspect: str | None = None
        self.recent: deque[dict] = deque(maxlen=4)
        self.finished: dict | None = None
        self.operator_note: str | None = None
        self.turn: str | None = None
        self.images: list[Image] = []
        # check-back (checkback.py): on for every model run; off only where a test asks
        self.check_back = True
        self.own: dict[str, set[str]] = {}  # control (first id) -> the channels its verdicts say it drives
        self.first_state: dict[str, Any] | None = None  # the first completed look
        self.first_readings: dict[str, Any] = {}  # each reading as first seen, before anything changed it
        self.changes_since_look = 0
        self.changed_any = False
        self.closing_tried = False
        self.closing_nudged = False
        self.side_effects: list[str] = []
        self.checkback = {"plans_refused": 0, "output_checks_failed": 0, "checkbacks_run": 0, "checkbacks_failed": 0, "closing_looks": 0,
                          "closing_differences": 0}

    # --- the model's view ------------------------------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        names = {p.name: p for a in self.status.actions for p in a.params}
        check = {"type": "object", "properties": {"metric": {"type": "string", "description": f"One of {', '.join(self.status.check_metrics)}"},
                                                  "op": {"type": "string", "enum": ["<=", ">=", "==", "changed"]},
                                                  "value": {"type": "string", "description": "Number or text, written as text"}},
                 "required": ["metric", "op"]}
        step = {"type": "object", "properties": {
            "id": {"type": "string"}, "skill": {"type": "string"}, "target": {"type": "string", "description": "A control id from the current scene"},
            "expected": {"type": "string", "description": "What should happen"}, "quote": {"type": "string", "description": "The manual's line this comes from"},
            "why": {"type": "string", "description": "With skill none: why this control can't be tested"},
            "check": {"type": "array", "items": check, "description": "Measurable results to evaluate on this step"},
            "requires": {"type": "array", "items": check, "description": "Readings that must hold before this step for its checks to mean anything"},
            "tests": {"type": "array", "items": {"type": "string"}, "description": "Checklist keys from record_hypothesis that this step gives evidence for"}},
            "required": ["id", "skill", "target"]}
        if names:
            step["properties"]["params"] = {"type": "object", "description": "Numbers, per get_status",
                                            "properties": {n: {"type": "number", "description": p.about or p.unit or n} for n, p in names.items()}}
        no_args = {"type": "object", "properties": {}}
        return [
            ToolSpec("get_status", "The skills on offer with their limits, what the robot is doing, and how each control stands so far.", no_args),
            ToolSpec("look_at_device", "Runs the robot's survey and returns what it found. Takes minutes. Plans are checked against the latest look.", no_args),
            ToolSpec("get_scene", "The latest scene again.", no_args),
            ToolSpec("read_manual", "The product's manual: one page, or a search.", {"type": "object", "properties": {
                "page": {"type": "integer", "description": "Page number"}, "query": {"type": "string", "description": "Words to search for"}}}),
            ToolSpec("get_evidence", "A trace or image, by a reference from a stop or the scene. Ask only when the summary isn't enough.", {
                "type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}),
            ToolSpec("record_hypothesis", "Records what you believe the device is, from the manual and the scan, and derives a checklist of "
                     "properties worth testing on it. You get its keys; get_status and each stop list the ones still untested. Plan from it; "
                     "it isn't a plan, and you can test more.", {
                "type": "object", "properties": {"hypothesis": {**HYPOTHESIS_SCHEMA, "description": (
                    "controls [{id, label, primitive: press|turn|flip|slide|push_latch|hook_pull|pick|place, returns: momentary|latching|continuous, "
                    "range {low, high, unit, direction}}], indicators [{id, label, kind: text_display|light|led|beeper|flag, shows [state], vocabulary [messages]}], "
                    "mechanisms [{id, kind: hinge|slide|latch|spring, rest, operated_by}], containers [{id, kind, accepts [object ids], sensed}], objects [{id, fits}], "
                    "state [{name, values or range, default, persists, is_mode}], relations [{kind: enables|requires|interlocks|drives|displays, source, target, "
                    "when {subject, op, value}, mapping, message}], procedures [{name, goal, manual_ref, steps [{primitive, target, pre [conditions], effects [conditions]}]}]. "
                    "Use the scene's control ids. Every field but ids is optional; say only what the manual or the scan supports")}},
                "required": ["hypothesis"]}),
            ToolSpec("propose_plan", "Submits steps. They're checked, then go for approval if they need it. Nothing moves until run_plan.", {
                "type": "object", "properties": {"steps": {"type": "array", "items": step}, "why": {"type": "string"}}, "required": ["steps"]}),
            ToolSpec("run_plan", "Runs the approved plan and returns at the next stop that needs you.", no_args),
            ToolSpec("answer_stop", "Answers a stop: continue, amend (replaces the remaining steps), skip, or abort. Returns at the next stop.", {
                "type": "object", "properties": {"kind": {"type": "string", "enum": ["continue", "amend", "skip", "abort"]},
                                                 "steps": {"type": "array", "items": step}, "targets": {"type": "array", "items": {"type": "string"}},
                                                 "note": {"type": "string"}}, "required": ["kind"]}),
            ToolSpec("recover", "After a safety stop or when the device may have moved: home the arm, or home and look again.", {
                "type": "object", "properties": {"action": {"type": "string", "enum": ["home", "re_explore"]}, "note": {"type": "string"}}, "required": ["action"]}),
            ToolSpec("ask_operator", "Asks a person. The arm holds until they answer.", {
                "type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}),
            ToolSpec("finish_run", "Ends the run. Every control needs a result or a reason here.", {
                "type": "object", "properties": {"summary": {"type": "string"}, "controls": {"type": "array", "items": {
                    "type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}, "why": {"type": "string"}}, "required": ["id"]}}},
                "required": ["summary"]}),
        ]

    def run(self, request: ToolRequest, turn: str | None) -> dict:
        """One model tool call, traced. Raises ToolRejected for what the model got wrong."""
        self.turn, self.images = turn, []
        fn = getattr(self, f"tool_{request.name}", None)
        if fn is None:
            skills = {a.skill for a in (self.status.actions if self.status else [])}
            hint = f" {request.name} is one of the robot's skills: put it in a step of a plan." if request.name in skills else ""
            error = ToolRejected("unknown_tool", f"No tool called {request.name}.{hint} Tools: {', '.join(t.name for t in self.specs())}")
            self.tracer.stage = self.tracer.stage or "MAP"
            return self.tracer.call(request.name, request.args, lambda: _raise(error), turn=turn)
        self.tracer.stage = STAGE.get(request.name, self.tracer.stage)
        self.on_state("calling", request.name)
        def invoke():
            try:
                return fn(**request.args)
            except TypeError as e:
                raise ToolRejected("bad_args", f"{request.name}: {e}") from e
        return self.tracer.call(request.name, request.args, invoke, turn=turn)

    def progress(self) -> dict:
        """Each control in the current scene, by what its attempts add up to so far."""
        settled = settle(self.verdicts)
        out = {}
        for c in (self.scene.controls if self.scene else []):
            if c.id == DEVICE_CONTROL:
                continue
            s = settled.get(self.canon.get(c.id, c.id))
            out[c.id] = (s.status + ("" if s.confirmed else " (once, not retested)")) if s else "untested"
        return out

    def _plan_state(self) -> str:
        if self.holding:
            return "holding at a stop: answer_stop"
        if self.handle:
            return "a routine is running"
        return "an approved plan is ready: run_plan" if self.ready else "idle"

    def tool_get_status(self) -> dict:
        self.status = self.system1.system_status()
        return {"robot": self.status.robot, "state": self.status.state, "now": self._plan_state(),
                "actions": [a.model_dump(mode="json", exclude_none=True) for a in self.status.actions],
                "max_force_n": self.status.max_force_n, "check_metrics": self.status.check_metrics,
                "progress": self.progress(), "readings_seen": self.readings, "needs_recovery": self.needs_recovery, "scene_stale": self.scene_stale,
                **({"checklist_untested": [{"key": t.key, "test": t.statement, "evidence": t.oracle, **({"after": t.blocked_by} if t.blocked_by else {})}
                                           for t in self.intents if t.key in set(self.untested(None))]} if self.intents else {})}

    def _scene_view(self) -> dict:
        if self.scene is None:
            return {"scene": None, "note": "Nothing seen yet: look_at_device."}
        return {"scene_version": self.scene_version, "controls": [_control_view(c) for c in self.scene.controls],
                "notes": self.scene.notes, "frames": self.scene.frames, "progress": self.progress()}

    def tool_get_scene(self) -> dict:
        return self._scene_view()

    def tool_read_manual(self, page: int | None = None, query: str | None = None) -> dict:
        if self.manual is None:
            return {"available": False, "note": "No manual for this product."}
        try:
            return self.manual.read(int(page) if page else None, query)
        except ValueError as e:
            raise ToolRejected("bad_args", str(e)) from e

    def tool_get_evidence(self, ref: str) -> dict:
        try:
            if ref.startswith("frame:"):
                frame = self.system1.evidence_frame(ref)
                self.images.append(Image(frame.mime, frame.data_b64, f"{ref}: {frame.caption}".strip(": ")))
                return {"ref": ref, "caption": frame.caption, "width": frame.width, "height": frame.height, "shown": "the image follows"}
            found = self.system1.evidence_get(ref)
        except (ToolFailed, KeyError) as e:
            raise ToolRejected("unknown_target", f"No evidence called {ref}") from e
        view = found.model_dump(mode="json", exclude_none=True)
        view["force_trace"] = _thin(view.get("force_trace", []))
        return view

    # --- looking ---------------------------------------------------------------------------------

    def _adopt_scene(self, scene: SceneInventory, fallback: Plan | None) -> list[str]:
        """The latest look replaces the scene. Ids may change between looks, so a control keeps the id it first had in the
        record: verdicts already earned stay with the control that earned them. Anything validated against an older
        scene is dropped."""
        notes, old, canon = [], dict(self.controls), {}
        moved = (0.0, 0.0, 0.0)
        if self.scene is not None and scene.controls and self.scene.controls:
            before = _middle(self.scene.controls)
            after = _middle(scene.controls)
            moved = tuple(a - b for a, b in zip(after, before))
            if math.dist(after, before) > 5.0:
                notes.append(f"the layout moved {math.dist(after, before):.0f} mm since the last look")
        taken: set[str] = set()
        previous = {self.canon.get(c.id, c.id): c for c in (self.scene.controls if self.scene else []) if c.id != DEVICE_CONTROL}
        for c in scene.controls:
            if c.id == DEVICE_CONTROL:  # the device itself: there to be moved, not tested
                canon[c.id] = c.id
                continue
            best, gap = None, SAME_PLACE_MM
            for first, p in previous.items():
                d = math.dist([a + b for a, b in zip(p.pos_mm, moved)], c.pos_mm)
                if first not in taken and p.kind == c.kind and d < gap:
                    best, gap = first, d
            first = best
            if first is None:
                first = c.id if c.id not in old else f"{c.id}@look{self.scene_version + 1}"
            taken.add(first)
            canon[c.id] = first
            self.controls[first] = c.model_copy(update={"id": first})
        self.scene, self.fallback, self.canon = scene, fallback, canon
        self.scene_version += 1
        self.scene_stale, self.suspect, self.ready = None, None, None
        self.recent.clear()
        self.log.emit("scene_ready", without_device(scene))
        return notes

    def _look(self) -> dict:
        if self.changes_since_look and self.first_state is not None:
            self.closing_tried = True
            self.checkback["closing_looks"] += 1
        self.handle = self._inner("routine_start", {"routine": "explore"}, lambda: self.system1.routine_start("explore", policy=self.policy))
        view = self._wait()
        if view["status"] == "completed":
            report = self.system1.scene_get()
            notes = self._adopt_scene(report.scene, report.fallback_plan)
            self.changes_since_look = 0
            if self.first_state is None:
                self.first_state = self._scene_state()
            view.pop("device_may_have_moved", None)
            view.pop("scene_stale", None)
            view.update(self._scene_view())
            if notes:
                view["layout"] = notes
        return view

    def _scene_state(self) -> dict[str, Any]:
        controls = [c.model_copy(update={"id": self.canon.get(c.id, c.id)}) for c in (self.scene.controls if self.scene else []) if c.id != DEVICE_CONTROL]
        return cb.state_of(controls, {})

    def closing_differences(self) -> list[str]:
        """The latest look and readings against the first: what the run has left changed."""
        if self.first_state is None:
            return []
        first = {**self.first_state, **cb.state_of([], self.first_readings)}
        now = {**self._scene_state(), **cb.state_of([], {k: v for k, v in self.readings.items() if k in self.first_readings})}
        return cb.differences(first, now)

    def _closing_refusal(self) -> str | None:
        """(iii): the run ends with a look compared with the first, and the device back where it started, or the reason."""
        if not self.check_back or self.operator_note or self.needs_recovery or self.first_state is None:
            return None
        if self.changes_since_look and not self.closing_tried:
            return ("Look at the device once more before finishing (look_at_device): the closing look is compared with the first, so the report "
                    "says what this run left changed. Then call finish_run again.")
        diffs = self.closing_differences()
        if diffs and not self.closing_nudged:  # once: then finishing anyway is the model's call, and the report lists them
            self.closing_nudged = True
            return (f"The device isn't as the first look found it: {'; '.join(diffs[:12])}. Return it to its starting state with a plan "
                    "(and check it back), then look again; or call finish_run again and say in the summary why it stays this way.")
        return None

    def tool_look_at_device(self) -> dict:
        self._guard_idle("looking again")
        return self._look()

    def _guard_idle(self, doing: str) -> None:
        if self.holding:
            raise ToolRejected("refused", f"A routine is holding at a stop: answer_stop first, or abort it, before {doing}.")
        if self.needs_recovery:
            raise ToolRejected("refused", f"The last routine ended on a safety stop ({self.needs_recovery}). Call recover first.")

    # --- planning --------------------------------------------------------------------------------

    def _parse_steps(self, raw: Any) -> tuple[list[Step], dict[str, list[Check]], list[str]]:
        if not isinstance(raw, list) or not raw:
            raise ToolRejected("bad_args", "steps must be a non-empty list")
        steps, requires, problems = [], {}, []
        for item in raw:
            try:
                item = dict(item)
                reqs = item.pop("requires", None) or []
                tests = item.pop("tests", None) or []
                for c in [*reqs, *(item.get("check") or [])]:
                    if "value" in c:
                        c["value"] = _value(c["value"])
                step = Step(**item)
                steps.append(step)
                requires[step.id] = [Check(**r) for r in reqs]
                self.tests_of[step.id] = [str(t) for t in tests] if isinstance(tests, list) else []
            except (ValidationError, TypeError, ValueError) as e:
                problems.append(f"{item.get('id', '?') if isinstance(item, dict) else item}: {e}".replace("\n", " ")[:400])
        return steps, requires, problems

    def _validate(self, steps: list[Step], malformed: list[str] | None = None) -> None:
        if self.scene is None:
            raise ToolRejected("refused", "Nothing seen yet: look_at_device first.")
        if self.scene_stale:
            raise ToolRejected("refused", f"The scene is out of date ({self.scene_stale}): look_at_device, then plan from what it finds.")
        self.status = self.system1.system_status()
        problems = [*(malformed or []), *check_steps(steps, self.scene.controls, self.status.actions)]
        problems += [f"{s.id}: the operator asked not to test {s.target}" for s in steps if self.canon.get(s.target, s.target) in self.skipped_by_operator]
        problems += unsourced_bounds(steps)
        if self.check_back:
            missing = cb.missing_checkback(steps, {s.target: self.own.get(self.canon.get(s.target, s.target), set()) for s in steps},
                                           [c.id for c in self.scene.controls if self.canon.get(c.id, c.id) in {v.target for v in self.verdicts}],
                                           self._can_observe())
            if missing:
                self.checkback["plans_refused"] += 1
                self.log.emit("message", {"role": "harness", "text": f"check-back missing: {len(missing)} problems", "checkback_missing": missing})
            problems += missing
        if problems:
            kind = "unknown_target" if all("no control called" in p for p in problems) else "bad_args"
            raise ToolRejected(kind, "Nothing moved. Fix these and send the steps again:\n" + "\n".join(problems))

    def _can_observe(self) -> bool:
        kinds = {c.kind for c in (self.scene.controls if self.scene else []) if c.id != DEVICE_CONTROL}
        return any(a.skill == "observe" and (not a.kinds or kinds & set(a.kinds)) for a in self.status.actions)

    def _level(self, steps: list[Step], remaining: list[Step]) -> int:
        """Plain code grades the change against what a person approved. Moving the device always needs a person."""
        canon = lambda s: s.model_copy(update={"target": self.canon.get(s.target, s.target)})  # noqa: E731
        level = classify(self.approved, [canon(s) for s in remaining], [canon(s) for s in steps])
        if self.amendments > MAX_UNSIGNED_AMENDMENTS or any(s.skill == "reposition" for s in steps):
            level = max(level, APPROVE)
        return level

    def _sign(self, kind: str, ref: str) -> str | None:
        self.on_state("waiting_person", f"{kind} {ref}")
        self.log.emit("approval_needed", {"kind": kind, "ref": ref})
        by = self.approve(kind, ref)
        if by is not None:
            self.log.emit("approved", {"kind": kind, "ref": ref, "by": by})
        return by

    def _accept(self, steps: list[Step], requires: dict[str, list[Check]]) -> None:
        for s in steps:
            self.steps[s.id] = s
            self.requires[s.id] = requires.get(s.id, [])
        self.approved += [s.model_copy(update={"target": self.canon.get(s.target, s.target)}) for s in steps]

    def tool_propose_plan(self, steps: Any = None, why: str = "") -> dict:
        closed = None
        if self.holding and not self.needs_recovery:  # a new plan replaces what's left of the held one: close it, rather than refuse
            self._resume(Decision(kind="abort", note="replaced by a new plan"))
            self._wait()
            closed = "The routine that was holding at a stop has been closed, so this plan can run."
        self._guard_idle("planning")
        parsed, requires, malformed = self._parse_steps(steps)
        self._validate(parsed, malformed)
        self.plans += 1
        plan = Plan(plan_id=f"plan-{self.plans}", steps=parsed, source="model")
        first = not self.approved
        if not first:
            self.amendments += 1
        level = APPROVE if first else self._level(parsed, [])
        self.log.emit("plan_ready", plan)
        if level >= APPROVE and self._sign("plan", plan.plan_id) is None:
            self.log.emit("message", {"role": "harness", "text": f"{plan.plan_id} refused"})
            return {"approved": False, "plan_id": plan.plan_id, "note": "A person refused this plan. Nothing moved. Ask why, or change it."}
        if not first:
            self.log.emit("plan_amended", {"level": level, "by": None, "steps": [s.id for s in parsed], "why": why})
        self._accept(parsed, requires)
        self.ready = plan
        return {"approved": True, "plan_id": plan.plan_id, "next": "run_plan", **({"note": closed} if closed else {})}

    def tool_run_plan(self) -> dict:
        self._guard_idle("running a plan")
        if self.handle:
            raise ToolRejected("refused", "A routine is already running.")
        if self.scene_stale:
            raise ToolRejected("refused", f"The scene is out of date ({self.scene_stale}): look_at_device first.")
        if self.ready is None:
            raise ToolRejected("refused", "No approved plan is ready: propose_plan first.")
        plan, self.ready = self.ready, None
        self.queue = deque(plan.steps)
        self.handle = self._start("run_plan", plan)
        return self._wait()

    def _start(self, routine: str, plan: Plan | None = None) -> RoutineHandle:
        try:
            return self._inner("routine_start", {"routine": routine}, lambda: self.system1.routine_start(routine, plan, self.policy))
        except ToolFailed as e:
            raise ToolRejected("refused", str(e)) from e

    def _inner(self, tool: str, args: dict, fn: Callable[[], Any]) -> Any:
        return self.tracer.call(f"system1.{tool}", args, fn, turn=self.turn, caller="rules")

    # --- the routine -----------------------------------------------------------------------------

    def _judge_checks(self, step: Step, summary, verdict: StepVerdict) -> StepVerdict:
        """A failed check counts against the control only when what the step declared it needs was truly there. Otherwise
        it says nothing about the product. The readings are the robot's: this only applies the rule, in plain code."""
        failed = [c for c in summary.checks if c.passed is False]
        if failed:
            requires = self.requires.get(step.id, [])
            unmet = [f"{r.metric} {r.op} {r.value} (seen: {self._reading(r.metric)})" for r in requires if holds(r, self._reading(r.metric)) is not True]
            counted = not unmet
            self.log.emit("check_judged", {"step": step.id, "target": verdict.target, "failed": [c.model_dump(mode="json") for c in failed],
                                           "requires": [r.model_dump(mode="json") for r in requires], "met": not unmet, "counted": counted,
                                           "why": "" if counted else f"needed {', '.join(unmet)}"})
            if counted and verdict.status == "passed":
                said = "; ".join(f"{c.metric} {c.op} {c.value}, got {c.actual}" for c in failed)
                return verdict.model_copy(update={"status": "failed", "label": "wrong_feedback", "reason": f"{verdict.reason}. Expected {said}"})
        return verdict

    def _note_checkback(self, step: Step, first: str, verdict: StepVerdict, summary, trace) -> None:
        own = self.own.setdefault(first, set())
        for channel, values in trace.readout_change.items():  # what each reading was before anything changed it
            if values:
                self.first_readings.setdefault(channel, values[0])
        if not cb.changes(step) and not self.changed_any:  # a read before anything changed is the starting state; one after isn't
            snapshot = trace.measures.get("readings")
            for channel, value in (snapshot.items() if isinstance(snapshot, dict) else []):
                self.first_readings.setdefault(channel, value)
            if trace.measures.get("lcd") is not None:
                self.first_readings.setdefault("lcd", trace.measures["lcd"])
        failed = {c.metric for c in summary.checks if c.passed is False}
        outputs = {c.metric for c in cb.output_checks(step, own | ({verdict.channel} if verdict.channel else set()))}
        if step.skill == "observe" and outputs:
            self.checkback["checkbacks_run"] += 1
            self.checkback["checkbacks_failed"] += bool(failed & outputs)
        elif cb.changes(step) and verdict.status != "inconclusive":
            self.changed_any = True
            self.changes_since_look += 1
            self.closing_tried = False
            self.checkback["output_checks_failed"] += bool(failed & outputs) and verdict.status == "passed"  # it moved, and the device showed it wrong
            checked = {c.metric.removeprefix("reading:") for c in step.check}
            for channel, values in trace.readout_change.items():
                if channel != verdict.channel and channel not in checked and len(values) > 1 and values[0] != values[-1]:
                    self.side_effects.append(f"{step.id} ({step.skill} {first}) also changed {channel}: {values[0]} -> {values[-1]}")
        if verdict.channel:
            own.add(verdict.channel)

    def _reading(self, metric: str) -> Any:
        return self.readings.get(metric.removeprefix("reading:"))

    def _note_readings(self, trace) -> None:
        snapshot = trace.measures.get("readings")
        if isinstance(snapshot, dict):
            self.readings.update(snapshot)
        for channel, values in trace.readout_change.items():
            if values:
                self.readings[channel] = values[-1]
        if trace.measures.get("lcd") is not None:
            self.readings["lcd"] = trace.measures["lcd"]

    def _record(self, stop: Checkpoint) -> list[dict]:
        results = []
        for summary in stop.verdicts:
            verdict = summary.verdict
            step = self.steps.get(verdict.step) or Step(id=verdict.step, skill="none", target=verdict.target, why="not in a known plan")
            first = self.canon.get(verdict.target, verdict.target)
            for i, s in enumerate(self.queue):
                if s.id == step.id:
                    del self.queue[i]
                    break
            self.log.emit("step_started", step.model_copy(update={"target": first}))
            trace = self.system1.evidence_get(summary.trace_ref)
            judged = self._judge_checks(step, summary, verdict).model_copy(update={"target": first})
            self._note_checkback(step, first, verdict, summary, trace)
            self._note_readings(trace)
            event = self.log.emit("step_finished", StepOutcome(trace=trace, verdict=verdict.model_copy(update={"target": first})))
            self.verdicts.append(judged)
            self.seqs[id(judged)] = event.seq
            self.recent.append({"target": first, "status": judged.status, "measures": summary.measures})
            view = {"step": verdict.step, "target": verdict.target, "status": judged.status, "label": judged.label, "reason": judged.reason,
                    "attempts": summary.attempts, "peak_force_n": summary.peak_force_n, "travel_mm": summary.travel_mm, "stop": summary.stop_reason,
                    "readings": summary.readout_change, "measures": summary.measures, "trace_ref": summary.trace_ref}
            if summary.checks:
                view["checks"] = [c.model_dump(mode="json", exclude_none=True) for c in summary.checks]
            if judged.status != verdict.status:
                view["sensor_verdict"] = verdict.status
            results.append({k: v for k, v in view.items() if v not in (None, {}, [])})
        return results

    def _suspect_scene(self, stop: Checkpoint) -> str | None:
        """Signs the device isn't where the scene says. Only a hint to the model: it decides what to do about it."""
        if stop.escalation and stop.escalation.code == "pose_unstable":
            return "the robot reports its corrections keep growing"
        recent = list(self.recent)
        misses = [r for r in recent[-STREAK:] if r["status"] == "inconclusive"]
        if len(misses) == STREAK and len({r["target"] for r in misses}) == STREAK:
            return f"{STREAK} different controls in a row couldn't be tested"
        if sum(r["measures"].get("refined") is False for r in recent[-3:]) >= STREAK:
            return "the last looks before contact keep failing to find their parts"
        offsets = [r["measures"].get("contact_offset_mm") for r in recent[-3:]]
        if len(offsets) == 3 and all(isinstance(o, (int, float)) for o in offsets):
            offsets = [abs(o) for o in offsets]
            if offsets[0] < offsets[1] < offsets[2] and offsets[2] > OFFSET_MM:
                return f"contact offsets keep growing ({offsets[0]:.1f}, {offsets[1]:.1f}, {offsets[2]:.1f} mm)"
        return None

    def _note_stale(self, stop: Checkpoint) -> None:
        """The robot says when a scene's poses are old: after a move, whoever or whatever did it."""
        moved = (stop.escalation and stop.escalation.measured.get("pattern") == "device_moved") or \
            any(self.steps.get(s.verdict.step) and self.steps[s.verdict.step].skill == "reposition" for s in stop.verdicts)
        if moved:
            scene = self.system1.scene_get().scene
            if scene is not None and scene.stale:
                self.scene_stale = "the device moved"

    def _wait(self) -> dict:
        """Waits for the next stop that needs the model. A clean checkpoint needs nobody, so it's logged and answered here:
        the Console still sees each step, and the model spends no turn on it."""
        self.on_state("arm", self.handle.routine)
        results: list[dict] = []
        while True:
            stop = wait_for_stop(self.system1, self.handle, lambda: any(c.kind == "stop" for c in self.steering.commands))
            log_crossing(self.log, self.handle, stop, self.policy)
            results += self._record(stop)
            self._note_stale(stop)
            was_suspect, self.suspect = self.suspect, self._suspect_scene(stop) or self.suspect
            if stop.stop == "safety_abort":
                self.needs_recovery = stop.reason or "safety stop"
            if stop.status != "paused":
                self.handle, self.holding = None, False
                break
            self.holding = True
            newly_suspect = self.suspect and not was_suspect
            judged_failure = any(r["status"] == "failed" for r in results)
            if stop.stop == "checkpoint" and not (self.wake_on_checkpoint or self.steering.commands or newly_suspect or judged_failure):
                self.system1.routine_resume(self.handle.routine_id, Decision())
                self.holding = False
                continue
            break
        self.tracer.step = stop.escalation.step if stop.escalation else None
        return self._stop_view(stop, results)

    def _stop_view(self, stop: Checkpoint, results: list[dict]) -> dict:
        view: dict[str, Any] = {"stop": stop.stop, "status": stop.status, "steps_done": stop.steps_done, "steps_total": stop.steps_total, "results": results}
        if stop.reason:
            view["reason"] = stop.reason
        if stop.escalation:
            view["escalation"] = stop.escalation.model_dump(mode="json", exclude_none=True)
        view["remaining"] = [s.id for s in self.queue]
        view["progress"] = self.progress()
        if self.intents:
            view["checklist_untested"] = self.untested()
        if self.suspect:
            view["device_may_have_moved"] = self.suspect
        if self.scene_stale:
            view["scene_stale"] = self.scene_stale
        if self.needs_recovery:
            view["next"] = "recover"
        elif self.holding:
            view["next"] = "answer_stop with kind abort, then recover with re_explore" if self.scene_stale else "answer_stop"
        return view

    def _resume(self, decision: Decision) -> None:
        try:
            self._inner("routine_resume", {"kind": decision.kind, "steps": [s.id for s in decision.steps], "targets": decision.targets},
                        lambda: self.system1.routine_resume(self.handle.routine_id, decision))
        except ToolFailed as e:  # it refused the answer and is still holding
            raise ToolRejected("bad_args", str(e)) from e
        self.holding = False

    def tool_answer_stop(self, kind: str = "continue", steps: Any = None, targets: list[str] | None = None, note: str | None = None) -> dict:
        if not self.holding:
            raise ToolRejected("refused", f"Nothing is holding at a stop. Now: {self._plan_state()}.")
        if kind not in ("continue", "amend", "skip", "abort"):
            raise ToolRejected("bad_args", f"kind {kind} isn't one of continue, amend, skip, abort")
        decision = Decision(kind=kind, note=note, targets=list(targets or []))
        if kind == "amend":
            parsed, requires, malformed = self._parse_steps(steps)
            self._validate(parsed, malformed)
            self.amendments += 1
            level = self._level(parsed, list(self.queue))
            by = None
            if level >= APPROVE:
                by = self._sign("amendment", f"amendment-{self.amendments}")
                if by is None:
                    self.log.emit("message", {"role": "harness", "text": f"amendment refused: {note or 'no reason given'}"})
                    return {"amended": False, "note": "A person refused this amendment. The routine is still holding, with its plan as it was.",
                            "next": "answer_stop"}
            self.log.emit("plan_amended", {"level": level, "by": by, "steps": [s.id for s in parsed], "why": note or ""})
            self._accept(parsed, requires)
            decision.steps = parsed
            self._resume(decision)
            self.queue = deque(parsed)
        else:
            self._resume(decision)
            if kind == "skip":
                self.queue = deque(s for s in self.queue if s.target not in decision.targets)
        return self._wait()

    def tool_recover(self, action: str = "home", note: str | None = None) -> dict:
        if action not in ("home", "re_explore"):
            raise ToolRejected("bad_args", "action must be home or re_explore")
        if self.handle and not self.holding:
            raise ToolRejected("refused", "A routine is running: wait for its stop.")
        if self.holding:
            self._resume(Decision(kind="abort", note=note or "recovering"))
            self._wait()
        if self.needs_recovery:  # always a person: no setting lowers this (docs/system-boundary.md)
            self.log.emit("message", {"role": "harness", "text": f"resuming after a safety stop needs a person: {self.needs_recovery}"})
            if self._sign("safety", self.needs_recovery) is None:
                return {"recovered": False, "note": "A person refused to resume. Finish the run with what you know."}
            self.needs_recovery = None
        self.handle = self._start("home")
        view = self._wait()
        if action == "re_explore" and view["status"] == "completed" and not self.needs_recovery:
            return self._look()
        return view

    def tool_record_hypothesis(self, hypothesis: Any = None, **rest: Any) -> dict:
        from . import theory

        if hypothesis is None and rest:  # sent without the wrapper
            hypothesis = rest
        try:
            h, repaired = theory.parse_hypothesis(hypothesis)
        except ValueError as e:
            raise ToolRejected("bad_args", f"That hypothesis can't be read: {str(e)[:600]}. Send an object with controls, indicators, state, "
                               "relations and procedures, per the schema.") from e
        self.intents = theory.derive_tests(h)
        unknown = sorted(c.id for c in h.controls if self.scene and c.id not in {x.id for x in self.scene.controls})
        self.log.emit("message", {"role": "harness", "text": f"hypothesis recorded: {len(self.intents)} properties to test",
                                  "checklist": [t.model_dump(mode="json") for t in self.intents], "repaired": repaired})
        return {"recorded": len(self.intents), "untested": [t.key for t in self.intents],
                "note": "Keys read property:subject. Put a step's keys in its tests. get_status explains any key; each stop lists those still untested. "
                        "Untested isn't passed, and a property behind a failed one is blocked, not passed.",
                **({"read_differently": repaired[:15] + ([f"and {len(repaired) - 15} more"] if len(repaired) > 15 else [])} if repaired else {}),
                **({"not_in_the_scene": unknown} if unknown else {})}

    def untested(self, limit: int | None = CHECKLIST_SHOWN) -> list[str]:
        if not self.intents:
            return []
        keys = self.checklist().untested
        return keys if limit is None else keys[:limit] + ([f"... {len(keys) - limit} more"] if len(keys) > limit else [])

    def checklist(self) -> Any:
        """What the checklist's properties add up to, from the steps that named them."""
        from . import theory

        latest = {v.step: v.status for v in self.verdicts}
        done: dict[str, Any] = {}
        for step, keys in self.tests_of.items():
            status = latest.get(step)
            if status in ("passed", "failed", "observed", "inconclusive"):
                for k in keys:
                    done[k] = "failed" if "failed" in (done.get(k), status) else status
        return theory.coverage(self.intents, done)

    def tool_ask_operator(self, question: str = "") -> dict:
        self.log.emit("message", {"role": "model", "text": question, "asks": True})
        self.on_state("waiting_person", "question")
        answer = self.ask(question) if self.ask else None
        if answer is None:
            return {"answer": None, "note": "Nobody answered. Decide for yourself, and say so in finish_run."}
        return {"answer": answer}

    def tool_finish_run(self, summary: str = "", controls: list[dict] | None = None) -> dict:
        if self.holding and not self.queue:  # held at its last step with nothing left to run: closing it is all that's left
            self._resume(Decision(kind="abort", note="finished: no steps left"))
            self._wait()
        if self.holding or self.handle:
            raise ToolRejected("refused", "A routine is still open: answer_stop with abort first.")
        if self.scene is None and not self.operator_note:
            raise ToolRejected("refused", "Nothing has been looked at yet.")
        said = {str(c.get("id")): c for c in (controls or []) if isinstance(c, dict)}
        progress = self.progress()
        missing = [i for i, s in progress.items() if s == "untested" and not (said.get(i) or {}).get("why")]
        if missing and not self.operator_note:
            raise ToolRejected("refused", f"No result or reason for: {', '.join(missing)}. Test them, or give each a why in controls.")
        if self.intents and not self.checklist_nudged and not self.operator_note:
            open_ = self.checklist().untested
            if open_:  # once: then finishing anyway is the model's call
                self.checklist_nudged = True
                raise ToolRejected("refused", f"{len(open_)} checklist properties have no evidence yet: {', '.join(open_[:20])}"
                                   f"{' …' if len(open_) > 20 else ''}. Test the ones a user would rely on, or call finish_run again to finish, "
                                   "saying in the summary which you left and why.")
        closing = self._closing_refusal()
        if closing:
            raise ToolRejected("refused", closing)
        claims = {i: str(c.get("status")) for i, c in said.items() if c.get("status")}
        self.log.emit("message", {"role": "model", "text": summary, "claims": claims})
        if self.intents:
            cov = self.checklist()
            self.log.emit("message", {"role": "harness", "text": f"checklist: {len(cov.tested)} tested, {len(cov.blocked)} blocked, {len(cov.untested)} untested",
                                      "checklist": cov.model_dump()})
        for i, claim in claims.items():
            actual = progress.get(i, "").split(" ")[0]
            if actual and actual != "untested" and claim not in (actual, "") and claim.split(" ")[0] != actual:
                self.log.emit("message", {"role": "harness", "text": f"the model says {i} {claim}; its attempts add up to {actual}"})
        self.finished = {"summary": summary, "claims": claims, "why": {i: c.get("why") for i, c in said.items() if c.get("why")}}
        return {"finished": True}

    # --- with no model ---------------------------------------------------------------------------

    def run_rules(self, why: str) -> None:
        """The model can't answer. Hold nothing open, test what's untested with the rule-based plan, labelled as such."""
        self.log.emit("message", {"role": "harness", "text": f"continuing with the rule-based plan: {why}"})
        self.turn = None
        if self.holding:
            self._resume(Decision(kind="abort", note="the model can't be reached"))
            self._wait()
        if self.needs_recovery:
            return
        if self.scene is None:
            if self._look()["status"] != "completed":
                return
        done = {v.target for v in self.verdicts}
        steps = [s for s in (self.fallback.steps if self.fallback else []) if self.canon.get(s.target, s.target) not in done]
        if not steps:
            return
        plan = Plan(plan_id="rules-fallback", steps=steps, source="rules")
        self.log.emit("plan_ready", plan)
        if self._sign("plan", plan.plan_id) is None:
            return
        self._accept(steps, {})
        self.queue = deque(steps)
        try:
            self.handle = self._start("run_plan", plan)
        except ToolFailed as e:  # what's already been found still gets reported
            self.log.emit("message", {"role": "harness", "text": f"the rule-based plan was refused: {e}"})
            return
        while True:
            self._wait()
            if not self.holding:
                return
            self._resume(Decision(kind="abort", note="the device moved") if self.scene_stale else Decision())

    # --- the record ------------------------------------------------------------------------------

    def report(self, status: str) -> Report:
        about_device = [v for v in self.verdicts if v.target != DEVICE_CONTROL]
        findings = findings_from(about_device, self.seqs)
        for finding in findings:
            self.log.emit("finding", finding)
        if self.scene_version > 1:  # the record names controls by their first id, across every look
            self.log.emit("scene_ready", SceneInventory(controls=[c for c in self.controls.values() if c.id != DEVICE_CONTROL], notes=["every control across the run's looks"]))
        cov = coverage(self.controls.values(), about_device)
        score = reward(cov)
        summary = (f"{len(cov.passed)} of {cov.detected} controls passed, {len(cov.failed)} failed, {len(cov.intermittent)} intermittent, "
                   f"{len(cov.inconclusive)} inconclusive, {len(cov.skipped)} skipped. Reward {score.value:.2f}.")
        if self.check_back and self.first_state is not None:
            diffs = self.closing_differences()
            self.checkback["closing_differences"] = len(diffs)
            if self.changes_since_look and not self.closing_tried:
                summary += " No closing look: the device's state at the end wasn't compared with the start."
            elif self.changes_since_look:
                summary += " The closing look didn't complete."
            else:
                summary += (f" Closing look differs from the first: {'; '.join(diffs)}." if diffs else " Closing look: the device is as the first look found it.")
            if self.side_effects:
                summary += f" Side effects: {'; '.join(self.side_effects[:12])}{' …' if len(self.side_effects) > 12 else ''}."
            self.log.emit("message", {"role": "harness", "text": "check-back: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in self.checkback.items()),
                                      "checkback": {**self.checkback, "side_effects": len(self.side_effects)}})
        report = Report(run_id=self.log.run_id, product=self.request.product, revision=self.request.revision, findings=findings, coverage=cov, reward=score,
                        summary=summary)
        self.log.emit("report_ready", report)
        self.log.write_report(report)
        self.log.emit("run_finished", {"status": status})
        return report


def unsourced_bounds(steps: list[Step]) -> list[str]:
    """A check against a value is a claim about what the product should do. It needs a source, or a made-up number
    becomes a finding. The robot's own rules already judge whether a step worked."""
    return [f"{s.id}: the check {c.metric} {c.op} {c.value} has no source. Quote the manual line it comes from in quote, or name "
            f"the spec in the check's source. With neither, leave the check out, or use op changed"
            for s in steps for c in s.check if c.op != "changed" and not (c.source or s.quote)]


def without_device(scene: SceneInventory) -> SceneInventory:
    """A scene as anything that lists controls should see it: the device itself is there to be moved, not tested."""
    return scene.model_copy(update={"controls": [c for c in scene.controls if c.id != DEVICE_CONTROL]})


def _raise(error: Exception):
    raise error
