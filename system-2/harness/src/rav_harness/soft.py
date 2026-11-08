"""A cheap first test of a model, with no sim: short made-up scenarios on a fake robot, scored by the same scorer as a real
run. Each checks one kind of judgment, and also that the provider's tool calls, images and reasoning reach the harness.

    rav soft --models claude-haiku-5-5,grok-4.7 --token-cap 1500000

The scenarios are invented, on purpose unlike any real product. They're for comparing models, so they aren't for tuning
prompts against, and their answers are only ever read here, after a run.
"""
from __future__ import annotations

import base64
import json
import pathlib
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rav_contracts import (ActionSpec, Check, CheckResult, Checkpoint, Control, Frame, ParamSpec, Plan, RoutineHandle, SceneInventory, Step, StepTrace, StepVerdict,
                           SystemStatus, TestRequest)

from .agent import AgentConfig, run_agent, sim_auto_approve
from .client import ToolFailed
from .eval import score
from .ledger import Budget, Ledger, LedgeredClient
from .loop import run_test
from .manual import Manual
from .mock import FakeSystem1, MockBackend
from .model import make_client
from .runlog import RunLog, read_events

DIGITS = {"0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110", "2": "01110 10001 00001 00010 00100 01000 11111",
          "3": "11110 00001 00001 01110 00001 00001 11110", "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
          "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000", "8": "01110 10001 10001 01110 10001 10001 01110",
          "9": "01110 10001 10001 01111 00001 00010 01100"}


def number_png(text: str, scale: int = 12, margin: int = 16) -> bytes:
    """Dark digits on a light panel, as a PNG, with nothing but the standard library."""
    width = (len(text) * 6 - 1) * scale + 2 * margin
    height = 7 * scale + 2 * margin
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            cx, cy = (x - margin) // scale, (y - margin) // scale
            on = False
            if 0 <= cy < 7 and 0 <= cx < len(text) * 6 and x >= margin:
                n, column = cx // 6, cx % 6
                if n < len(text) and column < 5:
                    on = DIGITS[text[n]].split()[cy][column] == "1"
            rows += bytes((30, 30, 40) if on else (225, 228, 220))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


def _evaluate(check: Check, readings: dict, trace: StepTrace) -> CheckResult:
    if check.metric.startswith("reading:"):
        actual = readings.get(check.metric.split(":", 1)[1])
    else:
        actual = getattr(trace, check.metric, None)
    passed = None
    if actual is not None:
        if check.op == "==":
            passed = str(actual) == str(check.value) or actual == check.value
        elif check.op == "changed":
            passed = True
        elif isinstance(actual, (int, float)) and isinstance(check.value, (int, float)):
            passed = actual <= check.value if check.op == "<=" else actual >= check.value
    return CheckResult(metric=check.metric, op=check.op, value=check.value, actual=actual, passed=passed)


class SoftRobot(MockBackend):
    """Each control's attempts come from a script. Rules in `effects` change readings, so one step can depend on another."""

    def __init__(self, controls: list[Control], script: dict[str, list[str]] | None = None, effects: Callable[[Step, dict], dict] | None = None, frames: list[str] | None = None,
                 readings: dict | None = None):
        self.controls, self.script, self.effects = controls, {k: list(v) for k, v in (script or {}).items()}, effects
        self.frames, self.readings, self.executed = frames or [], dict(readings or {}), []

    def perceive(self) -> SceneInventory:
        return SceneInventory(controls=self.controls, frames=self.frames)

    def default_plan(self, scene: SceneInventory) -> Plan:
        steps = [Step(id=f"r{n}", skill="observe" if c.kind == "display" else "press", target=c.id) for n, c in enumerate(scene.controls)]
        return Plan(plan_id="rules", steps=steps, source="rules")

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        self.executed.append(step)
        planned = self.script.get(step.target)
        status = planned.pop(0) if planned else ("observed" if step.skill == "observe" else "passed")
        unsafe = status == "unsafe"
        before = dict(self.readings)
        if status == "passed":
            self.readings[f"BTN_{step.target}"] = 1
            if self.effects:
                self.readings.update(self.effects(step, self.readings) or {})
        changed = {k: [before.get(k), v] for k, v in self.readings.items() if before.get(k) != v}
        label = {"failed": "stuck", "inconclusive": "inconclusive"}.get(status)
        verdict = StepVerdict(step=step.id, target=step.target, status="inconclusive" if unsafe else status, label="unsafe" if unsafe else label,
                              reason={"passed": f"{step.target} changed a reading", "failed": f"pressed {step.target} to the force limit, 6.0 N, with 0.2 mm of travel, and no reading changed",
                                      "inconclusive": f"the pad never touched {step.target}: it landed 5 mm off", "unsafe": "safety stop: force over the cap", "observed": "read the display"}.get(status, status))
        peak, travel, offset = {"failed": (6.0, 0.2, 0.3), "inconclusive": (0.1, 0.0, 5.2), "unsafe": (15.2, 0.0, 0.2)}.get(status, (2.8, 2.5, 0.3))
        trace = StepTrace(step=step.id, stop_reason={"failed": "force_limit", "inconclusive": "landed"}.get(status, "travel"), peak_force_n=peak, travel_mm=travel, duration_s=2.0,
                          readout_change=changed, force_trace=[(0.0, 0.0), (1.0, peak)], measures={"contact_offset_mm": offset, "readings": dict(self.readings)})
        trace.checks = [_evaluate(c, self.readings, trace) for c in step.check]
        return trace, verdict


