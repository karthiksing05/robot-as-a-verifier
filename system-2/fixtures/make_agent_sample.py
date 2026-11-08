"""Write fixtures/sample_run/sample-agent: a scripted model run, so the Console's agent view works with no model and no sim.

It is NOT real model output. The model's words and all the numbers here were written by hand, to show every kind of entry
the view has to draw: a rejected plan, a robot error and its retry, an operator's message, a real fault, a false alarm
and a level 3 approval. Replace it with a real recording once one exists.

    uv run python fixtures/make_agent_sample.py
"""
import json
import pathlib

RUN = "sample-agent"
MODEL = "scripted (not a real model)"
OUT = pathlib.Path(__file__).parent / "sample_run" / RUN
events: list[dict] = []
clock = [0.0]
turns = [0]
calls = [0]


def emit(kind: str, payload: dict, after: float = 0.4) -> None:
    clock[0] = round(clock[0] + after, 3)
    events.append({"seq": len(events) + 1, "t": clock[0], "run_id": RUN, "type": kind, "payload": payload})


def state(name: str, detail: str = "") -> None:
    emit("agent_state", {"state": name, "detail": detail}, 0.1)


def turn(thinking: str, text: str = "", step: str | None = None, in_tokens: int = 2400, out: int = 180) -> str:
    state("thinking")
    turns[0] += 1
    tid = f"turn-{turns[0]}"
    emit("model_turn", {"id": tid, "model": MODEL, "stage": None, "step": step, "input": None, "thinking": thinking or None, "text": text or None, "stop_reason": "tool_use",
                        "tokens_in": in_tokens, "tokens_out": out, "latency_ms": 2600.0, "claims": {}, "error": None, "error_kind": None, "layer": None, "raw": None}, 1.6)
    return tid


def tool(name: str, args: dict, tid: str | None, result: dict | None = None, error: str | None = None, kind: str | None = None, ms: float = 40.0, step: str | None = None) -> None:
    calls[0] += 1
    emit("tool_call", {"id": f"call-{calls[0]}", "tool": name, "args": args, "caller": "model" if tid else "rules", "turn": tid, "stage": None, "step": step, "ok": error is None, "result": result,
                       "error": error, "error_kind": kind, "layer": "model" if kind in ("bad_args", "unknown_target") else None, "duration_ms": ms}, 0.2)


def step(sid: str, skill: str, target: str, params: dict | None = None, **kw) -> dict:
    return {"id": sid, "skill": skill, "target": target, "params": params or {}, "quote": kw.get("quote"), "expected": kw.get("expected"), "check": [], "why": None}


def ramp(peak: float, n: int = 40, hold: int = 0) -> list[list[float]]:
    rise = [[round(i * 0.05, 3), round(peak * min(1, i / (n * 0.6)), 2)] for i in range(n)]
    return rise + [[round((n + i) * 0.05, 3), peak] for i in range(hold)]


def result(s: dict, status: str, reason: str, *, attempt: int = 1, label: str | None = None, peak: float | None = None, travel: float | None = None, stop: str | None = None, readings: dict | None = None,
           measures: dict | None = None, channel: str | None = None, hold: int = 0) -> None:
    state("arm", f"{s['skill']} {s['target']}")
    emit("step_started", s, 0.4)
    trace = {"step": s["id"], "attempt": attempt, "stop_reason": stop, "duration_s": 3.2, "peak_force_n": peak, "travel_mm": travel, "force_trace": ramp(peak, hold=hold) if peak else [],
             "readout_change": readings or {}, "measures": measures or {}, "checks": [], "frames": []}
    emit("step_finished", {"trace": trace, "verdict": {"step": s["id"], "target": s["target"], "attempt": attempt, "status": status, "label": label, "reason": reason, "channel": channel, "decided_by": "rule", "evidence": []}}, 1.2)


def crossing(routine: str, stop: str, code: str | None = None, sid: str | None = None, target: str | None = None) -> None:
    emit("crossing", {"routine": routine, "stop": stop, "code": code, "step": sid, "target": target, "policy": "tethered", "verdicts": 1, "retries_resolved": 0}, 0.1)


