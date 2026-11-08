"""System 1's pipeline (pipeline.py) behind the server's Robot interface. PipelineRobot runs it on any rig (rig.Rig:
an arm and its cameras), and SimBackend builds the sim's. The stages are the ones explore.py films, in the same order:
  perceive   pipeline.scan_device, then pipeline.touch_plane and touch_parts (the RGB route)
  plan       affordances.plan_tests, plus an observe step per display
  execute    affordances.run_step, with pipeline.last_look

The two mapping functions at the top need no simulator, so they are tested without MuJoCo.
"""
from __future__ import annotations

import base64
import json
import math
import os
import pathlib
import sys
from collections import Counter, OrderedDict
from typing import Any

from rav_interface import DEVICE_CONTROL, Control, Frame, Plan, SceneInventory, Step, StepTrace, StepVerdict

from .actions import reposition_action
from .robot import PipelineFailure

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[3]
CORE_DIR, SIM_DIR, HARDWARE_DIR = SYSTEM_1 / "core", SYSTEM_1 / "sim", SYSTEM_1 / "hardware"
# What separates "the part is broken" from "the robot missed", from run_step's result. The engine puts the small ones in each stop.
MEASURES = ("contact_offset_mm", "refined", "refine_shift_mm", "refine_why", "regrip_mm", "touch_mm", "landing_n", "turned_deg",
            "force_limit_n", "collisions", "lcd")
REPOSITION_RANGE = (30.0, 30.0, 12.0)  # dx_mm, dy_mm, yaw_deg, for a device that doesn't say: world.random_placement's
VIEW_RETRIES = 3  # a camera that gives no frame is asked again this many times per view,
SCAN_RETRY_BUDGET = 6  # and this many times in one explore, before the scan gives up as a pipeline_error
FRAME_WIDTH, FRAME_QUALITY, FRAMES_KEPT, SURVEY_FRAMES = 640, 80, 300, 4


def on_path(*dirs):
    """Put System 1's folders of flat modules on the path (see system-1/sim/docs/code-map.md)."""
    for d in dirs:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))


def part_to_control(part: Any) -> Control:
    """features.Part (metres, radians) to Control (millimetres, degrees), with what a plan needs to write a valid step."""
    meta, kind = getattr(part, "meta", None) or {}, part.kind
    extra: dict[str, Any] = {}
    if kind == "slider":
        extra["position"] = round(float(part.state), 3)
        if "travel" in meta:
            extra["travel_mm"] = round(float(meta["travel"]) * 1000, 1)
    elif kind in ("dial", "knob"):
        lo, hi = getattr(part, "range", (0.0, 0.0))
        if (lo, hi) != (0, 0):  # (0, 0) means unknown
            extra["turn_range_deg"] = (round(math.degrees(lo), 1), round(math.degrees(hi), 1))
        if meta.get("detent_step"):
            extra["detent_deg"] = round(math.degrees(meta["detent_step"]), 1)
    elif kind == "toggle" and "on" in meta:
        extra["on"] = bool(meta["on"])
    elif kind == "door" and "latched" in meta:
        extra["latched"] = bool(meta["latched"])
    return Control(id=part.id, kind=kind, pos_mm=tuple(float(v) * 1000 for v in part.pos),
                   normal=tuple(float(v) for v in part.normal), size_mm=tuple(float(v) * 1000 for v in part.size),
                   motion=part.motion, grip=part.grip, conf=float(part.score), source=meta.get("source", "scan"), **extra)


def _plain(value: Any) -> Any:
    if hasattr(value, "item") and getattr(value, "ndim", 1) == 0:
        return value.item()
    return value


def map_verdict(step: Step, r: dict) -> tuple[StepTrace, StepVerdict]:
    """affordances.run_step's result dict to contracts. docs/decisions.md D9 has the vocabulary mapping."""
    raw, reason = r.get("verdict", "MISSED"), r.get("reason", "")
    label, decided_by = None, "rule"
    if raw == "PASS":
        status = "passed"
    elif raw == "OBSERVED":
        status = "observed"
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
                      readout_change={k: list(v) for k, v in (r.get("readout_change") or {}).items()},
                      measures={k: _plain(r[k]) for k in MEASURES if r.get(k) is not None})
    verdict = StepVerdict(step=step.id, target=step.target, status=status, label=label, reason=reason,
                          channel=r.get("channel"), decided_by=decided_by)
    return trace, verdict


