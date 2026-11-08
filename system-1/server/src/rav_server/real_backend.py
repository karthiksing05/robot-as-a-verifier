"""The real SO-101 and its USB wrist camera (hardware/hw_rig.py) as a Robot, on the RGB route: the real rig has no depth
camera. Building it connects with torque off, and main.py asks before turning torque on. Both happen once, on the main
thread at startup, and the engine's worker then uses this backend. close() takes the arm home and back to where it
rested when torque went on, then turns torque off, unless Ctrl+C already stopped it mid-motion."""
from __future__ import annotations

import copy
import math
import os
import pickle
import threading
import time
from dataclasses import replace

from .sim_backend import CORE_DIR, HARDWARE_DIR, PipelineRobot, map_verdict, on_path


LAST_SCAN = "last_scan.pkl"  # in the folder rav-server runs in


def shifted(p, shift):
    """Part p moved by shift's component along its panel (RealArm.part_shift)."""
    T = p.T.copy()
    T[:3, 3] += shift - (shift @ p.normal) * p.normal
    return replace(p, T=T)


def load_models():
    """OWLv2 and SAM, which the scan loads on first use (segmodels caches them)."""
    import segmodels

    t0 = time.monotonic()
    segmodels.owl(), segmodels.sam_boxes()  # not SAM's automatic masks: hw_rig turns them off
    print(f"OWLv2 and SAM loaded on {segmodels.DEVICE} in {time.monotonic() - t0:.0f} s", flush=True)


