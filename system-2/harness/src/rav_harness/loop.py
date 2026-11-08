"""The run loop: /explore, plan, approve, /test handling each stop System 1 reports, report, then the fix loop.

The model thinks, code moves, sensors decide. This file only sequences. Whatever proposes a plan or a patch has no say
in the verdicts: those come from System 1, and the reward from reward.py. The harness talks to System 1 only through
its tools, so System 1 can be on another machine.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from rav_contracts import (DEVICE_CONTROL, CADPatch, CadBackend, Checkpoint, Decision, EscalationPolicy, Finding, Plan, Report, RootCause,
                           SceneInventory, SteerCommand, Step, StepOutcome, StepVerdict, System1, TestRequest, TETHERED)

from .amendments import APPROVE, classify
from .commands import Responder, explore, log_crossing, rule_responder, wait_for_stop
from .reward import coverage, reward
from .runlog import RunLog, read_events
from .trace import Tracer
from .verdicts import findings_from

MAX_UNSIGNED_AMENDMENTS = 5  # per run; a guess until runs show what's normal
Planner = Callable[[TestRequest, SceneInventory, Plan], Plan]
Approver = Callable[[str, str], str | None]  # (kind, ref) -> approver's name, or None to refuse


def rule_planner(request: TestRequest, scene: SceneInventory, fallback: Plan) -> Plan:
    """The default until the manual-driven planner lands (Kanban: Harness: load the manual)."""
    return fallback


def auto_approve(kind: str, ref: str) -> str:
    """For mocks and tests only. A real arm run must pass a person's approval from the Console."""
    return "auto (mock)"


def robot_may_auto_approve(robot: str) -> bool:
    return robot in ("sim", "mock", "fake")


@dataclass
class Steering:
    """The command queue the Console writes to. The loop drains it each time System 1 is holding at a boundary."""
    commands: deque[SteerCommand] = field(default_factory=deque)

    def send(self, command: SteerCommand) -> None:
        self.commands.append(command)


def _apply_steering(steering: Steering, queue: deque[Step], log: RunLog) -> str:
    """Returns "run", "pause" or "stop"."""
    state = "run"
    while steering.commands:
        c = steering.commands.popleft()
        note = ""
        if c.kind == "stop":
            state, note = "stop", "stopping before the next step"
        elif c.kind == "pause":
            state, note = "pause", "paused"
        elif c.kind == "resume":
            state, note = "run", "resumed"
        elif c.kind == "prioritize":
            first = [s for s in queue if s.target == c.target]
            rest = [s for s in queue if s.target != c.target]
            queue.clear()
            queue.extend(first + rest)
            note = f"{len(first)} steps moved to the front"
        elif c.kind == "skip":
            kept = [s for s in queue if s.target != c.target]
            note = f"{len(queue) - len(kept)} steps skipped"
            queue.clear()
            queue.extend(kept)
        elif c.kind == "add_step" and c.step:
            queue.appendleft(c.step)
            note = f"added {c.step.id}"
        elif c.kind == "message":
            log.emit("message", {"role": "user", "text": c.text or "", "by": c.by})
            continue
        log.emit("steer_applied", {**c.model_dump(mode="json"), "note": note})
    return state


def _steer_at_boundary(steering: Steering, queue: deque[Step], log: RunLog, wait: Callable[[], None] | None) -> str:
    """Applies steering while System 1 is holding. Returns "run" or "stop". Without `wait`, a pause ends the run."""
    state = _apply_steering(steering, queue, log)
    while state == "pause":
        if wait is None:
            return "stop"
        wait()
        state = _apply_steering(steering, queue, log) if steering.commands else "pause"
    return state


def _amend(decision: Decision, plan: Plan, remaining: list[Step], approve: Approver, log: RunLog, count: int) -> Decision:
    """Gets an amended plan the sign-off its level asks for. If a person refuses, the plan stays as it was."""
    level = classify(plan.steps, remaining, decision.steps)
    if count > MAX_UNSIGNED_AMENDMENTS:  # however small each one is, a run that keeps changing its plan needs a person
        level = max(level, APPROVE)
    by = None
    if level >= APPROVE:
        by = approve("amendment", plan.plan_id)
        if by is None:
            log.emit("message", {"role": "harness", "text": f"amendment to {plan.plan_id} refused: {decision.note or 'no reason given'}"})
            return Decision()
    log.emit("plan_amended", {"level": level, "by": by, "steps": [s.id for s in decision.steps], "why": decision.note or ""})
    return decision


