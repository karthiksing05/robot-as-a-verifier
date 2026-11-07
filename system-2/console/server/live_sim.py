"""Streams a real run of Joseph's MuJoCo pipeline to the Console, while it runs.

The one file in System 2 allowed to run System 1's code in-process (docs/system-boundary.md). Its streams belong behind
System 1's server, and need to move there before Live can show a robot on another machine.

    cd system-2
    uv sync --extra live
    uv run python console/server/live_sim.py        # then open Live in the Console

explore.py is unchanged and still does all the work: perception, planning, skills and verdicts. This file hooks
four seams from outside: Show (stages, log, force), Dashboard.frame (the clean camera images, before the film is
composed), viz.Video (paces to 30 fps, writes nothing) and affordances.run_plan (approval and steering between
steps). Events go through RunLog, so runs/<id>/events.jsonl is the same contract as any other run. Each run also
saves poses.bin and scene/ (the 3D view, replayed by the browser), cameras.mp4 (the other cameras) and timeline.json
(when each stage and event appears), so the Console can revisit it. Speed only changes how often frames are drawn and how long they wait: the physics, sensing and
verdicts run exactly the same at any speed.

The main view isn't a picture: /scene.json and /scene/* hand the browser the model's real geometry and textures, and
/poses streams body poses at 30 Hz, blended by the browser, so the Console renders the sim itself at the display's frame rate. The film's
pauses aren't waited for: Show.hold still runs its physics without drawing, and Show.still only keeps its last state.
MJPEG is left for the wrist and phone cameras, whose pictures come from the sim's own camera models. The server only
renders the main view if a browser without WebGL asks for it, as /feed/main, which is most of what makes this light
enough for an ordinary laptop. Meshes are simplified and textures compressed on export, for the same reason.

Local only: it binds to 127.0.0.1 and accepts commands only from the Console's own origins. Stdlib HTTP, no new
dependencies. FastAPI (docs/decisions.md Q3) can replace it when a real server is built.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import queue
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[2]  # system-2: runs/ lives here
SYSTEM_1 = REPO.parent / "system-1"
SIM_DIR = SYSTEM_1 / "sim"
sys.path[:0] = [str(SYSTEM_1 / "core"), str(SIM_DIR), str(SYSTEM_1 / "server" / "src")]  # flat modules: see the code map

import cv2  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

import affordances  # noqa: E402
import explore  # noqa: E402
import device as device_module  # noqa: E402
import faults  # noqa: E402
import perceive as perceive_module  # noqa: E402
import rgbperceive  # noqa: E402
import touch  # noqa: E402
import viz  # noqa: E402
from rav_contracts import Finding, Plan, Report, SceneInventory, Step, StepOutcome, TestRequest  # noqa: E402
from rav_server.sim_backend import map_verdict, part_to_control  # noqa: E402
from rav_harness.reward import coverage, reward  # noqa: E402
from rav_harness.runlog import RunLog  # noqa: E402
from rav_harness.trace import Tracer  # noqa: E402

PORT = 8765
ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}
MAIN_FPS, PANEL_FPS, TELEMETRY_FPS, HOLD_POSE_FPS = 30, 8, 10, 30
MAIN_SIZE = (1056, 594)  # rendered smaller than the film's 1408x792: plenty on screen, and much faster to draw
SPEEDS = (1, 2, 4, 8)
SKIP_GEOM_GROUPS = {3}  # the arm's collision copies of its visual meshes
SKIP_GEOMS = {"cyclorama"}  # the film's backdrop: the Console lights its own studio
VIDEO_FPS = 30
BLANK = np.zeros((viz.Dashboard.H, viz.Dashboard.W, 3), np.uint8)
BLANK_PANEL = np.zeros((2, 2, 3), np.uint8)
FORCE_PANEL = "force"  # the film draws its own force plot; the Console charts the same numbers itself


class StopRun(BaseException):
    """A person asked to stop. A BaseException so explore.py's `except Exception` can't swallow it as a failure."""


class Hub:
    """What the HTTP threads read and the sim thread writes. One run at a time."""

    def __init__(self):
        self.cond = threading.Condition()
        self.history: list[tuple[str, str]] = []  # (SSE name, JSON): a page that opens late still sees everything
        self.generation = 0
        self.frames: dict[str, tuple[int, bytes]] = {}
        self.commands: queue.Queue = queue.Queue()
        self.start: dict | None = None
        self.running = False
        self.project: str | None = None  # the project the current run belongs to
        self.approval: str | None = None  # the name of who approved
        self.awaiting = False  # a plan is on screen: nobody can approve a plan they haven't been shown
        self.rejected = False
        self.rate = 4  # sim seconds per second on screen, kept between runs
        self.scene: dict | None = None  # what /scene.json serves
        self.scene_blobs: dict[str, tuple[str, bytes]] = {}
        self.poses: tuple[int, str] = (0, "")
        self.watching_main = 0

    def publish(self, name: str, body: dict) -> None:
        line = json.dumps(body, separators=(",", ":"))
        with self.cond:
            self.history.append((name, line))
            self.cond.notify_all()

    def frame(self, feed: str, jpeg: bytes) -> None:
        with self.cond:
            n = self.frames.get(feed, (0, b""))[0] + 1
            self.frames[feed] = (n, jpeg)
            self.cond.notify_all()

    def reset(self) -> None:
        with self.cond:
            self.history, self.frames, self.approval, self.rejected, self.awaiting = [], {}, None, False, False
            self.scene, self.scene_blobs, self.poses = None, {}, (0, "")
            self.commands = queue.Queue()
            self.generation += 1
            self.cond.notify_all()


hub = Hub()


MESH_CELL_M = 0.0015  # vertices closer than this merge, about a fifth of the triangles and no visible change at this scale
TEXTURE_MAX, TEXTURE_QUALITY = 1024, 84
_mesh_cache: dict[bytes, bytes] = {}


def simplify_mesh(corners: np.ndarray, normals: np.ndarray) -> tuple[bytes, int, int]:
    """Vertex clustering that keeps hard edges, since vertices only merge when their normals roughly agree.
    Returns positions and normals as float32 pairs, then uint32 triangle indices, with both counts."""
    pos, nrm = corners.reshape(-1, 3).astype(np.float64), normals.reshape(-1, 3).astype(np.float64)
    keys = np.c_[np.floor(pos / MESH_CELL_M), np.round(nrm * 2)].astype(np.int64)
    hashed = (keys * np.array([73856093, 19349663, 83492791, 131, 1031, 10007], dtype=np.int64)).sum(axis=1)
    _, index, counts = np.unique(hashed, return_inverse=True, return_counts=True)
    average = lambda values: np.c_[[np.bincount(index, values[:, axis]) / counts for axis in range(3)]].T  # noqa: E731
    merged, smooth = average(pos), average(nrm)
    smooth /= np.maximum(np.linalg.norm(smooth, axis=1, keepdims=True), 1e-9)
    tris = index.reshape(-1, 3)
    tris = tris[(tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])]
    # merging can turn a small triangle over, which shows as a dark speck: face each one the way its normals point
    p0, p1, p2 = merged[tris[:, 0]], merged[tris[:, 1]], merged[tris[:, 2]]
    flipped = np.einsum("ij,ij->i", np.cross(p1 - p0, p2 - p0), smooth[tris].sum(axis=1)) < 0
    tris[flipped] = tris[flipped][:, [0, 2, 1]]
    blob = np.c_[merged, smooth].astype(np.float32).tobytes() + tris.astype(np.uint32).tobytes()
    return blob, len(merged), len(tris)


def export_scene(model, data, run_id: str, folder: pathlib.Path) -> None:
    """Hand the browser the compiled model: geoms, materials, simplified meshes, compressed textures and where each
    body starts. The same files go in the run's folder, so it can replay without the sim."""
    used_meshes, used_tex, geoms = set(), set(), []
    helper = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "target")
    for g in range(model.ngeom):
        name = model.geom(g).name
        if int(model.geom_group[g]) in SKIP_GEOM_GROUPS or name in SKIP_GEOMS or int(model.geom_bodyid[g]) == helper:
            continue
        mesh, mat = int(model.geom_dataid[g]), int(model.geom_matid[g])
        if int(model.geom_type[g]) == mujoco.mjtGeom.mjGEOM_MESH:
            used_meshes.add(mesh)
        geoms.append({"name": name, "body": int(model.geom_bodyid[g]), "type": mujoco.mjtGeom(int(model.geom_type[g])).name.removeprefix("mjGEOM_").lower(),
                      "size": model.geom_size[g].round(6).tolist(), "pos": model.geom_pos[g].round(6).tolist(),
                      "quat": model.geom_quat[g].round(6).tolist(), "mesh": mesh, "mat": mat, "rgba": model.geom_rgba[g].round(4).tolist()})
    materials = []
    for i in range(model.nmat):
        tex = int(model.mat_texid[i][mujoco.mjtTextureRole.mjTEXROLE_RGB])
        if tex >= 0:
            used_tex.add(tex)
        materials.append({"name": model.material(i).name, "rgba": model.mat_rgba[i].round(4).tolist(), "specular": float(model.mat_specular[i]),
                          "shininess": float(model.mat_shininess[i]), "emission": float(model.mat_emission[i]), "tex": tex})
    blobs: dict[str, tuple[str, bytes]] = {}
    meshes = {}
    for i in used_meshes:
        va, fa, na = model.mesh_vertadr[i], model.mesh_faceadr[i], model.mesh_normaladr[i]
        faces = model.mesh_face[fa:fa + model.mesh_facenum[i]]
        corners = model.mesh_vert[va:va + model.mesh_vertnum[i]][faces]
        normals = model.mesh_normal[na:na + model.mesh_normalnum[i]][model.mesh_facenormal[fa:fa + model.mesh_facenum[i]]]
        key = hashlib.blake2b(corners.tobytes(), digest_size=16).digest()
        if key not in _mesh_cache:  # the arm is the same in every run
            _mesh_cache[key] = simplify_mesh(corners, normals)
        blob, verts, tris = _mesh_cache[key]
        blobs[f"mesh/{i}.bin"] = ("application/octet-stream", blob)
        meshes[str(i)] = {"verts": verts, "tris": tris}
    lcd = next((i for i in range(model.nmat) if model.material(i).name == "dev_lcd"), None)
    for i in used_tex:
        if lcd is not None and int(model.mat_texid[lcd][mujoco.mjtTextureRole.mjTEXROLE_RGB]) == i:
            continue  # drawn in the browser from the device's text
        h, w, n = int(model.tex_height[i]), int(model.tex_width[i]), int(model.tex_nchannel[i])
        adr = int(model.tex_adr[i])
        pixels = cv2.cvtColor(model.tex_data[adr:adr + h * w * n].reshape(h, w, n), cv2.COLOR_RGB2BGR)
        shrink = TEXTURE_MAX / max(h, w)
        if shrink < 1:
            pixels = cv2.resize(pixels, (round(w * shrink), round(h * shrink)), interpolation=cv2.INTER_AREA)
        blobs[f"tex/{i}.jpg"] = ("image/jpeg", cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, TEXTURE_QUALITY])[1].tobytes())
    moving = [b for b in range(model.nbody) if model.body_weldid[b] != 0 and b != helper]
    scene = {"run_id": run_id, "geoms": geoms, "materials": materials, "moving": moving, "meshes": meshes,
             "files": {path: hashlib.blake2b(blob, digest_size=6).hexdigest() for path, (_, blob) in blobs.items()},
             "bodies": [{"name": model.body(b).name, "pos": data.xpos[b].round(6).tolist(), "quat": data.xquat[b].round(6).tolist()} for b in range(model.nbody)]}
    for path, (_, blob) in blobs.items():
        out = folder / "scene" / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
    (folder / "scene" / "scene.json").write_text(json.dumps(scene, separators=(",", ":")))
    with hub.cond:
        hub.scene_blobs, hub.scene = blobs, scene
        hub.cond.notify_all()