class RealBackend(PipelineRobot):
    """arm_port is the servo bus's serial port and calibration the file lerobot-calibrate wrote. The device's readout is
    its Pico on readout_port (pico_readout.PicoReadout), or with readout_device the board that POSTs to
    /readout/<readout_device> over WiFi (http_readout.HttpReadout, kept as self.http_readout for the server to feed), or
    else real_arm.OperatorReadout: after each test motion, the server's terminal asks what changed on the device."""

    touches = False  # the touch-offs and part touches never ran on a real panel: the scan's plane and heights are used

    def __init__(self, arm_port: str, calibration: str, refine: bool = True, readout_port: str | None = None,
                 readout_device: str | None = None, readout_url: str | None = None):
        on_path(CORE_DIR, HARDWARE_DIR)
        import hw_rig

        self.http_readout = None
        if readout_device:
            import http_readout
            self.http_readout = http_readout.HttpReadout(readout_device, readout_url)
        rig = hw_rig.make_rig(arm_port, calibration, app=self.http_readout, readout_port=readout_port)
        super().__init__(rig, refine=refine, plan_id="rules-real")
        self.rest, self.closing, self.stage = None, threading.Lock(), "idle"
        threading.Thread(target=load_models, daemon=True).start()  # while the operator checks the arm, not mid-scan
        if hasattr(getattr(rig.wrist, "grab", None), "read"):  # the real camera's stream (not the sim's, nor a test's)
            from . import live_view

            threading.Thread(target=live_view.run, args=(self,), daemon=True).start()

    def enable(self) -> None:
        """Torque on, holding where the arm rests now, which close() comes back to."""
        self.arm.enable(confirm=True)
        self.rest = self.arm.read_q()

    def perceive(self):
        t0, telemetry = time.monotonic(), getattr(self, "on_stage", None)

        def on_stage(name, scene=None):  # each stage of the scan in this terminal, as it starts
            views = f" ({len(scene.views)} views so far)" if name == "scan" and getattr(scene, "views", None) else ""
            print(f"  scan {time.monotonic() - t0:5.1f} s: {name}{views}", flush=True)
            if name == "scan" and getattr(scene, "views", None):  # before the arm moves: a panel off to the side shows here
                T, ext = scene.survey["panel"], scene.survey["extent"]
                print(f"  panel centre (mm) {(T[:3, 3] * 1000).round().tolist()}, extent {[round(e * 1000) for e in ext]}; "
                      f"views look at y = {[round(v['look'][1] * 1000) for v in scene.views]}", flush=True)
            self.stage = f"scan {time.monotonic() - t0:.0f} s: {name}"
            if telemetry:
                telemetry(name, scene)
        self.on_stage = on_stage
        try:
            super().perceive()
        finally:
            self.on_stage = telemetry
        self.stage = f"scanned: {len(self.parts)} parts"
        print(f"  scan {time.monotonic() - t0:5.1f} s: done, {len(self.parts)} parts: "
              + ", ".join(f"{p.id} ({p.kind})" for p in self.parts), flush=True)
        with open(LAST_SCAN, "wb") as f:  # the whole scan, to work out offline what it saw and why
            pickle.dump(self.scene, f)
        shift = getattr(self.arm, "part_shift", None)
        if shift is not None:  # as tools/press_part.py: the scan's parts and each last look's answer
            self.parts = [shifted(p, shift) for p in self.parts]
            look = self.refine
            if look is not None:
                def refine(arm, p):  # the look from the scan's position: from the shifted one its checks spent the shift
                    q = look(arm, shifted(p, -shift))
                    return shifted(q, shift) if q.meta.get("refined") else p
                self.refine = refine
                self.arm.relook = lambda part: refine(self.arm, part)  # a missed press looks again (affordances._press)
        import real_skills
        # toggles as press_part flips them: the swing snapped to the panel's slope, the push lowered onto the lever
        self.parts = [real_skills.slope_swing(copy.deepcopy(p)) if p.kind == "toggle" and "tip" in p.meta else p
                      for p in self.parts]
        return self.current_scene()

    def execute(self, step):
        """Flips and knob turns as the hardware session ran them on the real centrifuge (real_skills), which
        affordances' own can't do on this arm (its jaws don't open for them), and the centrifuge's lid, rack cover and
        tube skills (centrifuge_skills); everything else as PipelineRobot. The operator says whether the device
        changed, which gives the verdict. A lid, cover or tube skill that changed nothing is OBSERVED: the photo says."""
        import centrifuge_skills

        p = next((q for q in self.parts if q.id == step.target), None)
        if step.skill not in ("flip", "turn", *centrifuge_skills.SKILLS) or p is None:
            return self._press_with_photo(step)
        import real_skills
        import skills

        if not self.at_home:
            skills.go_home(self.arm)
        self.arm.status = "between steps"  # reading the device here sets its baseline, with nothing to ask
        before, n_ev, t0 = dict(self.arm.app.readings), len(self.arm.app.events), time.monotonic()
        angle = float(step.params.get("angle", 60.0))  # degrees, + counter-clockwise seen from the front
        done = None
        try:
            if step.skill in centrifuge_skills.SKILLS:
                done = centrifuge_skills.run(self.arm, step.skill, p, self.plane_T, step.params)
            elif step.skill == "flip" and "tip" not in p.meta:  # the review derives a lever for a switch read as a knob
                raise RuntimeError("the scan didn't measure its lever (no tip), so there's no push to plan")
            elif step.skill == "flip":
                toward =step.params.get("toward")  # +1 up the slope, -1 down: the operator's word over the scan's lean
                if toward and (p.x[2] > 0) != (toward < 0):  # the plan pushes against p.x
                    p = self._mirrored(p)
                real_skills.flip(self.arm, p, self.parts, plane=self.plane_T)
            else:
                real_skills.grip_turn(self.arm, p, self.plane_T, math.radians(angle), self.rig.wrist)
        except RuntimeError as e:  # no plan or out of reach
            r = {"verdict": "REFUSED", "reason": f"{p.id}: {e}"}
        else:
            self.at_home = False
            new = [ch for _, ch, _ in self.arm.app.events[n_ev:]] + [
                ch for ch, v in self.arm.app.readings.items() if before.get(ch) != v]
            ch = new[0] if new else None
            if step.skill == "flip" and ch:  # it went over: it now leans the other way, so a flip back pushes from there
                q = self._mirrored(p)
                self.parts = [q if x.id == p.id else x for x in self.parts]
            what = f"{p.id} switches {ch}" if step.skill == "flip" else f"turning {p.id} {angle:+g} deg changes {ch}"
            r = {"verdict": "PASS" if ch else "FAIL", "reason": what if ch else "nothing changed on the device",
                 "channel": ch, "stop": "done", "duration_s": round(time.monotonic() - t0, 1)}
            if done is not None:
                r.update(verdict="FAIL" if done["verdict"] == "FAIL" else "PASS" if ch else "OBSERVED",
                         reason=f"{done['reason']}; " + (f"{ch} changed" if ch else "no reading changed"))
        trace, verdict = map_verdict(step, r)
        ref = self._snap(f"{step.id}, at {step.target}, after the step")
        trace.frames = [ref] if ref else []
        return trace, verdict

    def extra_actions(self) -> list:
        from .actions import centrifuge_actions

        return centrifuge_actions()

    @staticmethod
    def _mirrored(p):
        """Toggle p leaning the other way: its tip mirrored through the panel's normal at the hinge."""
        n, v = p.normal, p.meta["tip"] - p.pos
        q = copy.deepcopy(p)
        q.meta = {**p.meta, "tip": p.pos + 2 * (v @ n) * n - v}
        q.T[:3, :2] *= -1
        return q

    def _press_with_photo(self, step):
        """PipelineRobot.execute, saving the wrist camera's frame at the bottom of each press (and retry) next to the
        last looks, as tools/press_part.py did: the jaw is in view there, so a press that lands off the cap shows how
        far and which way (STOP's first press landed right of a cap the scan and look both put it on)."""
        import affordances
        import touch

        line = affordances._line

        def line_with_photo(arm, *args, **kwargs):
            if arm.status.endswith(": retreat") and touch.LOOK_DIR:
                try:
                    import cv2

                    os.makedirs(touch.LOOK_DIR, exist_ok=True)
                    name = f"{time.strftime('%H%M%S')}_{arm.status.split(': ')[0].replace(' ', '_')}_bottom.jpg"
                    cv2.imwrite(os.path.join(touch.LOOK_DIR, name), self.rig.wrist.grab.read()[0])
                except Exception as e:  # noqa: BLE001 - evidence must never stop a press
                    print(f"couldn't save the press's photo: {type(e).__name__}: {e}")
            return line(arm, *args, **kwargs)
        affordances._line = line_with_photo
        try:
            return super().execute(step)
        finally:
            affordances._line = line

    def close(self) -> None:
        with self.closing:  # the engine's worker and main.py both close it: one goes home, the other waits
            if self.arm.torque and self.rest is not None:
                import skills

                print("Going home, then back to where the arm rested, then torque off")
                try:
                    skills.go_home(self.arm)
                    skills.move_joints(self.arm, self.rest)
                except Exception as e:  # noqa: BLE001 - torque goes off below whatever happened
                    print(f"Couldn't get back to rest ({type(e).__name__}: {e}): hold the arm")
            super().close()
