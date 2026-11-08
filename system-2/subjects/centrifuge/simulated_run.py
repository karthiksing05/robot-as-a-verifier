"""A simulated Rev A test run of the MC-6 centrifuge, written by the harness's own run_test.

    cd system-2 && .venv/bin/python subjects/centrifuge/simulated_run.py      # -> subjects/centrifuge/sim_run/

There is no arm on the centrifuge yet, so this stands in for System 1: a scripted robot runs the test plan and
reports what it measured. The harness then makes the verdicts into escalations and findings exactly as it would
for the arm. The analyst reads the result (`rav analyze`), so this file decides how realistic its inputs are.

What it may use, and what it may not:
- Physical behaviour comes from the assumptions below, fixed before any analyst run.
- Which steps misbehave, and how, comes only from what the robot would observe (the brief's evidence column):
  the Stop press sees a force spike and no btn_stop; no allowed skill opens the lid and the lid sensor never
  changes; the placed tube stays 8.5 mm high, the tube sensor stays dark, and Start then shows TUBE.
- Nothing about causes, the fault table or Rev B.
Verdicts come from one rule applied to every trace (verdict() below), not written per step.
"""
from __future__ import annotations

import pathlib

from rav_contracts import TestRequest
from rav_harness.loop import run_test
from rav_harness.mock import FakeSystem1
from rav_harness.runlog import RunLog
from rav_interface import Control, Plan, SceneInventory, Step, StepTrace, StepVerdict

HERE = pathlib.Path(__file__).resolve().parent

# --- assumptions, fixed before any run --------------------------------------------------------------------------
FORCE_LIMIT_N = 6.0          # the harness's press force cap
SWITCH_N, SWITCH_MM = 2.5, 0.25   # a 12 mm tactile switch clicks at about 2.5 N over its own 0.25 mm
TOGGLE_N, TOGGLE_MM = 3.0, 2.0
DIAL_RPM = (1000, 6000)      # the brief: 270 degrees = 1000-6000 rpm
HOOK_LIFT_MM = 6.0           # how far the hook tries to lift
PRESS_S, RAMP = 2.0, 5       # timing of a press, and samples in a force curve

# --- what the robot observes on Rev A (the brief's evidence column, in measured terms) ---------------------------
OBSERVED = {
    "stop": "bound",            # force climbs to the cap almost at once; btn_stop never fires
    "lid": "nothing_to_hook",   # flat push: lid presses into its frame; hook: slides past, lifts nothing; no lid event
    "well_A": "high",           # tube released, rests 8.5 mm above where it should; no tube event; Start shows TUBE
}
TUBE_HIGH_MM = 8.5

CONTROLS = [  # id, kind, product-frame position (mm), skill, expected serial event
    ("power", "toggle", (34.0, -45.0, 75.0), "flip", "power"),
    ("lid", "door", (15.0, 0.0, 104.0), "hook_pull", "lid"),
    ("well_A", "other", (-21.0, -13.0, 60.7), "slide", "tube"),
    ("start", "button", (45.7, -22.86, 79.7), "press", "btn_start"),
    ("stop", "button", (45.7, 0.0, 79.7), "press", "btn_stop"),
    ("time", "button", (45.7, 22.86, 79.7), "press", "btn_time"),
    ("dial", "dial", (50.8, 45.0, 83.1), "turn", "speed"),
]
NOTES = {"well_A": "pick tube_1 from the rack and lower it into well A; the operator opened the lid by hand"}


def ramp(peak: float, seconds: float = PRESS_S) -> list[tuple[float, float]]:
    return [(round(seconds * k / RAMP, 2), round(peak * k / RAMP, 2)) for k in range(RAMP + 1)]


def verdict(step: Step, trace: StepTrace, channel: str) -> StepVerdict:
    """System 1's rule for every step: the expected event fired, or say what the measurements show."""
    base = dict(step=step.id, target=step.target, channel=channel, evidence=[f"{step.id} force trace", f"{step.id} serial log"])
    if trace.readout_change.get(channel):
        return StepVerdict(**base, status="passed", reason=f"{step.target} drives {channel}")
    if trace.stop_reason == "force_limit":
        return StepVerdict(**base, status="failed", label="stuck",
                           reason=f"reached the {trace.peak_force_n:g} N limit after {trace.travel_mm:g} mm of travel; no {channel} event")
    if trace.stop_reason == "no_skill_fits":
        return StepVerdict(**base, status="failed", label="accessibility",
                           reason=f"no allowed skill moved it: a flat push reached {trace.peak_force_n:g} N with "
                                  f"{trace.travel_mm:g} mm of travel, and the hook lifted {HOOK_LIFT_MM:g} mm without "
                                  f"catching anything (pinching isn't allowed); no {channel} event")
    if trace.stop_reason == "rested_short":
        oled = (trace.readout_change.get("oled") or ["", ""])[-1]
        return StepVerdict(**base, status="failed", label="wrong_behavior",
                           reason=f"the tube rested {trace.travel_mm:g} mm above where it seats; no {channel} event; "
                                  f"Start then showed {oled}")
    return StepVerdict(**base, status="inconclusive", reason=f"stopped ({trace.stop_reason}) without {channel}")


