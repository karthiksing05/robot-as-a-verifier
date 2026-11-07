"""The sim's arm and world misbehaving, at random, so a caller's recovery gets tested. Sim only.

Errors change the world, never the verdict: the verdict rules run untouched on whatever then happens. Each action (each
step attempt, each explore stage) goes wrong with the given chance. What happened is written to the answer key and
nowhere else, and the messages a caller sees are the ones the real fault would give.

    UnreliableRobot(SimBackend(...), rate=0.05, seed=3)
    UnreliableRobot(SimBackend(...), schedule="2:false_alarm,button_2:stale_readout")   # forced, for tests
"""
from __future__ import annotations

import time
import zlib
from dataclasses import replace
from typing import Any

import numpy as np
from rav_interface import SceneInventory, Step, StepTrace, StepVerdict

from .robot import PipelineFailure

STEP_ERRORS = ("missed_aim", "false_alarm", "stale_readout", "pipeline_fault", "slow_arm", "device_moved")
EXPLORE_ERRORS = ("dropped_frame", "pipeline_fault", "weak_perception", "slow_arm")
# How an explore error splits. A dropped frame System 1 takes again, invisibly. A pipeline_fault crashes the scan mid-way
# and ends explore as a pipeline_error, about a third of the time, so a caller has to practise exploring again.
EXPLORE_SPLIT = (0.40, 0.33, 0.17, 0.10)
FORCED_ONLY = ("device_moved_silent",  # the device moves and nothing says so: only a caller's trend can notice
               "camera_dead")  # the wrist camera stops giving frames for the rest of the scan
EXPLORE_STAGES = ("scan", "touch", "map")
POINTS = ("slot_ends", "tip", "corners", "hinge")  # the part geometry in meta that moves with the part


def parse_schedule(text: str | None) -> dict[str, str]:
    forced: dict[str, str] = {}
    for item in filter(None, (text or "").split(",")):
        when, _, kind = item.partition(":")
        if kind not in (*STEP_ERRORS, *EXPLORE_ERRORS, *FORCED_ONLY):
            raise ValueError(f"no error called {kind!r} in {item!r}. Known: {', '.join(sorted({*STEP_ERRORS, *EXPLORE_ERRORS, *FORCED_ONLY}))}")
        forced[when] = kind
    return forced


def shifted(part: Any, d: np.ndarray) -> Any:
    """The same part with everything about where it is moved by d (metres, arm frame)."""
    T = part.T.copy()
    T[:3, 3] += d
    meta = {k: (np.asarray(v) + d if k in POINTS else v) for k, v in part.meta.items()}
    origin = None if part.origin is None else part.origin + d
    return replace(part, T=T, origin=origin, meta=meta)


class FrozenReadout:
    """The device's readout, stuck for one step. The device itself carries on behind it."""

    def __init__(self, app: Any):
        self._app, self.readings, self.events, self.lcd = app, dict(app.readings), list(app.events), app.lcd

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app, name)


class FlakyCamera:
    """The wrist camera failing as a real one does: no frame on the given captures, as a timeout, or a frame that can't be
    used at all."""

    def __init__(self, camera: Any, fail_on: set[int], forever_from: int | None = None, crash_on: int | None = None):
        self.camera, self.fail_on, self.forever_from, self.n, self.failed = camera, fail_on, forever_from, 0, 0
        self.crash_on, self.crashed = crash_on, False

    def capture(self):
        self.n += 1
        if self.n == self.crash_on:  # not a timeout: asking again won't help, and the scan stops
            self.crashed = True
            raise ValueError("wrist camera: frame failed to decode (corrupt JPEG data)")
        if self.n in self.fail_on or (self.forever_from is not None and self.n >= self.forever_from):
            self.failed += 1
            raise TimeoutError("wrist camera: no frame within 1 s")
        return self.camera.capture()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.camera, name)


