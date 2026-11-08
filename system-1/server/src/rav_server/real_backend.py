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


def live_view(wrist, status):
    """A window with the wrist camera's newest frame at half size, the gripper's mask outlined, and status(), as
    tools/scan_check.py shows. It reads frames only, never the arm, so it runs beside the scan."""
    import cv2
    import rgbperceive

    while True:
        bgr, _ = wrist.grab.read()
        img = cv2.resize(bgr, None, fx=0.5, fy=0.5)
        cv2.polylines(img, [rgbperceive._gripper(img.shape[1])], True, (0, 200, 255), 2)
        for color, width in (((0, 0, 0), 5), ((255, 255, 255), 2)):
            cv2.putText(img, status(), (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, width)
        cv2.imshow("System 1: wrist camera", img)
        cv2.waitKey(80)


class RealBackend(PipelineRobot):
    """arm_port is the servo bus's serial port and calibration the file lerobot-calibrate wrote. The device's readout is
    its Pico on readout_port (pico_readout.PicoReadout), or without one real_arm.OperatorReadout: after each test
    motion, the server's terminal asks what changed on the device."""

    touches = False  # the touch-offs and part touches never ran on a real panel: the scan's plane and heights are used

    def __init__(self, arm_port: str, calibration: str, refine: bool = True, readout_port: str | None = None):
        on_path(CORE_DIR, HARDWARE_DIR)
        import hw_rig

        rig = hw_rig.make_rig(arm_port, calibration, readout_port=readout_port)
        super().__init__(rig, refine=refine, plan_id="rules-real")
        self.rest, self.closing, self.stage = None, threading.Lock(), "idle"
        threading.Thread(target=load_models, daemon=True).start()  # while the operator checks the arm, not mid-scan
        if hasattr(getattr(rig.wrist, "grab", None), "read"):  # the real camera's stream (not the sim's, nor a test's)
            status = lambda: f"{self.stage} | {self.arm.status}"  # noqa: E731
            threading.Thread(target=live_view, args=(rig.wrist, status), daemon=True).start()

    def enable(self) -> None:
        """Torque on, holding where the arm rests now, which close() comes back to."""
        self.arm.enable(confirm=True)
        self.rest = self.arm.read_q()

    def perceive(self):
        t0, telemetry = time.monotonic(), getattr(self, "on_stage", None)

        def on_stage(name, scene=None):  # each stage of the scan in this terminal, as it starts
            views = f" ({len(scene.views)} views so far)" if name == "scan" and getattr(scene, "views", None) else ""
            print(f"  scan {time.monotonic() - t0:5.1f} s: {name}{views}", flush=True)
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
                def refine(arm, p):
                    q = look(arm, p)
                    return shifted(q, shift) if q.meta.get("refined") else q
                self.refine = refine
        import real_skills
        # toggles as press_part flips them: the swing snapped to the panel's slope, the push lowered onto the lever
        self.parts = [real_skills.slope_swing(copy.deepcopy(p)) if p.kind == "toggle" and "tip" in p.meta else p
                      for p in self.parts]
        return self.current_scene()

    def execute(self, step):
        """Flips and knob turns as the hardware session ran them on the real centrifuge (real_skills), which
        affordances' own can't do on this arm (its jaws don't open for them); everything else as PipelineRobot. The
        operator says whether the device changed, which gives the verdict."""
        p = next((q for q in self.parts if q.id == step.target), None)
        if step.skill not in ("flip", "turn") or p is None:
            return self._press_with_photo(step)
        import real_skills
        import skills

        if not self.at_home:
            skills.go_home(self.arm)
        self.arm.status = "between steps"  # reading the device here sets its baseline, with nothing to ask
        before, n_ev, t0 = dict(self.arm.app.readings), len(self.arm.app.events), time.monotonic()
        angle = float(step.params.get("angle", 60.0))  # degrees, + counter-clockwise seen from the front
        try:
            if step.skill == "flip" and "tip" not in p.meta:  # the review derives a lever for a switch read as a knob
                raise RuntimeError("the scan didn't measure its lever (no tip), so there's no push to plan")
            if step.skill == "flip":
                real_skills.flip(self.arm, p, self.parts)
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
                n, v = p.normal, p.meta["tip"] - p.pos
                q = copy.deepcopy(p)
                q.meta = {**p.meta, "tip": p.pos + 2 * (v @ n) * n - v}
                q.T[:3, :2] *= -1
                self.parts = [q if x.id == p.id else x for x in self.parts]
            what = f"{p.id} switches {ch}" if step.skill == "flip" else f"turning {p.id} {angle:+g} deg changes {ch}"
            r = {"verdict": "PASS" if ch else "FAIL", "reason": what if ch else "nothing changed on the device",
                 "channel": ch, "stop": "done", "duration_s": round(time.monotonic() - t0, 1)}
        trace, verdict = map_verdict(step, r)
        ref = self._snap(f"{step.id}, at {step.target}, after the step")
        trace.frames = [ref] if ref else []
        return trace, verdict

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