def run_test(system1: System1, request: TestRequest, log: RunLog, planner: Planner = rule_planner,
             approve: Approver = auto_approve, steering: Steering | None = None,
             wait: Callable[[], None] | None = None, policy: EscalationPolicy = TETHERED,
             respond: Responder = rule_responder) -> Report:
    """One coverage run. `wait` is called while paused; without one, a pause ends the run as stopped.

    Steering applies whenever System 1 is holding, so how often that is depends on the policy. Only `stop` reaches a
    routine between stops."""
    steering = steering or Steering()
    if approve is auto_approve and not robot_may_auto_approve(robot := system1.system_status().robot):
        raise PermissionError(f"plans on {robot} must be approved by a person")
    log.emit("run_started", request)
    scene, fallback = explore(system1, log, policy, respond)
    log.emit("scene_ready", scene.model_copy(update={"controls": [c for c in scene.controls if c.id != DEVICE_CONTROL]}))
    plan = planner(request, scene, fallback)
    log.emit("plan_ready", plan)
    log.emit("approval_needed", {"kind": "plan", "ref": plan.plan_id})
    by = approve("plan", plan.plan_id)
    if by is None:
        raise PermissionError(f"plan {plan.plan_id} was not approved, so the arm did not move")
    log.emit("approved", {"kind": "plan", "ref": plan.plan_id, "by": by})

    queue, verdicts, seqs, status = deque(plan.steps), [], {}, "completed"
    if _steer_at_boundary(steering, queue, log, wait) == "stop":
        status = "stopped"
    elif queue:
        status = _test(system1, plan, queue, log, policy, respond, approve, steering, wait, verdicts, seqs)

    findings = findings_from(verdicts, seqs)
    for finding in findings:
        log.emit("finding", finding)
    cov = coverage(scene.controls, verdicts)
    score = reward(cov)
    report = Report(run_id=log.run_id, product=request.product, revision=request.revision, findings=findings,
                    coverage=cov, reward=score,
                    summary=(f"{len(cov.passed)} of {cov.detected} controls passed, {len(cov.failed)} failed, "
                             f"{len(cov.intermittent)} intermittent, {len(cov.inconclusive)} inconclusive, {len(cov.skipped)} skipped. "
                             f"Reward {score.value:.2f}."))
    log.emit("report_ready", report)
    log.write_report(report)
    log.emit("run_finished", {"status": status})
    return report


def _test(system1, plan, queue, log, policy, respond, approve, steering, wait, verdicts, seqs) -> str:
    """/test: hands the plan to System 1, and records and answers each stop until the routine ends."""
    by_id, amendments = {s.id: s for s in plan.steps}, 0
    to_run = Plan(plan_id=plan.plan_id, steps=list(queue), source=plan.source)
    handle = system1.routine_start("run_plan", to_run, policy)

    def stop_asked() -> bool:
        return any(c.kind == "stop" for c in steering.commands)

    while True:
        stop = wait_for_stop(system1, handle, stop_asked)
        log_crossing(log, handle, stop, policy)
        _record(system1, stop, by_id, queue, log, verdicts, seqs)
        if stop.status != "paused":
            return {"completed": "completed", "stopped": "stopped"}.get(stop.status, "aborted")
        decision = respond(stop)
        if stop.escalation and stop.escalation.measured.get("pattern") == "device_moved":  # the robot takes nothing else here, and this plan can't re-plan
            log.emit("message", {"role": "harness", "text": "the device moved, so the remaining steps would run on old poses. Stopping this plan"})
            system1.routine_resume(handle.routine_id, Decision(kind="abort", note="the device moved"))
            continue
        before = list(queue)
        if _steer_at_boundary(steering, queue, log, wait) == "stop":
            decision = Decision(kind="abort", note="stopped by an operator")
        elif list(queue) != before:  # a person steered, so it needs no further sign-off
            for s in queue:
                by_id.setdefault(s.id, s)
            decision = Decision(kind="amend", steps=list(queue), note="operator steering")
        elif decision.kind == "amend":
            amendments += 1
            decision = _amend(decision, plan, list(queue), approve, log, amendments)
            for s in decision.steps:
                by_id.setdefault(s.id, s)
            if decision.kind == "amend":
                queue.clear()
                queue.extend(decision.steps)
        elif decision.kind == "skip":
            kept = [s for s in queue if s.target not in decision.targets]
            queue.clear()
            queue.extend(kept)
        system1.routine_resume(handle.routine_id, decision)