def control(cid: str, kind: str, y: float, **extra) -> dict:
    return {"id": cid, "kind": kind, "pos_mm": [250.0, y, 60.0], "normal": [0.0, 0.0, 1.0], "size_mm": None, "motion": "", "grip": "tip", "label": None, "conf": 0.93, "source": "scan", **extra}


CONTROLS = [control("button_1", "button", -40), control("button_2", "button", -20), control("slider_1", "slider", 0, position=0.0, travel_mm=40.0),
            control("dial_1", "dial", 20, turn_range_deg=[-150.0, 150.0], detent_deg=30.0), control("toggle_1", "toggle", 40, on=True), control("door_1", "door", 60, latched=True), control("display_1", "display", 80)]

emit("run_started", {"request_id": RUN, "product": "Scripted model run (mock)", "revision": "A", "project": None, "instruction": "Verify every control on this device.", "manual": None, "spec": {}}, 0.0)
t = turn("I know nothing about this device yet. Before I can plan anything I need to know what's on it, so the first thing is to have System 1 look at it.", "Starting with a look at the device.")
state("arm", "explore")
tool("look_at_device", {}, t, {"stop": "done", "controls": 7}, ms=41000.0)
crossing("explore", "done")
emit("scene_ready", {"frame": "arm_base", "controls": CONTROLS, "unmatched_manual_controls": [], "notes": [], "frames": []})

t = turn("Seven controls. Before writing steps I need to know which skill each kind takes and what its limits are, because a guess would just get refused.")
tool("get_status", {}, t, {"state": "idle", "skills": ["press", "slide", "turn", "flip", "push_latch", "observe"], "max_force_n": 14.0})
tool("get_scene", {}, t, {"controls": 7})

STEPS = [step("s1", "press", "button_1"), step("s2", "press", "button_2"), step("s3", "slide", "slider_1", {"to": 1.0}), step("s4", "turn", "dial_1", {"angle": 60}), step("s5", "flip", "toggle_1"), step("s6", "push_latch", "door_1"), step("s7", "observe", "display_1")]
t = turn("One step per control first, simplest to riskiest, and leave the door for late because opening it could change what else is reachable.")
bad = [*STEPS[:2], step("s3", "press", "slider_1"), *STEPS[3:]]
tool("propose_plan", {"steps": [f"{s['id']} {s['skill']} {s['target']}" for s in bad]}, t, error="s3 (press slider_1): press can't act on a slider. It takes: slide", kind="bad_args")
t = turn("I used the wrong skill on the slider. The status listed slide for it, and it needs a position, so I'll send it to the far end.")
tool("propose_plan", {"steps": [f"{s['id']} {s['skill']} {s['target']}" for s in STEPS]}, t, {"plan_id": "plan-1", "steps": 7})
emit("plan_ready", {"plan_id": "plan-1", "steps": STEPS, "source": "mock"})
emit("approval_needed", {"kind": "plan", "ref": "plan-1"})
state("waiting_person")
emit("approved", {"kind": "plan", "ref": "plan-1", "by": "Karthik"}, 2.4)

t = turn("", "Running the plan.")  # some models return no reasoning
tool("run_plan", {"plan_id": "plan-1"}, t, {"routine_id": "r2"})
result(STEPS[0], "passed", "button_1 drives BTN1 (0 -> 1 -> 0)", peak=2.9, travel=2.6, stop="travel", readings={"BTN1": [0, 1, 0]}, measures={"contact_offset_mm": 0.4, "refined": True, "refine_shift_mm": 0.8}, channel="BTN1")
crossing("run_plan", "checkpoint")
result(STEPS[1], "inconclusive", "the pad slipped off the part without pushing it", label="inconclusive", peak=0.2, travel=0.2, stop="landed", measures={"contact_offset_mm": 6.4, "refined": True, "refine_shift_mm": 0.6})
crossing("run_plan", "escalation", "retries_exhausted", "s2", "button_2")