class SoftSystem1(FakeSystem1):
    """The tools, for the fake robot: published actions, images, home, checks on stops, and a refusal to order."""

    ACTIONS = [ActionSpec(skill="press", kinds=["button"], params=[ParamSpec(name="force_limit", min=0.1, max=14.0, default=6.0, unit="N")], about="Push a button along its normal."),
               ActionSpec(skill="observe", kinds=["display"], about="Read a display: no motion.")]

    def __init__(self, robot: SoftRobot, images: dict[str, Frame] | None = None, refuse_first: str | None = None):
        super().__init__(robot)
        self.images, self.refuse_first = images or {}, refuse_first

    def system_status(self) -> SystemStatus:
        return SystemStatus(state="idle", robot="fake", skills=[a.skill for a in self.ACTIONS], actions=self.ACTIONS, max_force_n=14.0)

    def evidence_frame(self, ref: str) -> Frame:
        if ref not in self.images:
            raise ToolFailed(f"no evidence called {ref}")
        return self.images[ref]

    def evidence_get(self, ref: str) -> StepTrace:
        if ref not in self.traces:
            raise ToolFailed(f"no evidence called {ref}")
        return self.traces[ref]

    def routine_start(self, routine, plan=None, policy=None) -> RoutineHandle:
        if routine == "run_plan" and self.refuse_first:
            why, self.refuse_first = self.refuse_first, None
            raise ToolFailed(f"routine_start: {why}")
        if routine == "home":
            self.routines += 1
            def go():
                yield Checkpoint(routine_id=f"r{self.routines}", stop="done", status="completed")
            self.routine = go()
            self.next = next(self.routine)
            return RoutineHandle(routine_id=f"r{self.routines}", routine="home")
        return super().routine_start(routine, plan, policy)

    def _run_plan(self, plan, policy):
        inner = super()._run_plan(plan, policy)
        stop = next(inner)
        while True:
            for s in stop.verdicts:
                trace = self.traces[s.trace_ref]
                s.checks, s.measures = trace.checks, {k: v for k, v in trace.measures.items() if k != "readings"}
            decision = yield stop
            try:
                stop = inner.send(decision)
            except StopIteration:
                return


def _button(i: str, n: int, label: str | None = None) -> Control:
    return Control(id=i, kind="button", pos_mm=(250.0, -40.0 + 30.0 * n, 60.0), normal=(-0.7, 0.0, 0.7), size_mm=(12.0, 12.0, 3.0), motion="translation", label=label, source="mock")


def _key(controls: list[Control], faults: list[str] = ()) -> dict:
    return {"controls": [{"id": c.id, "kind": c.kind, "pos_mm": list(c.pos_mm)} for c in controls], "faults": [{"part": f} for f in faults], "errors": []}


@dataclass
class Scenario:
    name: str
    teaches: str
    build: Callable[[], tuple[SoftSystem1, dict]]
    instruction: str = "Try every feature a first-time user would try, and report what's wrong."
    manual: str | None = None
    checks: Callable[[dict, list, Any], dict[str, bool]] = lambda s, events, report: {}


def _common(s: dict) -> dict[str, bool]:
    return {"finished": s["finished"] == "completed" and s["report_written"], "no_false_findings": not s.get("false_findings"), "found_every_fault": not s.get("faults_missed")}


PROCEDURE = """Model K-2 bench unit. Short guide.
Page 1. Controls: MAIN, GO and TONE, three buttons, labelled on the panel.
Operating: Press MAIN once to switch on. The reading MAINS goes to 1. GO only works once the unit is on.
With the unit on, press GO: the reading RUN goes to 1. If MAINS is 0, GO does nothing, and that is correct.
TONE sounds a beep. The reading BEEP goes to 1."""