def expected_vs_found(expected, parts) -> str:
    """A note comparing the manual's controls (SurveyAnswer.expect) with the scan's parts, kind by kind."""
    want, got = Counter(e.kind for e in expected), Counter(p.kind for p in parts)
    diffs = [f"{k}: manual {want[k]}, scan {got[k]}" for k in sorted(set(want) | set(got)) if want[k] != got[k]]
    listed = ", ".join(f"{e.name} ({e.kind})" for e in expected)
    return f"the manual lists {listed}. " + ("The scan has the same kinds and counts." if not diffs else
                                            "By kind, " + "; ".join(diffs))


class RetryingCamera:
    """A camera that's asked again when a view gives no frame, as a dropped USB frame or a driver timeout would. It holds
    still between tries, so the view is the same one. Shared by every view in one explore, and once the budget is spent
    the scan stops as a pipeline_error: perception couldn't do its job, and the arm is safe."""

    def __init__(self, camera: Any, budget: int = SCAN_RETRY_BUDGET, per_view: int = VIEW_RETRIES):
        self.camera, self.left, self.per_view, self.retried = camera, budget, per_view, []

    def capture(self):
        for attempt in range(self.per_view + 1):
            try:
                return self.camera.capture()
            except (OSError, TimeoutError, RuntimeError) as e:
                self.retried.append(f"{type(e).__name__}: {e}")
                if attempt == self.per_view or self.left <= 0:
                    raise PipelineFailure(f"the {getattr(self.camera, 'name', 'camera')} gave no frame after {len(self.retried)} tries this scan: {e}") from e
                self.left -= 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.camera, name)