def _record(system1, stop: Checkpoint, by_id, queue, log, verdicts, seqs) -> None:
    """Logs each finished step in full. The stop itself stays small, so the harness fetches the traces: this is
    bookkeeping for the record, and none of it goes to the model unless it asks."""
    for summary in stop.verdicts:
        verdict = summary.verdict
        step = by_id[verdict.step]
        if step in queue:
            queue.remove(step)
        log.emit("step_started", step)
        trace = system1.evidence_get(summary.trace_ref)
        event = log.emit("step_finished", StepOutcome(trace=trace, verdict=verdict))
        verdicts.append(verdict)
        seqs[id(verdict)] = event.seq


@dataclass
class AnalystContext:
    """What an analyst works from. One object, so adding the manual's line or frames later doesn't change the signature.

    `params` is cad.read_params(): every patchable parameter with its current value, keyed by the names the backend
    accepts (dotted paths for CadQuery). The analyst names a parameter from it and copies its value into from_value.
    `outcomes` is every step of the run, the failing one and the ones that passed, so similar controls can be compared
    when the run tested any. `check` is cad.check, to test a proposal before submitting it."""
    finding: Finding
    params: dict[str, Any]
    outcomes: list[StepOutcome]
    check: Callable[[CADPatch], list[str]]
    rules: str = ""
    tracer: Tracer | None = None


# A patch of None means no CAD change fixes this finding (perception, the arm, firmware); the root cause is still logged.
Analyst = Callable[[AnalystContext], tuple[RootCause, CADPatch | None]]


def _outcomes(log: RunLog) -> list[StepOutcome]:
    return [StepOutcome(**e.payload) for e in read_events(log.path) if e.type == "step_finished"]


def diagnose(findings: list[Finding], analyst: Analyst, cad: CadBackend, log: RunLog, outcomes: list[StepOutcome],
             parallel: bool = False) -> list[tuple[Finding, RootCause, CADPatch | None]]:
    """Each finding through the analyst, in finding order. With `parallel`, all at once: each finding has its own
    branch and its own tracer (ids prefixed with the finding), and the log is safe to write from several threads."""
    params, rules = cad.read_params(), getattr(cad, "rules", lambda: "")()

    def one(finding: Finding) -> tuple[Finding, RootCause, CADPatch | None]:
        tracer = Tracer(log, caller="model", prefix=f"{finding.id}-" if parallel and len(findings) > 1 else "")
        tracer.stage, tracer.step = "ANALYZE", finding.step_ids[0] if finding.step_ids else None
        return (finding, *analyst(AnalystContext(finding, params, outcomes, cad.check, rules, tracer)))

    if not parallel or len(findings) < 2:
        return [one(f) for f in findings]
    with ThreadPoolExecutor(max_workers=len(findings)) as pool:
        return list(pool.map(one, findings))


def fix_and_retest(make_system1: Callable[[str], System1], request: TestRequest, analyst: Analyst, cad: CadBackend,
                   log_root: str = "runs", planner: Planner = rule_planner, approve: Approver = auto_approve,
                   policy: EscalationPolicy = TETHERED, parallel: bool = False) -> tuple[Report, Report | None]:
    """Test, diagnose, patch, retest. A patch counts only if the reward rises; otherwise it is reported as rolled back."""
    rid = request.request_id
    before_log = RunLog(f"{rid}-rev{request.revision}", log_root)
    system1 = make_system1(request.revision)
    try:
        before = run_test(system1, request, before_log, planner, approve, policy=policy)
    finally:
        system1.close()
    if not before.findings:
        return before, None

    patches = []
    for finding, cause, patch in diagnose(before.findings, analyst, cad, before_log, _outcomes(before_log), parallel):
        before_log.emit("root_cause", cause)
        if patch is None:
            before_log.emit("message", {"role": "harness", "text": f"no CAD fix for {finding.id}: {cause.root_cause}"})
            continue
        before_log.emit("patch_proposed", patch)
        problems = cad.check(patch)
        if problems:
            before_log.emit("message", {"role": "harness", "text": f"patch for {finding.id} refused: {problems}"})
            continue
        patches.append(patch)
    if not patches:
        return before, None
    revision = patches[0].revision_to
    for patch in patches:
        by = approve("patch", patch.file)
        if by is None:
            return before, None
        before_log.emit("approved", {"kind": "patch", "ref": patch.file, "by": by})
        cad.apply(patch)
        before_log.emit("patch_applied", patch)

    retest = request.model_copy(update={"revision": revision})
    system1 = make_system1(revision)
    try:
        after = run_test(system1, retest, RunLog(f"{rid}-rev{revision}", log_root), planner, approve, policy=policy)
    finally:
        system1.close()
    verdict = "kept" if after.reward.value > before.reward.value else "rolled back: the reward did not rise"
    before_log.emit("message", {"role": "harness", "text": f"reward {before.reward.value:.2f} -> {after.reward.value:.2f}; patch {verdict}"})
    return before, after