class Recorder:
    """What a run needs to replay: every body's pose per frame, and the other cameras in one small H.264 video."""
    W, SIDE_H, CAMERA_EVERY = 360, 202, 4  # a camera frame per 4 pose frames: 7.5 fps, which is about how often they change

    def __init__(self, folder: pathlib.Path):
        self.folder = folder
        self.poses = (folder / "poses.bin").open("wb")
        self.cameras = None
        self.frames = 0
        self.lcd: list[dict] = []
        self.canvas = np.zeros((self.SIDE_H * 3, self.W, 3), np.uint8)

    @property
    def t(self) -> float:
        return round(self.frames / VIDEO_FPS, 3)

    def write(self, arm, force: float, lcd: list[str], panels: list | None) -> None:
        body = [v for b in live.moving for v in (*arm.d.xpos[b], *arm.d.xquat[b])]
        self.poses.write(struct.pack(f"<{len(body) + 1}f", force, *body))
        if not self.lcd or self.lcd[-1]["lines"] != lcd:
            self.lcd.append({"t": self.t, "lines": lcd})
        if self.frames % self.CAMERA_EVERY == 0:
            self.camera_frame(panels)
        self.frames += 1

    def camera_frame(self, panels: list | None) -> None:
        import imageio_ffmpeg

        if self.cameras is None:
            self.cameras = imageio_ffmpeg.write_frames(str(self.folder / "cameras.mp4"), (self.W, self.SIDE_H * 3), pix_fmt_in="bgr24", fps=VIDEO_FPS / self.CAMERA_EVERY,
                                                       quality=5, macro_block_size=2, output_params=["-preset", "veryfast", "-movflags", "+faststart"])
            self.cameras.send(None)
        if panels:
            self.canvas[:] = 0
            for i, (title, img) in enumerate(panels[:3]):
                cell = self.canvas[i * self.SIDE_H:(i + 1) * self.SIDE_H]
                cell[:] = cv2.resize(img, (self.W, self.SIDE_H), interpolation=cv2.INTER_AREA)
                cv2.putText(cell, title[:34], (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(cell, title[:34], (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (235, 235, 235), 1, cv2.LINE_AA)
        self.cameras.send(self.canvas.tobytes())

    def close(self) -> None:
        self.poses.close()
        if self.cameras is not None:
            self.cameras.close()


class Throttled:
    """A panel's picture, redrawn only as often as it's sent. These renders were most of the cost of a frame."""

    def __init__(self, src, blank: bool):
        self.src, self.blank, self.next, self.img = src, blank, 0.0, None

    def __call__(self):
        now = time.monotonic()
        if self.blank:
            return BLANK_PANEL
        if self.img is None or now >= self.next:
            self.next = now + 1 / PANEL_FPS
            self.img = self.src()
        return self.img


class PanelList(list):
    """explore.py also appends to show.panels, so those need throttling too."""

    def append(self, item):
        title, src = item
        super().append((title, Throttled(src, FORCE_PANEL in title.lower()) if callable(src) else src))


class Live:
    """One run's bookkeeping: the event log, the steps' ids, and what steering has asked for."""

    def __init__(self, run_id: str, product: str, depth: bool, fault: str | None = None, project: str | None = None):
        self.fault = fault
        self.dir = REPO / "runs" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.recorder = Recorder(self.dir)
        self.event_times: dict[int, float] = {}
        self.stage_times: list[dict] = []

        def on_event(e):
            self.event_times[e.seq] = self.recorder.t
            hub.publish("run", e.model_dump(mode="json"))

        self.log = RunLog(run_id, REPO / "runs", on_event=on_event)
        self.tracer = Tracer(self.log)
        self.tracer.stage = (explore.DEPTH_STAGE_NAMES if depth else explore.STAGE_NAMES)[0]
        self.meta = {"run_id": run_id, "product": product, "stages": explore.DEPTH_STAGE_NAMES if depth else explore.STAGE_NAMES,
                     "route": "D405 depth camera" if depth else "USB wrist camera, OWLv2 and SAM"}
        spec = {"planted_fault": faults.FAULTS[fault]["what"]} if fault else {}  # on the record, so no one mistakes it for a find in the wild
        self.request = TestRequest(request_id=run_id, product=product, instruction="Test every control on the device.", spec=spec, project=project)
        self.stages = list(explore.DEPTH_STAGE_NAMES if depth else explore.STAGE_NAMES)
        self.ids: dict[int, str] = {}
        self.scene: SceneInventory | None = None
        self.verdicts, self.findings = [], []
        self.reported = False
        self.paused = False
        self.next_panel = self.next_main = self.next_telemetry = self.next_pose = 0.0
        self.camera_panels: list | None = None
        self.moving: list[int] = []
        self.force_t = -1.0
        self.feeds: list[str] = []
        self.step: str | None = None
        self.log.emit("run_started", self.request)
        self.meta["stages"] = self.stages
        hub.publish("meta", self.meta)

    def telemetry(self, show, now: float) -> None:
        new = [(t, s) for t, s, _ in list(show.forces) if t > self.force_t]
        force = []
        if new:
            self.force_t = new[-1][0]
            stride = max(1, len(new) // 8)
            for i in range(0, len(new), stride):  # the peak of each slice, so a short spike isn't lost
                part = new[i:i + stride]
                force.append([round(part[-1][0], 3), round(float(max(s for _, s in part)), 3)])
        hub.publish("telemetry", {"wall": round(now, 2), "sim_t": round(float(show.arm.d.time), 2), "stage": show.stage,
                                  "status": show.dash.status, "rate": hub.rate, "feeds": self.feeds, "force": force,
                                  "paused": self.paused, "step": self.step, "substage": show.dash.perceiving or None,
                                  "lcd": device_lines(show), "probe_n": round(float(show.forces[-1][1]), 2) if show.forces else 0})

    # --- steering, only ever between steps ------------------------------------------------------

    def boundary(self, steps: list | None = None, plan_rows: list | None = None, at: int = 0) -> None:
        """Apply what's queued, the same way run_test does. Blocks here while paused, never mid-motion."""
        while True:
            try:
                while True:
                    self.apply(hub.commands.get_nowait(), steps, plan_rows, at)
            except queue.Empty:
                pass
            if not self.paused:
                return
            time.sleep(0.05)

    def apply(self, c: dict, steps, plan_rows, at: int) -> None:
        kind, target, note = c["kind"], c.get("target"), ""
        if kind == "stop":
            self.steer(c, "stopping before the next step")
            raise StopRun
        if kind == "pause":
            self.paused, note = True, "paused"
        elif kind == "resume":
            self.paused, note = False, "resumed"
        elif kind in ("prioritize", "skip"):
            if steps is None:
                self.steer(c, "ignored: there is no test plan yet")
                return
            # steps and the film's plan rows move together, because explore.py pairs them by position
            rest = list(zip(steps[at:], plan_rows[at:]))
            hits = [r for r in rest if r[0]["target"] == target]
            others = [r for r in rest if r[0]["target"] != target]
            kept = others if kind == "skip" else hits + others
            steps[at:], plan_rows[at:] = [r[0] for r in kept], [r[1] for r in kept]
            note = (f"{len(hits)} steps skipped" if kind == "skip" else f"{len(hits)} steps moved to the front")
        self.steer(c, note, steps[at:] if steps is not None else None)

    def steer(self, c: dict, note: str, queue_left: list | None = None) -> None:
        body = {"kind": c["kind"], "target": c.get("target"), "text": c.get("text"), "by": c.get("by", "operator"), "note": note}
        if queue_left is not None:
            body["queue"] = [self.ids[id(s)] for s in queue_left]
        self.log.emit("steer_applied", body)

    # --- events from the stages -----------------------------------------------------------------

    def scene_ready(self, show) -> None:
        if self.scene is None and show.scene is not None:
            parts = show.scene.parts
            self.scene = SceneInventory(controls=[part_to_control(p) for p in parts])
            self.log.emit("scene_ready", self.scene)

    def plan_gate(self, show) -> None:
        """A person approves before the arm tests anything. Nothing auto-approves here."""
        self.scene_ready(show)
        steps = [Step(id=f"s{i + 1}", skill=s["skill"], target=s["target"], params=s.get("params", {}), why=s.get("why"))
                 for i, s in enumerate(show.steps)]
        self.ids = {id(raw): step.id for raw, step in zip(show.steps, steps)}
        plan = Plan(plan_id=f"rules-{self.log.run_id}", steps=steps, source="rules")
        self.log.emit("plan_ready", plan)
        self.log.emit("approval_needed", {"kind": "plan", "ref": plan.plan_id})
        show.dash.status = "WAITING FOR APPROVAL"
        self.telemetry(show, time.monotonic())
        hub.awaiting = True
        while hub.approval is None:
            if hub.rejected:
                self.log.emit("message", {"role": "harness", "text": "plan rejected, so the arm did not test anything"})
                raise StopRun
            self.boundary()  # a stop still works while waiting
            time.sleep(0.05)
        hub.awaiting = False
        self.log.emit("approved", {"kind": "plan", "ref": plan.plan_id, "by": hub.approval})

    def step_finished(self, raw: dict, result: dict) -> None:
        step = Step(id=self.ids[id(raw)], skill=raw["skill"], target=raw["target"], params=raw.get("params", {}), why=raw.get("why"))
        trace, verdict = map_verdict(step, result)
        event = self.log.emit("step_finished", StepOutcome(trace=trace, verdict=verdict))
        self.verdicts.append(verdict)
        if verdict.status == "failed":
            finding = Finding(id=f"F{len(self.findings) + 1}", severity="high" if verdict.label in ("stuck", "no_actuation", "unsafe") else "medium",
                              target=verdict.target, label=verdict.label or "anomalous", what_happened=verdict.reason,
                              step_ids=[verdict.step], event_seqs=[event.seq], evidence=verdict.evidence)
            self.findings.append(finding)
            self.log.emit("finding", finding)

    def save_timeline(self) -> None:
        self.recorder.close()
        (self.dir / "timeline.json").write_text(json.dumps({"fps": VIDEO_FPS, "duration": self.recorder.t, "meta": self.meta,
                                                            "stages": self.stage_times, "events": self.event_times, "lcd": self.recorder.lcd}))

    def report(self) -> None:
        if self.reported or self.scene is None:
            return
        self.reported = True
        cov = coverage(self.scene.controls, self.verdicts)
        score = reward(cov)
        report = Report(run_id=self.log.run_id, product=self.request.product, revision=self.request.revision, findings=self.findings,
                        coverage=cov, reward=score,
                        summary=(f"{len(cov.passed)} of {cov.detected} controls passed, {len(cov.failed)} failed, "
                                 f"{len(cov.inconclusive)} inconclusive, {len(cov.skipped)} skipped. Reward {score.value:.2f}."))
        self.log.emit("report_ready", report)
        self.log.write_report(report)


live: Live | None = None


def device_lines(show) -> list[str]:
    lcd = getattr(show.arm.app, "lcd", None)
    return [str(line) for line in device_module._lcd_lines(lcd)] if lcd else []


def publish_pose(arm) -> None:
    body = [round(float(v), 5) for b in live.moving for v in (*arm.d.xpos[b], *arm.d.xquat[b])]
    with hub.cond:
        hub.poses = (hub.poses[0] + 1, json.dumps(body, separators=(",", ":")))
        hub.cond.notify_all()


class LiveShow(explore.Show):
    def draw_stages(self, frame):
        pass  # the film's title bar: the Console draws its own stages

    # Sim seconds per second on screen, so 1x is real time at every stage. The film's own pacing, which plays slow
    # stages faster, only sets the recording's pace: a recording doesn't depend on the speed someone watched at.
    @property
    def speed(self):
        return hub.rate

    @speed.setter
    def speed(self, value):
        self._speed = value

    @property
    def panels(self):
        return self._panels

    @panels.setter
    def panels(self, value):
        self._panels = PanelList()
        for item in value:
            self._panels.append(item)

    def still(self, seconds, each=None):
        if each:  # the stage's last state, which is what the rest of the story reads
            each(1.0)

    def hold(self, seconds):
        """The film's camera hold: the physics still runs, because the servos settle in it, but nothing is drawn."""
        video, self.video = self.video, None
        try:
            super().hold(seconds)
        finally:
            self.video = video

    def draw(self):
        """The film's draw without its picture. The browser draws the main view, so the server only renders the cameras."""
        publish_pose(self.arm)  # here and not on each physics tick: frames are paced, so poses arrive evenly
        if hub.watching_main:
            return super().draw()
        arm = self.arm
        if arm.app.lcd != self.shown_lcd:
            self.shown_lcd = arm.app.lcd
            arm.app.refresh_lcd(self.r)
        self.dash.frame(None, [(title, src() if callable(src) else src) for title, src in self.panels], t=arm.d.time)
        self.video.write(BLANK)
        self.n_frames += 1

    shown_lcd = None
    next_record = None

    def tick(self, arm):
        super().tick(arm)
        if self.next_record is None:
            self.next_record = arm.d.time
        while arm.d.time + 1e-9 >= self.next_record:
            self.next_record += self._speed / VIDEO_FPS
            force = float(self.forces[-1][1]) if self.forces else 0.0
            live.recorder.write(arm, force, device_lines(self), live.camera_panels)
            if (live.recorder.frames - 1) % live.recorder.CAMERA_EVERY == 0:
                live.camera_panels = None
        if self.video is None and time.monotonic() >= live.next_pose:  # a hold draws nothing, but the servos still settle
            live.next_pose = time.monotonic() + 1 / HOLD_POSE_FPS
            publish_pose(arm)

    def log(self, text):
        super().log(text)
        live.log.emit("message", {"role": "harness", "text": text, "sim_t": round(float(self.arm.d.time), 2)})

    def set_stage(self, name, status=None):
        if name in live.stages:  # the film's own stages, like INTRO, have no place on the Console's chart
            live.tracer.stage = name
        if name == "TEST":
            live.plan_gate(self)
        elif name == "REPORT":
            live.report()
        else:
            live.boundary()
        if name == "PLAN":
            live.scene_ready(self)
        super().set_stage(name, status)
        live.stage_times.append({"name": name, "t": live.recorder.t})
        live.telemetry(self, time.monotonic())


def capture(self, main, panels=(), t=None):
    """Dashboard.frame, minus the film: publish the images as they are and hand back a blank canvas."""
    show, now = current_show(), time.monotonic()
    if main is not None and now >= live.next_main and hub.watching_main:  # the fallback for a browser without WebGL
        live.next_main = now + 1 / MAIN_FPS
        send("main", main, 72)
    shown = [(" ".join(title.split()), img) for title, img in panels if FORCE_PANEL not in title.lower()]
    live.camera_panels = shown
    if now >= live.next_panel:
        live.next_panel = now + 1 / PANEL_FPS
        for i, (_, img) in enumerate(shown):
            send(f"panel{i}", img, 68)
        live.feeds = [title for title, _ in shown]
    if now >= live.next_telemetry and show is not None:
        live.next_telemetry = now + 1 / TELEMETRY_FPS
        live.telemetry(show, now)
    return BLANK


def send(feed: str, img, quality: int) -> None:
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if ok:
        hub.frame(feed, jpeg.tobytes())


_show = None


def current_show():
    return _show


class PacedVideo:
    """Stands in for viz.Video: no file, and frames no faster than the film's 30 fps, so a person can follow it."""

    def __init__(self, path, fps=30):
        self.fps, self.frames, self.t0 = fps, 0, None

    def write(self, img):
        now = time.monotonic()
        self.t0 = self.t0 if self.t0 is not None else now
        self.frames += 1
        ahead = self.t0 + self.frames / self.fps - now
        if ahead > 0:
            time.sleep(ahead)
        elif ahead < -1:  # a slow stretch isn't made up for by racing afterwards
            self.t0 = now - self.frames / self.fps

    def close(self):
        pass


def live_run_plan(arm, parts, steps, on_step=None, refine=None):
    """affordances.run_plan, with steering between steps. The indexing is what lets steps be reordered or dropped."""
    known, results, i = {}, [], 0
    rows = current_show().dash.plan
    while True:
        live.boundary(steps, rows, i)
        if i >= len(steps):
            break
        step = steps[i]
        raw_id = live.ids[id(step)]
        live.step = live.tracer.step = raw_id
        live.log.emit("step_started", Step(id=raw_id, skill=step["skill"], target=step["target"], params=step.get("params", {}), why=step.get("why")))
        if on_step:
            on_step(step, None)
        result = live.tracer.call("robot.run_step", {"skill": step["skill"], "target": step["target"], **step.get("params", {})},
                                  lambda: affordances.run_step(arm, parts, step, known, refine), summarize=step_summary)
        results.append(result)
        if on_step:
            on_step(step, result)
        live.step_finished(step, result)
        live.step = live.tracer.step = None
        i += 1
    try:
        affordances.skills.go_home(arm)
    except affordances.SafetyStop:
        pass
    return results


def step_summary(result: dict) -> dict:
    return {k: result.get(k) for k in ("verdict", "reason", "stop", "peak_force_n", "travel_mm", "duration_s") if k in result}


def traced(module, attr: str, tool: str, args=lambda *a, **k: {}, summarize=None) -> None:
    """Log calls into Joseph's pipeline from outside it. explore.py looks these up on their modules at each call."""
    fn = getattr(module, attr)

    def call(*a, **k):
        return live.tracer.call(tool, args(*a, **k), lambda: fn(*a, **k), summarize=summarize)

    setattr(module, attr, call)


def install_hooks() -> None:
    parts_found = lambda scan: {"parts": len(scan.parts)} if hasattr(scan, "parts") else {"value": type(scan).__name__}  # noqa: E731
    traced(perceive_module, "perceive", "perception.depth_scan", summarize=parts_found)
    traced(rgbperceive, "perceive_rgb", "perception.rgb_scan", summarize=parts_found)
    traced(touch, "touch_plane", "touch.plane", summarize=lambda r: {"touches": r[1]})
    traced(touch, "touch_parts", "touch.parts", summarize=lambda parts: {"parts": len(parts)})
    traced(affordances, "plan_tests", "plan.rules", summarize=lambda steps: {"steps": len(steps)})
    traced(perceive_module, "refine", "perception.refine", args=lambda arm, wrist, part, *a, **k: {"part": part.id})

    class Recording(LiveShow):
        def __init__(self, arm, *a, **k):
            global _show
            # Every renderer shares one offscreen buffer size. The USB camera's 1280x720 renderer arrives mid-run, and
            # growing it then corrupts a smaller renderer made earlier, so reserve the film's size before any of them.
            v = arm.m.vis.global_
            v.offwidth, v.offheight = max(v.offwidth, viz.Dashboard.MAIN[2]), max(v.offheight, viz.Dashboard.MAIN[3])
            if live.fault:
                faults.plant(arm.m, live.fault)
            super().__init__(arm, *a, **k)
            _show = self
            mujoco.mj_forward(arm.m, arm.d)
            live.moving = [b for b in range(arm.m.nbody) if arm.m.body_weldid[b] != 0 and arm.m.body(b).name != "target"]
            export_scene(arm.m, arm.d, live.log.run_id, live.dir)

    explore.Show = Recording
    explore.MAIN_W, explore.MAIN_H = MAIN_SIZE
    explore.Dashboard.frame = capture
    viz.Video = PacedVideo
    affordances.run_plan = live_run_plan


def run_once(options: dict) -> None:
    global live, _show
    seed, depth, fault = options.get("seed"), bool(options.get("depth")), options.get("fault")
    name = ("preset-C" if seed is None else f"seed-{seed}") + ("-fault" if fault else "")
    run_id = f"live-{name}-{time.strftime('%H%M%S')}"
    hub.reset()
    _show = None
    live = Live(run_id, f"Sim device {'preset C' if seed is None else seed}{', planted fault' if fault else ''}", depth, fault, options.get("project"))
    argv = ["--headless", "--record", str(REPO / "runs" / run_id / "unused.mp4"), "--slop", "--stiffness", "18", "--sensing", "tactile"]
    argv += ["--depth"] if depth else []
    argv += ["--seed", str(seed)] if seed is not None else []
    status = "completed"
    try:
        show = explore.main(argv)
        if show.aborted:
            status = "aborted"
    except StopRun:
        status = "stopped"
    except Exception as e:  # shown on the screen as well as in the terminal
        import traceback
        traceback.print_exc()
        status = "aborted"
        live.log.emit("message", {"role": "harness", "text": f"the sim stopped with {type(e).__name__}: {e}"})
    live.report()
    live.log.emit("run_finished", {"status": status})
    live.save_timeline()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def allowed(self) -> bool:
        return self.headers.get("Origin") in ORIGINS

    def cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "POST, GET")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self.reply(200, {"ok": True, "running": hub.running, "project": hub.project if hub.running else None, "camera_route": importlib.util.find_spec("torch") is not None})
        elif path == "/scene.json":
            self.reply(200, hub.scene or {"run_id": None})  # polled while a run starts
        elif path.startswith("/scene/"):
            blob = hub.scene_blobs.get(path.removeprefix("/scene/"))
            if not blob:
                return self.reply(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", blob[0])
            self.send_header("Content-Length", str(len(blob[1])))
            self.send_header("Access-Control-Allow-Origin", "*")  # geometry only, on 127.0.0.1
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")  # the Console asks for these by content hash
            self.end_headers()
            self.wfile.write(blob[1])
        elif path == "/poses":
            self.pose_stream()
        elif path == "/stream":
            self.stream()
        elif path.startswith("/feed/"):
            self.feed(path.removeprefix("/feed/"))
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():  # another site in the browser can't start or steer a run
            return self.reply(403, {"error": "origin not allowed"})
        size = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            return self.reply(400, {"error": "bad json"})
        path = self.path.split("?")[0]
        if path == "/start":
            with hub.cond:
                if hub.running or hub.start is not None:
                    return self.reply(409, {"error": "a run is already going"})
                seed = body.get("seed")
                fault = body.get("fault") or None
                if fault is not None and fault not in faults.FAULTS:
                    return self.reply(400, {"error": "unknown fault"})
                project = body.get("project")
                if project is not None and not re.fullmatch(r"[a-z0-9-]{1,48}", str(project)):
                    return self.reply(400, {"error": "unknown project"})
                hub.start = {"seed": int(seed) if seed not in (None, "") else None, "depth": bool(body.get("depth")), "fault": fault, "project": project}
                hub.cond.notify_all()
            return self.reply(200, {"ok": True})
        if path == "/speed":
            if body.get("rate") not in SPEEDS:
                return self.reply(400, {"error": "unknown speed"})
            hub.rate = body["rate"]
            return self.reply(200, {"ok": True})
        if not hub.running:
            return self.reply(409, {"error": "no run is going"})
        if path in ("/approve", "/reject") and not hub.awaiting:
            return self.reply(409, {"error": "no plan is waiting"})
        if path == "/approve":
            by = str(body.get("by") or "").strip()
            if not by or by.lower() == "judge":
                return self.reply(403, {"error": "judges can steer but can't approve"})
            hub.approval = by
            return self.reply(200, {"ok": True})
        if path == "/reject":
            hub.rejected = True
            return self.reply(200, {"ok": True})
        if path == "/steer":
            if body.get("kind") not in ("pause", "resume", "stop", "prioritize", "skip"):
                return self.reply(400, {"error": "unknown command"})
            hub.commands.put(body)
            return self.reply(200, {"ok": True})
        return self.reply(404, {"error": "not found"})

    def stream(self):
        """Server-sent events: everything so far, then each new item."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.cors()
        self.end_headers()
        self.close_connection = True
        at, generation = 0, -1
        try:
            while True:
                with hub.cond:
                    if generation != hub.generation or at < len(hub.history):
                        pass
                    else:
                        hub.cond.wait(10)
                    if generation != hub.generation:
                        generation, at = hub.generation, 0
                        batch = [("reset", "{}")] + hub.history[:]
                    else:
                        batch = hub.history[at:]
                    at += len(batch) - (1 if batch and batch[0][0] == "reset" else 0)
                out = "".join(f"event: {name}\ndata: {line}\n\n" for name, line in batch) or ": still here\n\n"
                self.wfile.write(out.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return

    def pose_stream(self):
        """Latest body poses only: anyone who falls behind skips ahead, so the view never lags."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.cors()
        self.end_headers()
        self.close_connection = True
        seen = 0
        try:
            while True:
                with hub.cond:
                    if hub.poses[0] == seen or not hub.poses[1]:
                        hub.cond.wait(5)
                    n, line = hub.poses
                if n == seen or not line:
                    self.wfile.write(b": still here\n\n")
                else:
                    seen = n
                    self.wfile.write(f"data: {line}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return

    def feed(self, name: str):
        """Motion JPEG: an <img> plays it with no player code."""
        if name == "main":
            hub.watching_main += 1
        try:
            self.feed_frames(name)
        finally:
            if name == "main":
                hub.watching_main -= 1

    def feed_frames(self, name: str):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seen = 0
        try:
            while True:
                with hub.cond:
                    n, jpeg = hub.frames.get(name, (0, b""))
                    if n == seen or not jpeg:
                        hub.cond.wait(1)
                        n, jpeg = hub.frames.get(name, (0, b""))
                    if n < seen:  # a new run started
                        seen = 0
                if n == seen or not jpeg:
                    continue
                seen = n
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    install_hooks()
    server = Server(("127.0.0.1", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live sim bridge on http://127.0.0.1:{args.port}. Open Live in the Console and press Start.", flush=True)
    while True:  # MuJoCo renders on this thread: macOS needs OpenGL on the main thread
        with hub.cond:
            while hub.start is None:
                hub.cond.wait()
            options, hub.start = hub.start, None
            hub.project = options.get("project")
            hub.running = True
        try:
            run_once(options)
        finally:
            hub.running = False


if __name__ == "__main__":
    main()