class PipelineRobot:
    """The pipeline as a Robot, on any rig. A backend builds its rig and passes it in, as SimBackend does the sim's.
    Everything here runs on the engine's worker thread, except frame(), which only reads what's already encoded."""

    touches = True  # the RGB route touches the panel and some parts after the scan
    # System 2's panel pick at a survey_review stop is noted, not used: on Nov 8 it agreed with a wrong pick on the sim
    # centrifuge, and on the real one it moved the scan to a surface where it found nothing
    take_panel = False

    def __init__(self, rig, depth: bool = False, refine: bool = True, plan_id: str = "rules"):
        on_path(CORE_DIR)
        self.rig, self.arm, self.depth, self.use_refine, self.plan_id = rig, rig.arm, depth, refine, plan_id
        self.scene, self.parts, self.plane_T, self.known, self.refine = None, [], None, {}, None
        self.at_home = False
        self.notes: list[str] = []
        self.stale = False  # the device moved since the last explore
        self.survey_refs: list[str] = []
        self.review = None  # set by the engine for one explore: review(measured) holds at a survey_review stop
        self.expected, self.also_look = [], []
        self.frames: OrderedDict[str, Frame] = OrderedDict()
        self.frame_n = 0

    # --- evidence -----------------------------------------------------------------------------------

    def _store(self, bgr, caption: str) -> str | None:
        """Keeps one image, small enough for a model to read on request. Evidence must never stop a step."""
        try:
            import cv2

            h, w = bgr.shape[:2]
            if w > FRAME_WIDTH:
                bgr = cv2.resize(bgr, (FRAME_WIDTH, round(h * FRAME_WIDTH / w)), interpolation=cv2.INTER_AREA)
            ok, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, FRAME_QUALITY])
            if not ok:
                return None
        except Exception:
            return None
        self.frame_n += 1
        ref = f"frame:{self.frame_n}"
        self.frames[ref] = Frame(ref=ref, data_b64=base64.b64encode(jpeg.tobytes()).decode(), width=bgr.shape[1], height=bgr.shape[0], caption=caption)
        while len(self.frames) > FRAMES_KEPT:
            self.frames.popitem(last=False)
        return ref

    def _snap(self, caption: str) -> str | None:
        try:
            return self._store(self.rig.wrist.capture().rgb, caption)
        except Exception:
            return None

    def frame(self, ref: str) -> Frame | None:
        return self.frames.get(ref)

    def _panel_map(self) -> str | None:
        """The scan's straight-on picture of the panel with each control's id on it, so a caller can match what a manual
        names to what the scan found."""
        try:
            import cv2
            import numpy as np

            _, img, cell, origin = self.scene.heightmap
            T = self.scene.plane[0]
            img = np.clip(img * (255 if img.dtype.kind == "f" and img.max() <= 1 else 1), 0, 255).astype(np.uint8).copy()
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            scale = max(1, round(FRAME_WIDTH / max(img.shape[1], 1)))
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            for p in self.parts:
                v = np.asarray(p.pos) - T[:3, 3]
                r, c = (v @ T[:3, 0] - origin[0]) / cell * scale, (v @ T[:3, 1] - origin[1]) / cell * scale
                at = (int(c), int(r))
                cv2.circle(img, at, 3, (0, 255, 255), -1)
                cv2.putText(img, p.id, (at[0] + 5, at[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(img, p.id, (at[0] + 5, at[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
            return self._store(img, "the panel, straight on, from the scan, with each control's id")
        except Exception:
            return None

    # --- the Robot interface ------------------------------------------------------------------------

    def perceive(self) -> SceneInventory:
        import pipeline
        import rig as rig_module
        import skills

        try:
            if self.scene is not None:  # a repeat explore starts as the first did, and believes nothing from before
                skills.go_home(self.arm)
            # except, with a device file, where its moving parts were left: a lid it opened is still open
            before = self.parts
            self.parts, self.known, self.refine, self.notes = [], {}, None, []
            captured = []
            wrist = RetryingCamera(self.rig.wrist)
            phone = RetryingCamera(self.rig.phone) if self.rig.phone is not None else None
            self.expected, self.also_look = [], []
            self.scene = pipeline.scan_device(self.arm, phone, wrist, self.depth,
                                              on_stage=getattr(self, "on_stage", None), on_frame=lambda frame, _: captured.append(frame.rgb),
                                              on_survey=self._review_survey if self.review else None)
            self.parts = self.scene.parts
            if not self.depth and not self.touches:  # the last look then works on the scan's plane
                self.plane_T = self.scene.plane[0]
            elif not self.depth:  # as in explore.py: a touch that fails goes on with what the scan found, and says so
                if getattr(self, "on_stage", None):  # telemetry's stage hook
                    self.on_stage("touch", self.scene)
                self.plane_T, _, e = pipeline.touch_plane(self.arm, self.scene)
                if e:
                    self.notes.append(f"touch-offs failed, using the scan's plane: {type(e).__name__}: {e}")
                self.parts, e = pipeline.touch_parts(self.arm, self.scene, self.plane_T)
                if e:
                    self.notes.append(f"part touches failed, using the scan's heights: {type(e).__name__}: {e}")
            if self.use_refine:
                self.refine = pipeline.last_look(self.rig.wrist, self.plane_T, self.depth)
            if getattr(self, "inventory", None) is not None:
                self._registered(before)
            if self.expected:
                self.notes.append(expected_vs_found(self.expected, self.parts))
            if self.also_look:
                self.notes.append(f"not scanned, where System 2 said to look too: {'; '.join(self.also_look)}")
        except (rig_module.SafetyStop, PipelineFailure):
            raise
        except OSError:  # a driver, not perception: we can't be sure the arm is safe
            raise
        except Exception as e:
            if getattr(self.arm, "torque", True) is False:  # the real arm was stopped (Ctrl+C): a driver stop, not perception
                raise
            raise PipelineFailure(f"{type(e).__name__}: {e}") from e
        self.at_home = False  # the scan and touches left the arm over the device
        self.stale = False
        retried = wrist.retried + (phone.retried if phone else [])
        if retried:
            self.notes.append(f"{len(retried)} view(s) gave no frame at first and were taken again")
        step = max(1, len(captured) // SURVEY_FRAMES)
        views = captured[::step][:SURVEY_FRAMES]
        refs = [self._panel_map()] + [self._store(f, f"wrist camera, scan view {i + 1} of {len(views)}") for i, f in enumerate(views)]
        self.survey_refs = [r for r in refs if r]
        return self.current_scene()

    def _review_survey(self, survey: dict) -> None:
        """Holds at a survey_review stop with the survey's candidate surfaces drawn on its photo, then applies System 2's
        SurveyAnswer: another candidate as the panel, and what the manual expects, which perceive compares with the scan."""
        import rgbperceive

        cands, picked = survey["candidates"], survey["picked"]
        ref = self._store(rgbperceive.draw_candidates(survey), "the survey: each numbered outline is a flat surface the "
                          "robot measured, and the scan will look closely at the one that holds the controls")
        measured = {"candidates": [{"k": k + 1, "tilt_deg": round(math.degrees(math.acos(min(1.0, abs(float(n[2]))))), 1),
                                    "points": len(idx), "faces_arm": faces} for k, (n, _, idx, faces) in enumerate(cands)],
                    "picked": picked + 1, "frames": [ref] if ref else []}
        decision = self.review(measured)
        if decision.kind == "abort":
            raise PipelineFailure(f"stopped after the survey: {decision.note or 'System 2 aborted'}")
        answer = decision.survey
        if answer is None:
            return
        if answer.panel is not None and answer.panel - 1 != picked:
            if self.take_panel and 1 <= answer.panel <= len(cands):
                rgbperceive.use_panel(survey, answer.panel - 1)
                self.notes.append(f"System 2 picked surface {answer.panel} as the panel over the survey's {picked + 1}")
            else:
                self.notes.append(f"System 2 would pick surface {answer.panel} as the panel; the scan keeps the survey's "
                                  f"{picked + 1}")
        self.expected, self.also_look = answer.expect, answer.also_look

    def _registered(self, before: list) -> None:
        """With a device file: register its roots from the scan's parts and touches, and add each part the scan didn't
        find, from CAD at the registered pose (Control.source "cad"). Moving parts keep the state the robot last left
        them in. The notes say what came from where and what registration measured."""
        import inventory
        import skills

        skills.go_home(self.arm)
        Ts, report = self.inventory.register(self.arm, scanned=self.parts)
        lost = {root for root, r in report.items() if r.get("lost")}
        cad = self.inventory.parts(Ts, carried=before, lost=lost)
        self.parts, source = inventory.merge(self.parts, cad)
        for root, r in report.items():
            how = f"measured {', '.join(r['measured']) or 'nothing'} ({r['touches']} touches, {r['scan_matches']} scanned parts)"
            self.notes.append(f"registered {root}: moved {r['dx_mm']:+.1f}, {r['dy_mm']:+.1f} mm, {r['dyaw_deg']:+.1f} deg from the guess; {how}"
                              + (f"; {len(r['failed'])} touch(es) failed" if r["failed"] else "")
                              + (f"; LOST, {r['lost']}: its parts are left out" if r.get("lost") else ""))
        from_cad = sorted(i for i, s in source.items() if s == "cad")
        from_scan = sorted(i for i, s in source.items() if s == "scan")
        self.notes.append(f"from the scan: {', '.join(from_scan) or 'nothing'}. From CAD, where the scan saw nothing: {', '.join(from_cad) or 'nothing'}")
        self.at_home = True

    def current_scene(self) -> SceneInventory:
        """The inventory as the robot believes it now: steps move parts, and a plan needs to know where they are."""
        controls = [part_to_control(p) for p in self.parts]
        if controls and self.extra_actions():
            middle = tuple(sum(c.pos_mm[i] for c in controls) / len(controls) for i in range(3))
            controls.append(Control(id=DEVICE_CONTROL, kind="object", pos_mm=middle, normal=(0.0, 0.0, 1.0), source="scan"))
        return SceneInventory(controls=controls, notes=self.notes, frames=self.survey_refs, stale=self.stale)

    def extra_actions(self) -> list:
        """What this robot offers beyond the table. A backend that can move the device adds reposition."""
        return []

    def reposition(self, dx_mm: float, dy_mm: float, yaw_deg: float) -> str | None:
        """Move the device. None if it moved, else why it didn't."""
        return "this robot can't move the device"

    def _reposition(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        p = step.params
        asked = {k: float(p.get(k, 0.0)) for k in ("dx_mm", "dy_mm", "yaw_deg")}
        if not any(asked.values()):
            why: str | None = "nothing to do: every param is 0"
        else:
            why = self.reposition(**asked)
            self.stale = self.stale or why is None
        ok = why is None
        trace = StepTrace(step=step.id, stop_reason="moved" if ok else None, measures=asked)
        return trace, StepVerdict(step=step.id, target=step.target, status="passed" if ok else "skipped",
                                  reason=f"moved the device {asked}" if ok else why)

    def default_plan(self, scene: SceneInventory) -> Plan:
        import affordances

        raw = affordances.plan_tests(self.parts)
        raw += [{"skill": "observe", "target": p.id, "params": {}} for p in self.parts if p.kind == "display"]
        steps = [Step(id=f"s{n + 1}", skill=s["skill"], target=s["target"], params=s.get("params", {}), why=s.get("why"))
                 for n, s in enumerate(raw)]
        return Plan(plan_id=self.plan_id, steps=steps, source="rules")

    def home(self) -> None:
        import skills

        skills.go_home(self.arm)
        self.at_home = True

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        import affordances
        import skills

        if step.skill == "reposition":
            return self._reposition(step)
        if not self.at_home:  # explore.py's test stage starts here too
            skills.go_home(self.arm)
            self.at_home = True
        raw = {"skill": step.skill, "target": step.target, "params": dict(step.params)}
        if step.why:
            raw["why"] = step.why
        frames: list[str] = []
        look = self.refine

        def refine(arm, part):  # run_step calls this at the approach pose, looking at the part
            ref = self._snap(f"{step.id}, at {step.target}, before touching it")
            if ref:
                frames.append(ref)
            return look(arm, part)

        result = affordances.run_step(self.arm, self.parts, raw, self.known, refine if look else None)
        if result.get("verdict") not in ("REFUSED", "OBSERVED"):
            ref = self._snap(f"{step.id}, at {step.target}, after the step")
            if ref:
                frames.append(ref)
        elif step.skill == "observe":
            ref = self._snap(f"{step.id}, the arm's view during the reading")
            if ref:
                frames.append(ref)
        trace, verdict = map_verdict(step, result)
        readings = getattr(self.arm.app, "readings", None)
        if readings:
            trace.measures["readings"] = dict(readings)
        trace.frames = frames
        return trace, verdict

    def close(self) -> None:
        self.rig.close()


class AnswerKey:
    """The device's true parts, planted faults and every injected error, in a file only the scorer reads. It never
    crosses a tool: nothing in the engine or the server can see it."""

    def __init__(self, path: str | os.PathLike, seed: int | None, placement: str):
        self.path = pathlib.Path(path)
        self.data: dict[str, Any] = {"device": {"seed": seed, "placement": placement}, "controls": [], "faults": [], "errors": []}

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(self.data, indent=2, default=float) + "\n")
        os.replace(temp, self.path)

    def error(self, **entry: Any) -> None:
        self.data["errors"].append(entry)
        self.write()


class SimBackend(PipelineRobot):
    """The team's setup by default: USB wrist camera, soft servos at 18 N.m/rad, SensX pad. faults go into the physics
    before anything runs ("stuck_button", "stuck_button:button_1" or "random"), and verdict rules see only the result."""

    is_sim = True

    def __init__(self, seed: int | None = None, sensing: str | None = None, slop: bool = True, stiffness: float = 18.0,
                 depth: bool = False, refine: bool = True, placement: str = "nominal", faults: tuple[str, ...] = (),
                 fault_seed: int | None = None, answer_key: str | os.PathLike | None = None, device: str | os.PathLike | None = None,
                 rev: str = "B", effector: str = "stock", mounts: dict | None = None):
        """device: a device file (sim/cad_device.py) in place of a generated device, with rev, its revision or fault
        choices ("A", "F1=B,F2=B,F3=A"): its faults are its parts, so `faults` must be empty. effector: "stock"
        (the SO-101's own gripper, the real arm's only effector) or "probe" (the fingertip probe, a sim-only reference). mounts: {root: "clamped" | "free"} over the file's."""
        on_path(CORE_DIR, SIM_DIR)
        sensing = sensing or ("tactile" if effector == "probe" else "current")  # the stock gripper has no pad: the servos' current
        import faults as fault_module
        import sim_rig

        if device and faults:
            raise ValueError("a device file's faults are its revision's parts: pass rev, not faults")
        rig = sim_rig.make_rig(seed, placement=placement, slop=slop, stiffness=stiffness, sensing=sensing, depth=depth,
                               device=str(device) if device else None, rev=rev, effector=effector, mounts=mounts)
        super().__init__(rig, depth, refine, plan_id=f"rules-{seed if seed is not None else 'C'}")
        if device:
            import inventory

            # the robot's own copy of what the device file says is on it, registered where touches and the scan put it
            self.inventory = inventory.Inventory(device, rev)
        self.key = AnswerKey(answer_key, seed, placement) if answer_key else None
        self.planted = []
        for spec in faults:
            name, part = fault_module.resolve(self.arm.m, spec, seed if fault_seed is None else fault_seed)
            self.planted.append({"fault": name, "part": part, "what": fault_module.plant(self.arm.m, name, part, self.arm.app, self.arm.d)})
        self._write_truth()

    def truth(self) -> list[dict]:
        import device
        import mujoco

        mujoco.mj_forward(self.arm.m, self.arm.d)
        w = self.arm.world
        if hasattr(w, "answer_key"):  # a device file: its channels are its firmware's
            chans = {c["id"]: c.get("channel") for c in w.cfg["controls"]}
            return [{"id": p.id, "kind": p.kind, "pos_mm": [round(float(v) * 1000, 2) for v in p.pos], "channel": chans.get(p.id)}
                    for p in w.truth(self.arm.m, self.arm.d)]
        return [{"id": p.id, "kind": p.kind, "pos_mm": [round(float(v) * 1000, 2) for v in p.pos], "channel": None if p.kind == "display" else device.channel_of(p.id)}
                for p in device.truth(self.arm.m, self.arm.d)]

    def _write_truth(self) -> None:
        if self.key:
            w = self.arm.world
            faults = w.answer_key()["faults"] if hasattr(w, "answer_key") else self.planted
            self.key.data.update(controls=self.truth(), faults=faults, name=w.name)
            if hasattr(w, "answer_key"):
                self.key.data["device"].update(rev=w.answer_key().get("choices"), mounts={r: w.mount(r) for r in w.cfg["roots"]})
            self.key.write()

    def extra_actions(self) -> list:
        out = [reposition_action(*getattr(self.arm.world, "reposition_range", REPOSITION_RANGE))]
        if getattr(self, "inventory", None) is not None:
            from .actions import manipulate_actions

            opens = [c.get("open_deg", 105.0) for c in self.inventory.cfg["controls"] if c["kind"] == "handle"]
            out += manipulate_actions(getattr(self.arm, "effector", "probe") == "stock", max(opens, default=105.0))
        return out

    def reposition(self, dx_mm: float, dy_mm: float, yaw_deg: float) -> str | None:
        """A device from a device file is pushed by the arm (inventory.push): only a root that isn't clamped, only
        away from the arm along its push face, and how far it went is measured, not assumed. A generated device is
        simply placed at the new pose."""
        inv = getattr(self, "inventory", None)
        if inv is None:
            return None if self.move_device(dx_mm / 1000, dy_mm / 1000, yaw_deg) else "the arm couldn't reach every part from there"
        import inventory

        root = next(iter(inv.cfg["roots"]))  # "device" is the main root: the first in the file
        r = inventory.push(self.arm, inv, root, dx_mm, dy_mm, yaw_deg, self.arm.world.mount(root))
        self.at_home = True
        self.last_push = r
        if self.key:
            self.key.data["controls"] = self.truth()
            self.key.write()
        if r["moved_mm"]:
            return None if r["ok"] else f"moved only {r['moved_mm']} mm: {r['reason']}"
        return r["reason"]

    def move_device(self, dx: float, dy: float, yaw_deg: float) -> bool:
        """Moves the whole device on the desk, as a bump would: dx, dy in metres, about its own origin. False, with
        nothing moved, if the arm couldn't then reach every part."""
        import device
        import mujoco
        import numpy as np

        m, d, body = self.arm.m, self.arm.d, self.arm.m.body("device").id
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, m.body_quat[body])
        a = math.radians(yaw_deg)
        spin = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        T = np.eye(4)
        T[:3, :3] = spin @ R.reshape(3, 3)
        T[:3, 3] = m.body_pos[body] + (dx, dy, 0.0)
        if not device.reachable(self.arm.world.spec, T):
            return False
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, T[:3, :3].ravel())
        m.body_pos[body], m.body_quat[body] = T[:3, 3], q
        mujoco.mj_forward(m, d)
        if self.key:
            self.key.data["controls"] = self.truth()
            self.key.write()
        return True
