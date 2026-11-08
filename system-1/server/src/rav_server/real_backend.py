"""The real SO-101 and its USB wrist camera (hardware/hw_rig.py) as a Robot, on the RGB route: the real rig has no depth
camera. Building it connects with torque off, and main.py asks before turning torque on. Both happen once, on the main
thread at startup, and the engine's worker then uses this backend. close() takes the arm home and back to where it
rested when torque went on, then turns torque off, unless Ctrl+C already stopped it mid-motion."""
from __future__ import annotations

import pickle
import threading
import time
from dataclasses import replace

from .sim_backend import CORE_DIR, HARDWARE_DIR, PipelineRobot, on_path


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
    segmodels.owl(), segmodels.sam_boxes(), segmodels.sam_auto()
    print(f"OWLv2 and SAM loaded on {segmodels.DEVICE} in {time.monotonic() - t0:.0f} s", flush=True)


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
        self.rest, self.closing = None, threading.Lock()
        threading.Thread(target=load_models, daemon=True).start()  # while the operator checks the arm, not mid-scan

    def enable(self) -> None:
        """Torque on, holding where the arm rests now, which close() comes back to."""
        self.arm.enable(confirm=True)
        self.rest = self.arm.read_q()

    def perceive(self):
        t0, telemetry = time.monotonic(), getattr(self, "on_stage", None)

        def on_stage(name, scene=None):  # each stage of the scan in this terminal, as it starts
            views = f" ({len(scene.views)} views so far)" if name == "scan" and getattr(scene, "views", None) else ""
            print(f"  scan {time.monotonic() - t0:5.1f} s: {name}{views}", flush=True)
            if telemetry:
                telemetry(name, scene)
        self.on_stage = on_stage
        try:
            super().perceive()
        finally:
            self.on_stage = telemetry
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
        return self.current_scene()

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