t = turn("Inconclusive says nothing about the button. The force stayed near zero, so it probably never touched it. I'd like the contact offset before deciding, because that would separate a bad aim from something else.", step="s2")
tool("get_evidence", {"ref": "trace:r2:s2:1"}, t, {"peak_force_n": 0.2, "travel_mm": 0.2, "contact_offset_mm": 6.4}, step="s2")
t = turn("The contact was 6.4 mm off. That's the arm missing, not the device failing, so the fair thing is to try the same step again.", "Retrying button_2. The robot missed it.", step="s2")
tool("answer_stop", {"kind": "amend", "retry": "s2"}, t, {"level": 0})
emit("plan_amended", {"level": 0, "by": None, "steps": ["s2", "s3", "s4", "s5", "s6", "s7"], "why": "Retry s2: the pad landed 6.4 mm off button_2"})
result(STEPS[1], "passed", "button_2 drives BTN2 (0 -> 1 -> 0)", attempt=2, peak=2.8, travel=2.5, stop="travel", readings={"BTN2": [0, 1, 0]}, measures={"contact_offset_mm": 0.7, "refined": True, "refine_shift_mm": 1.1}, channel="BTN2")
crossing("run_plan", "checkpoint")

emit("message", {"role": "user", "text": "Test the dial before the slider, please. I'm most worried about it.", "by": "Karthik"}, 1.0)
t = turn("The operator wants the dial first. That changes the order only, so it's cheap to do.", "Moving the dial ahead of the slider.")
tool("answer_stop", {"kind": "amend", "order": ["s4", "s3", "s5", "s6", "s7"]}, t, {"level": 1})
emit("plan_amended", {"level": 1, "by": None, "steps": ["s4", "s3", "s5", "s6", "s7"], "why": "Operator asked for the dial first"})

STUCK = dict(label="stuck", peak=5.0, travel=0.3, stop="force_limit", hold=30, measures={"contact_offset_mm": 0.5, "refined": True, "regrip_mm": 5.0, "turned_deg": 0.4})
result(STEPS[3], "failed", "held at the 5.0 N limit after 0.3 mm, and no reading changed", **STUCK)
crossing("run_plan", "escalation", "step_failed", "s4", "dial_1")
t = turn("A real push this time: 5 N held, the contact was on target, and the regrip already tried further along the fin. That looks like the dial. One failure isn't enough to call it, since the arm can misbehave, so I'll repeat it once.", "Retesting dial_1 before calling this a fault.", step="s4")
tool("answer_stop", {"kind": "amend", "retry": "s4"}, t, {"level": 0})
emit("plan_amended", {"level": 0, "by": None, "steps": ["s4", "s3", "s5", "s6", "s7"], "why": "Retest s4 before reporting a failure"})
result(STEPS[3], "failed", "held at the 5.0 N limit after 0.2 mm, and no reading changed", attempt=2, **STUCK)
crossing("run_plan", "escalation", "step_failed", "s4", "dial_1")
emit("finding", {"id": "F1", "severity": "high", "target": "dial_1", "label": "stuck", "what_happened": "Failed twice in a row: held at 5.0 N with about 0.3 mm of travel and no reading change.", "manual_says": None, "user_impact": None, "step_ids": ["s4"], "event_seqs": [len(events)], "evidence": [], "confirmed": True})
t = turn("Same result twice with the same numbers, so this one stands. The rest of the plan doesn't depend on the dial, so I'll carry on.", "dial_1 is stuck. Carrying on.")
tool("answer_stop", {"kind": "amend", "order": ["s3", "s5", "s6", "s7"]}, t, {"level": 1})
emit("plan_amended", {"level": 1, "by": None, "steps": ["s3", "s5", "s6", "s7"], "why": "Done with s4, on to the rest"})