def _procedure(broken: bool) -> Callable[[], tuple[SoftSystem1, dict]]:
    def build() -> tuple[SoftSystem1, dict]:
        controls = [_button("p1", 0, "GO"), _button("p2", 1, "TONE"), _button("p3", 2, "MAIN")]

        def effects(step: Step, r: dict) -> dict:
            if step.target == "p3":
                return {"MAINS": 1}
            if step.target == "p2":
                return {"BEEP": 1}
            if step.target == "p1" and r.get("MAINS") == 1 and not broken:
                return {"RUN": 1}
            return {}
        key = _key(controls, ["p1"] if broken else [])
        return SoftSystem1(SoftRobot(controls, effects=effects, readings={"MAINS": 0, "RUN": 0, "BEEP": 0})), key
    return build


def _simple(script: dict[str, list[str]], faults: list[str] = (), refuse: str | None = None, n: int = 4) -> Callable[[], tuple[SoftSystem1, dict]]:
    def build() -> tuple[SoftSystem1, dict]:
        controls = [_button(f"x{i}", i) for i in range(1, n + 1)]
        return SoftSystem1(SoftRobot(controls, script), refuse_first=refuse), _key(controls, list(faults))
    return build


def _image() -> tuple[SoftSystem1, dict]:
    controls = [_button("v1", 0), Control(id="v2", kind="display", pos_mm=(250.0, 40.0, 90.0), normal=(-1.0, 0.0, 0.0), source="mock")]
    frame = Frame(ref="frame:1", mime="image/png", data_b64=base64.b64encode(number_png("4729")).decode(), width=0, height=0, caption="a view of the display")
    return SoftSystem1(SoftRobot(controls, frames=["frame:1"]), {"frame:1": frame}), _key(controls)


def _attempts(events: list, target: str) -> list[str]:
    return [e.payload["verdict"]["status"] for e in events if e.type == "step_finished" and e.payload["verdict"]["target"] == target]


SCENARIOS = [
    Scenario("plan_from_manual", "a plan from a scene and a manual, where one step depends on another", _procedure(False), manual=PROCEDURE,
             checks=lambda s, events, report: {**_common(s), "did_the_whole_procedure": any(
                 e.type == "step_finished" and e.payload["trace"].get("measures", {}).get("readings", {}).get("RUN") == 1 for e in events)}),
    Scenario("procedure_fault", "a real fault in a procedure: only a finding once what it depends on was truly there", _procedure(True), manual=PROCEDURE,
             checks=lambda s, events, report: {**_common(s), "named_the_right_control": "p1" in [f.target for f in report.findings]}),
    Scenario("fault_vs_robot_error", "a real fault against a robot's miss", _simple({"x2": ["failed"] * 6, "x3": ["inconclusive"]}, ["x2"]),
             checks=lambda s, events, report: {**_common(s), "retested_the_fault": len(_attempts(events, "x2")) >= 2, "retested_the_miss": _attempts(events, "x3")[-1:] == ["passed"],
                                               "called_the_miss_healthy": "x3" not in [f.target for f in report.findings]}),
    Scenario("false_alarm", "one failure that doesn't repeat", _simple({"x1": ["failed"]}),
             checks=lambda s, events, report: {**_common(s), "retested": len(_attempts(events, "x1")) >= 2, "not_called_broken": "x1" not in report.coverage.failed}),
    Scenario("bad_request", "the robot refusing a request, with the reason", _simple({}, refuse="plan rejected: force_limit may not be given as a default here. Send the steps again with force_limit set to 5 on each. Nothing moved"),
             checks=lambda s, events, report: {**_common(s), "recovered": s["covered"] == s["detected"]}),
    Scenario("safety_abort", "a safety stop on a healthy product", _simple({"x2": ["unsafe"]}),
             checks=lambda s, events, report: {**_common(s), "recovered": any(e.type == "tool_call" and e.payload["tool"] == "recover" and e.payload["ok"] for e in events),
                                               "tested_the_rest": s["covered"] == s["detected"]}),
    Scenario("image_read", "reading a number off an image", _image, instruction="Test the product, and say in your final summary what number the display shows in the survey image.",
             checks=lambda s, events, report: {**_common(s), "read_the_number": any(e.type == "message" and e.payload.get("role") == "model" and "4729" in (e.payload.get("text") or "") for e in events)}),
]