class CentrifugeRobot:
    def __init__(self, revision: str = "A"):
        self.revision = revision

    def perceive(self) -> SceneInventory:
        return SceneInventory(frame="product", notes=["simulated: positions from the CAD"], controls=[
            Control(id=i, kind=k, pos_mm=p, normal=(0.7071, 0.0, 0.7071), source="cad") for i, k, p, _, _ in CONTROLS])

    def default_plan(self, scene: SceneInventory) -> Plan:
        return Plan(plan_id=f"centrifuge-rev{self.revision}", source="rules", steps=[
            Step(id=f"s{n + 1}", skill=skill, target=cid, params={"force_limit": FORCE_LIMIT_N, **({"note": NOTES[cid]} if cid in NOTES else {})},
                 expected=f"serial event {event}") for n, (cid, _, _, skill, event) in enumerate(CONTROLS)])

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        channel = next(e for cid, _, _, _, e in CONTROLS if cid == step.target)
        how = OBSERVED.get(step.target) if self.revision == "A" else None
        t = dict(step=step.id)
        if how == "bound":
            trace = StepTrace(**t, stop_reason="force_limit", duration_s=1.2, peak_force_n=FORCE_LIMIT_N, travel_mm=0.04,
                              force_trace=[(0.0, 0.0), (0.3, 2.1), (0.6, 4.4), (0.9, 5.6), (1.2, FORCE_LIMIT_N)])
        elif how == "nothing_to_hook":
            trace = StepTrace(**t, stop_reason="no_skill_fits", duration_s=6.0, peak_force_n=FORCE_LIMIT_N, travel_mm=0.5,
                              force_trace=ramp(FORCE_LIMIT_N, 2.0) + [(4.0, 0.0), (6.0, 0.1)])
        elif how == "high":
            trace = StepTrace(**t, stop_reason="rested_short", duration_s=5.5, peak_force_n=1.2, travel_mm=TUBE_HIGH_MM,
                              force_trace=[(0.0, 0.0), (4.0, 0.0), (4.5, 1.2), (5.5, 0.0)], readout_change={"oled": ["READY", "TUBE"]})
        elif step.target == "dial":
            trace = StepTrace(**t, stop_reason="target_travel", duration_s=3.0, peak_force_n=0.8, travel_mm=270.0,
                              readout_change={"speed": [DIAL_RPM[0], 3500, DIAL_RPM[1]]})
        elif step.target == "power":
            trace = StepTrace(**t, stop_reason="target_travel", duration_s=1.5, peak_force_n=TOGGLE_N, travel_mm=TOGGLE_MM,
                              force_trace=ramp(TOGGLE_N, 1.5), readout_change={"power": [0, 1]})
        elif step.target == "lid":
            trace = StepTrace(**t, stop_reason="target_travel", duration_s=4.0, peak_force_n=1.5, travel_mm=105.0,
                              readout_change={"lid": [0, 1]})
        elif step.target == "well_A":
            trace = StepTrace(**t, stop_reason="target_travel", duration_s=5.0, peak_force_n=0.4, travel_mm=0.0,
                              readout_change={"tube": [0, 1]})
        else:
            trace = StepTrace(**t, stop_reason="target_travel", duration_s=PRESS_S, peak_force_n=SWITCH_N, travel_mm=SWITCH_MM,
                              force_trace=ramp(SWITCH_N), readout_change={channel: [0, 1, 0]})
        return trace, verdict(step, trace, channel)

    def close(self) -> None:
        pass


def main(out: pathlib.Path = HERE / "sim_run") -> pathlib.Path:
    request = TestRequest(request_id="centrifuge", product="MC-6 mini centrifuge (simulated run)", revision="A")
    log = RunLog("centrifuge-revA", out)
    report = run_test(FakeSystem1(CentrifugeRobot("A")), request, log)
    print(f"{report.summary}\n" + "\n".join(f"  {f.id} [{f.label}] {f.target}: {f.what_happened}" for f in report.findings))
    print("wrote", log.path)
    return log.path


if __name__ == "__main__":
    main()
