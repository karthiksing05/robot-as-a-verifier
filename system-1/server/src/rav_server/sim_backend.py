"""System 1's pipeline (pipeline.py) behind the server's Robot interface. PipelineRobot runs it on any rig (rig.Rig:
an arm and its cameras), and SimBackend builds the sim's. The stages are the ones explore.py films, in the same order:
  perceive   pipeline.scan_device, then pipeline.touch_plane and touch_parts (the RGB route)
  plan       affordances.plan_tests
  execute    affordances.run_step, with pipeline.last_look

The two mapping functions at the top need no simulator, so they are tested without MuJoCo.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

from rav_interface import Control, Plan, SceneInventory, Step, StepTrace, StepVerdict

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[3]
CORE_DIR, SIM_DIR, HARDWARE_DIR = SYSTEM_1 / "core", SYSTEM_1 / "sim", SYSTEM_1 / "hardware"


def on_path(*dirs):
    """Put System 1's folders of flat modules on the path (see system-1/sim/docs/code-map.md)."""
    for d in dirs:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))


def part_to_control(part: Any) -> Control:
    """features.Part (metres) to Control (millimetres)."""
    return Control(id=part.id, kind=part.kind, pos_mm=tuple(float(v) * 1000 for v in part.pos),
                   normal=tuple(float(v) for v in part.normal), size_mm=tuple(float(v) * 1000 for v in part.size),
                   motion=part.motion, grip=part.grip, conf=float(part.score), source="scan")


def map_verdict(step: Step, r: dict) -> tuple[StepTrace, StepVerdict]:
    """affordances.run_step's result dict to contracts. docs/decisions.md D9 has the vocabulary mapping."""
    raw, reason = r.get("verdict", "MISSED"), r.get("reason", "")
    label, decided_by = None, "rule"
    if raw == "PASS":
        status = "passed"
    elif raw == "FAIL":
        status = "failed"
        if "opposite" in reason or "back past" in reason:
            label = "wrong_behavior"
        elif r.get("stop") in ("force_limit", "max_lead", "side_force") or "blocked" in reason:
            label = "stuck"
        else:
            label = "no_actuation"
    elif raw == "REFUSED":
        status = "skipped"
        label = "accessibility" if "pinch" in reason else None
    elif raw == "ABORTED":
        status, label, decided_by = "inconclusive", "unsafe", "safety"
    else:  # MISSED: the robot couldn't carry out the test, which says nothing about the device
        status, label = "inconclusive", "inconclusive"
    trace = StepTrace(step=step.id, stop_reason=r.get("stop"), duration_s=r.get("duration_s"),
                      peak_force_n=r.get("peak_force_n"), travel_mm=r.get("travel_mm"),
                      force_trace=[(float(t), float(n)) for t, n in (r.get("force_trace") or [])],
                      readout_change={k: list(v) for k, v in (r.get("readout_change") or {}).items()})
    verdict = StepVerdict(step=step.id, target=step.target, status=status, label=label, reason=reason,
                          channel=r.get("channel"), decided_by=decided_by)
    return trace, verdict


class PipelineRobot:
    """The pipeline as a Robot, on any rig. A backend builds its rig and passes it in, as SimBackend does the sim's."""

    def __init__(self, rig, depth: bool = False, refine: bool = True, plan_id: str = "rules"):
        on_path(CORE_DIR)
        self.rig, self.arm, self.depth, self.use_refine, self.plan_id = rig, rig.arm, depth, refine, plan_id
        self.scene, self.parts, self.plane_T, self.known, self.refine = None, [], None, {}, None
        self.at_home = False

    def perceive(self) -> SceneInventory:
        import pipeline

        self.scene = pipeline.scan_device(self.arm, self.rig.phone, self.rig.wrist, self.depth)
        self.parts, notes = self.scene.parts, []
        if not self.depth:  # as in explore.py: a touch that fails goes on with what the scan found, and says so
            self.plane_T, _, e = pipeline.touch_plane(self.arm, self.scene)
            if e:
                notes.append(f"touch-offs failed, using the scan's plane: {type(e).__name__}: {e}")
            self.parts, e = pipeline.touch_parts(self.arm, self.scene, self.plane_T)
            if e:
                notes.append(f"part touches failed, using the scan's heights: {type(e).__name__}: {e}")
        if self.use_refine:
            self.refine = pipeline.last_look(self.rig.wrist, self.plane_T, self.depth)
        return SceneInventory(controls=[part_to_control(p) for p in self.parts], notes=notes)

    def default_plan(self, scene: SceneInventory) -> Plan:
        import affordances

        steps = [Step(id=f"s{n + 1}", skill=s["skill"], target=s["target"],
                      params=s.get("params", {}), why=s.get("why"))
                 for n, s in enumerate(affordances.plan_tests(self.parts))]
        return Plan(plan_id=self.plan_id, steps=steps, source="rules")

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        import affordances
        import skills

        if not self.at_home:  # explore.py's test stage starts here too
            skills.go_home(self.arm)
            self.at_home = True
        raw = {"skill": step.skill, "target": step.target, "params": dict(step.params)}
        if step.why:
            raw["why"] = step.why
        return map_verdict(step, affordances.run_step(self.arm, self.parts, raw, self.known, self.refine))

    def close(self) -> None:
        self.rig.close()


class SimBackend(PipelineRobot):
    """The team's setup by default: USB wrist camera, soft servos at 18 N.m/rad, SensX pad."""

    def __init__(self, seed: int | None = None, sensing: str = "current", slop: bool = True, stiffness: float = 18.0,
                 depth: bool = False, refine: bool = True):
        on_path(CORE_DIR, SIM_DIR)
        import sim_rig

        rig = sim_rig.make_rig(seed, slop=slop, stiffness=stiffness, sensing=sensing, depth=depth)
        super().__init__(rig, depth, refine, plan_id=f"rules-{seed if seed is not None else 'C'}")