def run_scenario(scenario: Scenario, model: str, folder: pathlib.Path, ledger: Ledger, config: AgentConfig | None = None, make=make_client) -> dict[str, Any]:
    system1, key = scenario.build()
    run_id = f"{model.replace(':', '-')}-{scenario.name}"
    log = RunLog(run_id, folder)
    request = TestRequest(request_id=run_id, product="A bench product", instruction=scenario.instruction)
    record: dict[str, Any] = {"model": model, "scenario": scenario.name}
    started = time.monotonic()
    try:
        if model == "rules":
            report = run_test(system1, request, log)
        else:
            manual = None
            if scenario.manual:  # in the run's folder: Windows can't reopen a temp file that is still open
                (log.dir / "manual.txt").write_text(scenario.manual)
                manual = Manual(log.dir / "manual.txt")
            client = LedgeredClient(make(model), ledger, run_id)
            report = run_agent(system1, request, log, client, approve=sim_auto_approve, config=config or AgentConfig(max_turns=30, max_tokens=120_000), manual=manual)
        events = read_events(log.path)
        s = score(report, events, key)
        checks = scenario.checks(s, events, report)
        turns = [e.payload for e in events if e.type == "model_turn"]
        record.update(score=round(sum(checks.values()) / len(checks), 3), checks=checks, findings=[f"{f.target}:{f.label}" for f in report.findings], turns=s["turns"], tokens=s["tokens"],
                      tool_errors=s["tool_errors"], thinking_chars=sum(len(t.get("thinking") or "") for t in turns), text_chars=sum(len(t.get("text") or "") for t in turns),
                      latency_s=[round((t.get("latency_ms") or 0) / 1000, 2) for t in turns], fell_back=s["model_gave_up"])
    except Exception as e:  # noqa: BLE001 - a provider that breaks is a result
        record.update(score=0.0, crashed=f"{type(e).__name__}: {e}"[:400])
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


def run_round_one(models: list[str], out: str | pathlib.Path = "runs", budget: Budget | None = None, scenarios: list[Scenario] | None = None, make=make_client, ledger: Ledger | None = None,
                  config: AgentConfig | None = None) -> dict:
    folder = pathlib.Path(out).resolve() / time.strftime("soft-%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    ledger = ledger or (budget.ledger if budget else Ledger())
    results: list[dict] = []
    stopped = None
    for model in models:
        for scenario in scenarios or SCENARIOS:
            if budget and (why := budget.refuse(model)):
                stopped = f"{model}/{scenario.name}: {why}"
                break
            results.append(run_scenario(scenario, model, folder, ledger, config=config, make=make))
            (folder / "results.json").write_text(json.dumps({"results": results, "stopped": stopped}, indent=2) + "\n")
        if stopped:
            break
    table = summary(results)
    (folder / "results.json").write_text(json.dumps({"results": results, "summary": table, "stopped": stopped}, indent=2) + "\n")
    return {"folder": str(folder), "results": results, "summary": table, "stopped": stopped}


def summary(results: list[dict]) -> list[dict]:
    rows = []
    for model in dict.fromkeys(r["model"] for r in results):
        mine = [r for r in results if r["model"] == model]
        latencies = sorted(x for r in mine for x in r.get("latency_s", []))
        rows.append({"model": model, "score": round(sum(r["score"] for r in mine) / len(mine), 3), "scenarios": len(mine), "tokens": sum(r.get("tokens", 0) for r in mine),
                     "turns": sum(r.get("turns", 0) for r in mine), "tool_errors": sum(r.get("tool_errors", 0) for r in mine), "crashes": sum("crashed" in r for r in mine),
                     "fell_back": sum(bool(r.get("fell_back")) for r in mine), "reasoning_chars": sum(r.get("thinking_chars", 0) for r in mine), "text_chars": sum(r.get("text_chars", 0) for r in mine),
                     "median_turn_s": latencies[len(latencies) // 2] if latencies else None, "seconds": round(sum(r.get("seconds", 0) for r in mine), 1),
                     "missed": sorted({f"{r['scenario']}.{k}" for r in mine for k, v in (r.get("checks") or {}).items() if not v})})
    return sorted(rows, key=lambda r: -r["score"])


def format_table(rows: list[dict]) -> str:
    lines = [f"{'model':<36}{'score':>6}{'tokens':>9}{'turns':>6}{'tool err':>9}{'crash':>6}{'med s':>7}"]
    for r in rows:
        lines.append(f"{r['model']:<36}{r['score']:>6.2f}{r['tokens']:>9}{r['turns']:>6}{r['tool_errors']:>9}{r['crashes']:>6}{(r['median_turn_s'] or 0):>7.1f}")
    return "\n".join(lines)


__all__ = ["SCENARIOS", "run_round_one", "format_table", "summary"]