result(STEPS[2], "passed", "pushing slider_1 toward +x raises FAN (0.0 -> 1.0)", peak=2.1, travel=39.2, stop="travel", readings={"FAN": [0.0, 1.0]}, measures={"contact_offset_mm": 0.6, "landing_n": 1.2}, channel="FAN")
crossing("run_plan", "checkpoint")
result(STEPS[4], "failed", "pushed it through its motion but no reading changed", label="no_actuation", peak=2.4, travel=9.0, stop="travel", measures={"contact_offset_mm": 0.3, "landing_n": 1.0})
crossing("run_plan", "escalation", "step_failed", "s5", "toggle_1")
t = turn("The lever moved its full travel at a normal force, and yet the reading didn't change. That could be the switch, or the reading itself. A repeat would separate those.", "Retesting toggle_1.", step="s5")
tool("answer_stop", {"kind": "amend", "retry": "s5"}, t, {"level": 0})
emit("plan_amended", {"level": 0, "by": None, "steps": ["s5", "s6", "s7"], "why": "Retest s5: normal force and full travel, no reading"})
result(STEPS[4], "passed", "toggle_1 switches POWER (1 -> 0)", attempt=2, peak=2.3, travel=9.1, stop="travel", readings={"POWER": [1, 0]}, measures={"contact_offset_mm": 0.4, "landing_n": 1.1}, channel="POWER")
crossing("run_plan", "checkpoint")
emit("finding", {"id": "F2", "severity": "medium", "target": "toggle_1", "label": "intermittent", "what_happened": "Failed and also passed (failed, passed). First failure: pushed it through its motion but no reading changed", "manual_says": None, "user_impact": None, "step_ids": ["s5"], "event_seqs": [len(events)], "evidence": [], "confirmed": True})

result(STEPS[5], "inconclusive", "safety stop: force over the hard cap", label="unsafe", peak=15.2, travel=0.1, stop="safety")
crossing("run_plan", "safety_abort", None, "s6", "door_1")
t = turn("A safety stop at 15 N with almost no travel. The approach force was normal until one spike, which could be a sensor glitch or the arm, but it isn't mine to wave through. Going home and asking a person is the right order.", "The arm stopped itself on door_1. I'm asking to resume.", step="s6")
emit("approval_needed", {"kind": "plan", "ref": "resume-after-abort"})
state("waiting_person")
emit("approved", {"kind": "plan", "ref": "resume-after-abort", "by": "Karthik"}, 2.2)
tool("recover", {"how": "home"}, t, {"stop": "done"}, ms=3100.0)
t = turn("")
tool("run_plan", {"plan_id": "plan-1", "steps": ["s6", "s7"]}, t, {"routine_id": "r4"})
result(STEPS[5], "passed", "door_1 opened (DOOR 0 -> 1)", attempt=2, peak=4.4, travel=3.1, stop="travel", readings={"DOOR": [0, 1]}, measures={"contact_offset_mm": 0.5, "refined": True}, channel="DOOR")
crossing("run_plan", "checkpoint")
result(STEPS[6], "observed", "display shows FAN 100% DOOR OPEN", readings={"LCD": ["READY", "FAN 100%  DOOR OPEN"]}, channel="LCD")
crossing("run_plan", "done")

t = turn("Every control now has a result. dial_1 is a real fault, toggle_1 needs a closer look, and the two robot errors were retried and don't count against the device.", "Finishing with one stuck control and one intermittent one.")
tool("finish_run", {"claims": {"dial_1": "failed", "toggle_1": "intermittent"}}, t, {"ok": True})

COVERAGE = {"detected": 7, "passed": ["button_1", "button_2", "slider_1", "door_1"], "failed": ["dial_1"], "intermittent": ["toggle_1"], "observed": ["display_1"], "inconclusive": [], "skipped": {}}
covered, judged = 7, 6
REWARD = {"value": round(covered / 7 * (4 / judged), 4), "control_coverage": 1.0, "pass_rate": round(4 / judged, 4), "formula": "R = control coverage x pass rate"}
SUMMARY = "4 of 7 controls passed, 1 failed, 1 intermittent, 1 observed. Scripted, not a real run."
findings = [e["payload"] for e in events if e["type"] == "finding"]
REPORT = {"run_id": RUN, "product": "Scripted model run (mock)", "revision": "A", "summary": SUMMARY, "findings": findings, "coverage": COVERAGE, "reward": REWARD}
emit("report_ready", REPORT)
emit("run_finished", {"status": "completed"})
state("done")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
(OUT / "report.json").write_text(json.dumps(REPORT, indent=2) + "\n")
print(f"{OUT}: {len(events)} events")