class UnreliableRobot:
    def __init__(self, sim: Any, rate: float = 0.05, seed: int = 0, schedule: str | None = None):
        if not getattr(sim, "is_sim", False):
            raise ValueError("error injection is for the sim only. It must never reach a real arm")
        self.sim, self.rate, self.forced = sim, rate, parse_schedule(schedule)
        self.seed, self.rng = seed, np.random.default_rng(seed)
        self.action = 0  # a running count, for schedules that name an action number
        self.drawn: dict[str, int] = {}
        self.slow_s = (5.0, 20.0)
        self.seen: set[str] = set()

    def __getattr__(self, name: str) -> Any:  # home, frame, default_plan, current_scene, extra_actions, close, arm, rig
        return getattr(self.sim, name)

    @property
    def on_stage(self) -> Any:
        return self.sim.on_stage

    @on_stage.setter
    def on_stage(self, fn: Any) -> None:  # telemetry sets this on whatever robot it's given
        self.sim.on_stage = fn

    # --- deciding ------------------------------------------------------------------------------------

    def _roll(self, kinds: tuple[str, ...], target: str | None = None, split: tuple[float, ...] | None = None, what: str = "") -> str | None:
        """Draws every action, forced or not, so a schedule doesn't change what the seed does elsewhere. Each draw comes
        from the seed and what the action is (an explore stage, or a skill on a target), and how many times that same action
        has run, never from how many actions came before. Two callers that run the same action meet the same error, in
        whatever order they plan."""
        self.action += 1
        self.drawn[what] = n = self.drawn.get(what, 0) + 1
        self.draw = f"{what}#{n}"
        self.rng = np.random.default_rng([self.seed, zlib.crc32(self.draw.encode())])  # also what this action's error looks like
        hit, kind = self.rng.random() < self.rate, str(self.rng.choice(kinds, p=split))
        first = target is not None and target not in self.seen
        if target:
            self.seen.add(target)
        forced = self.forced.get(str(self.action)) or (self.forced.get(target) if first else None)
        return forced or (kind if hit else None)

    def _log(self, kind: str, when: str, **detail: Any) -> None:
        if self.sim.key:
            self.sim.key.error(action=self.action, draw=getattr(self, "draw", None), kind=kind, when=when, **detail)

    def _move(self, stale: bool, when: str) -> None:
        for scale in (1.0, 0.6, 0.3):
            dx, dy = self.rng.uniform(0.008, 0.025, 2) * self.rng.choice([-1, 1], 2) * scale
            yaw = float(self.rng.uniform(3, 10) * self.rng.choice([-1, 1]) * scale)
            if self.sim.move_device(float(dx), float(dy), yaw):
                self.sim.stale = self.sim.stale or stale
                self._log("device_moved" if stale else "device_moved_silent", when, dx_mm=round(float(dx) * 1000, 1), dy_mm=round(float(dy) * 1000, 1), yaw_deg=round(yaw, 1))
                return
        self._log("device_moved", when, moved=False)

    # --- the Robot interface -------------------------------------------------------------------------

    def perceive(self) -> SceneInventory:
        rolls = [(stage, self._roll(EXPLORE_ERRORS, split=EXPLORE_SPLIT, what=f"explore:{stage}")) for stage in EXPLORE_STAGES]
        drops, dead, crash = set(), None, None
        for stage, kind in rolls:
            if kind == "slow_arm":
                self._sleep(stage)
            elif kind == "dropped_frame":  # one of the scan's first nine captures: every route takes at least that many
                drops.add(EXPLORE_STAGES.index(stage) * 3 + int(self.rng.integers(1, 4)))
            elif kind == "pipeline_fault" and crash is None:  # a frame perception can't use, so the scan stops part-way
                crash = EXPLORE_STAGES.index(stage) * 3 + int(self.rng.integers(1, 4))
            elif kind == "camera_dead":
                dead = EXPLORE_STAGES.index(stage) * 3 + int(self.rng.integers(1, 4))
        real = self.sim.rig.wrist
        flaky = FlakyCamera(real, drops, dead, crash) if drops or dead or crash else None
        if flaky:
            self.sim.rig.wrist = flaky
        try:
            self.sim.perceive()
        finally:
            if flaky:
                self.sim.rig.wrist = real
                kind = "pipeline_fault" if crash and flaky.crashed else "camera_dead" if dead else "dropped_frame"
                self._log(kind, "scan", captures=sorted(drops), dead_from=dead, crash_at=crash, failed=flaky.failed, split=dict(zip(EXPLORE_ERRORS, EXPLORE_SPLIT)))
        for stage, kind in rolls:
            if kind == "weak_perception":
                self._weaken(stage)
            elif kind == "device_moved":
                self._move(True, stage)
            elif kind == "device_moved_silent":
                self._move(False, stage)
        return self.sim.current_scene()

    def _sleep(self, when: str) -> None:
        seconds = float(self.rng.uniform(*self.slow_s))
        self._log("slow_arm", when, seconds=round(seconds, 1))
        time.sleep(seconds)

    def _weaken(self, when: str) -> None:
        parts = self.sim.parts
        if not parts:
            return
        i, how = int(self.rng.integers(len(parts))), str(self.rng.choice(["low_confidence", "shifted_pose", "missing_part"]))
        part = parts[i]
        self._log("weak_perception", when, how=how, part=part.id)
        if how == "low_confidence":
            parts[i] = replace(part, score=float(self.rng.uniform(0.1, 0.3)))
        elif how == "shifted_pose":
            parts[i] = shifted(part, self._offset(part))
        else:
            parts.pop(i)

    def _offset(self, part: Any) -> np.ndarray:
        """Across the part's face, in a random direction: at this size the 6 mm pad comes off most parts, or catches an edge."""
        a, size = self.rng.uniform(0, 2 * np.pi), self.rng.uniform(0.010, 0.018)
        return size * (np.cos(a) * part.T[:3, 0] + np.sin(a) * part.T[:3, 1])

    def execute(self, step: Step) -> tuple[StepTrace, StepVerdict]:
        kinds = ("pipeline_fault", "slow_arm") if step.skill in ("observe", "reposition", "none") else STEP_ERRORS
        kind = self._roll(kinds, step.target, what=f"{step.skill}:{step.target}")
        when = f"{step.id} on {step.target}"
        if kind is None:
            return self.sim.execute(step)
        if kind == "slow_arm":
            self._sleep(when)
            return self.sim.execute(step)
        if kind == "pipeline_fault":
            self._log(kind, when)
            raise OSError("servo bus read timed out")
        if kind == "device_moved_silent":
            self._move(False, when)
            return self.sim.execute(step)
        if kind == "device_moved":  # during this step's retreat: the result stands, and the map is what's now wrong
            result = self.sim.execute(step)
            self._move(True, when)
            return result
        if kind == "missed_aim":
            return self._missed_aim(step, when)
        if kind == "false_alarm":
            return self._false_alarm(step, when)
        return self._stale_readout(step, when)

    def _missed_aim(self, step: Step, when: str) -> tuple[StepTrace, StepVerdict]:
        """The arm goes somewhere other than the last look said, so the step really lands off the part."""
        sim, look, index = self.sim, self.sim.refine, next((i for i, p in enumerate(self.sim.parts) if p.id == step.target), None)
        if index is None:
            return sim.execute(step)
        d = self._offset(sim.parts[index])
        self._log("missed_aim", when, offset_mm=round(float(np.linalg.norm(d)) * 1000, 1))
        before = sim.parts[index]
        sim.refine = (lambda arm, p: shifted(look(arm, p), d)) if look else None
        if not look:
            sim.parts[index] = shifted(before, d)
        try:
            result = sim.execute(step)
        finally:
            sim.refine = look
        if look:
            if sim.parts[index] is not before:  # it recorded where the part went, from a pose that was off by d
                sim.parts[index] = shifted(sim.parts[index], -d)
        else:
            sim.parts[index] = shifted(sim.parts[index], -d)
        return result

    def _false_alarm(self, step: Step, when: str) -> tuple[StepTrace, StepVerdict]:
        """A force spike on a healthy arm: the real safety stop fires, as it would for a real one."""
        import rig

        arm, left, fired = self.sim.arm, int(self.rng.integers(10, 60)), []
        real_tick = arm.tick

        def tick():
            nonlocal left
            f = real_tick()
            left -= 1
            if left <= 0 and not fired:
                fired.append(True)
                f = float(self.rng.uniform(rig.HARD_FORCE_CAP_N + 0.3, rig.HARD_FORCE_CAP_N + 4))
                arm.force_log.append((arm.d.time, f))
                arm.__dict__.pop("tick", None)
                if hasattr(arm, "_back_off"):
                    arm._back_off()
                raise rig.SafetyStop(f"tip force {f:.1f} N over hard cap {rig.HARD_FORCE_CAP_N} N")
            return f

        arm.tick = tick
        try:
            result = self.sim.execute(step)
        finally:
            arm.__dict__.pop("tick", None)
        self._log("false_alarm", when, fired=bool(fired))
        return result

    def _stale_readout(self, step: Step, when: str) -> tuple[StepTrace, StepVerdict]:
        """The device's readout freezes for one step, so a part that worked looks dead."""
        arm, real = self.sim.arm, self.sim.arm.app
        self._log("stale_readout", when)
        arm.app = FrozenReadout(real)
        arm.app.update = real.update  # the device keeps running under the frozen readout
        try:
            return self.sim.execute(step)
        finally:
            arm.app = real
