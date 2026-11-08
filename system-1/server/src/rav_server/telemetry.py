"""The telemetry channel: what people watch, one way, never in a model's context (docs/system-boundary.md).

    GET  /health            run id, stages, feeds, speed, whether a scene is ready, the recording's clock
    GET  /scene.json        the compiled model: geoms, materials, moving bodies. {"run_id": null} until a routine has built it
    GET  /scene/<path>      its meshes and textures, by content hash
    GET  /scan.json         the real arm's last scan: panel corners, parts, and the id of /scan.bin's coloured points
    GET  /scan.bin          those points, int16 xyz in 0.1 mm then RGB bytes
    GET  /poses             SSE at 30 Hz: seven floats per moving body. Latest only, so a slow viewer skips ahead
    GET  /telemetry         SSE, named "telemetry": stage, status, force samples, step, lcd, probe_n
    GET  /feed/<camera>     MJPEG
    POST /speed {"rate": n} sim seconds per second. 0: as fast as the sim goes

The hooks are the arm's on_tick and the wrist's capture, both on the routine worker, which owns the renderers. Nothing
here changes the run: previews render without the cameras' noise generators, and the scene is read from a scratch MjData.
A camera renders only while someone is watching it or a recording needs it, and a hook that raises is switched off
rather than stopping a routine.

With record_dir, poses.bin, scene/, cameras.mp4 and timeline.json go there, one frame per 1/30 sim second, so a run
replays in the Console as live_sim's do. timeline.json's events are empty: System 2 owns the event log, and fills them
from its own clock using `anchors`, pairs of (wall seconds since the epoch, seconds into the recording).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ORIGINS = {f"http://{h}:{p}" for h in ("127.0.0.1", "localhost") for p in (5173, 5174)}  # 5174: Vite's next port when 5173 is taken
POSE_FPS, TELEMETRY_FPS, PANEL_FPS, RECORD_FPS = 30, 10, 8, 30
SPEEDS = (0, 1, 2, 4, 8)
HEARTBEAT_S = 0.5
FALLEN_BEHIND_S = 0.25  # pacing starts again from here after a pause, instead of racing to catch up
RGB_STAGES = ("SURVEY", "SCAN", "SEGMENT", "MAP", "TOUCH", "PLAN", "TEST", "REPORT")
DEPTH_STAGES = ("SURVEY", "SCAN", "MAP", "PLAN", "TEST", "REPORT")
STAGE_OF = {"survey": "SURVEY", "views": "SURVEY", "scan": "SCAN", "poses": "SEGMENT", "orthophoto": "SEGMENT", "segment": "SEGMENT",
            "heights": "MAP", "classify": "MAP", "fuse": "MAP", "plane": "MAP", "heightmap": "MAP", "touch": "TOUCH"}

SKIP_GEOM_GROUPS = {3}  # the arm's collision copies of its visual meshes
SKIP_GEOMS = {"cyclorama"}  # the film's backdrop: the Console lights its own studio
REAL_ARM_HIDDEN = ("wrist_camera",)  # the sim's D405-sized camera: the real arm's is another camera, mounted elsewhere
MESH_CELL_M = 0.0015  # vertices closer than this merge, about a fifth of the triangles and no visible change at this scale
TEXTURE_MAX, TEXTURE_QUALITY = 1024, 84
FEED_WIDTH, JPEG_QUALITY = 1280, 80
SCAN_POINTS = 40_000  # the real scan's height map, thinned to about this many points: ~360 kB once per scan
_mesh_cache: dict[bytes, tuple[bytes, int, int]] = {}


def simplify_mesh(corners, normals) -> tuple[bytes, int, int]:
    """Vertex clustering that keeps hard edges, since vertices only merge when their normals roughly agree.
    Returns positions and normals as float32 pairs, then uint32 triangle indices, with both counts."""
    import numpy as np

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


def moving_bodies(model) -> list[int]:
    import mujoco

    helper = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "target")
    return [b for b in range(model.nbody) if model.body_weldid[b] != 0 and b != helper]


def build_scene(model, data, run_id: str, hide: tuple[str, ...] = ()) -> tuple[dict, dict[str, tuple[str, bytes]]]:
    """The compiled model for the browser, and its files as {path: (type, bytes)}. It reads only what MuJoCo compiled, so
    any device works, generated or loaded from CAD meshes. hide: bodies whose geoms are left out."""
    import cv2
    import mujoco

    used_meshes, used_tex, geoms = set(), set(), []
    skip = {mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b) for b in ("target", *hide)}
    for g in range(model.ngeom):
        name = model.geom(g).name
        if int(model.geom_group[g]) in SKIP_GEOM_GROUPS or name in SKIP_GEOMS or int(model.geom_bodyid[g]) in skip:
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
    scene = {"run_id": run_id, "geoms": geoms, "materials": materials, "moving": moving_bodies(model), "meshes": meshes,
             "files": {path: hashlib.blake2b(blob, digest_size=6).hexdigest() for path, (_, blob) in blobs.items()},
             "bodies": [{"name": model.body(b).name, "pos": data.xpos[b].round(6).tolist(), "quat": data.xquat[b].round(6).tolist()} for b in range(model.nbody)]}
    return scene, blobs


def scan_cloud(scene: Any, parts: list, shift: Any = None) -> tuple[dict, bytes]:
    """The real arm's last scan for the Console: its height map as at most SCAN_POINTS coloured points (int16 xyz in
    0.1 mm, then uint8 RGB), the panel's corners, and each part where the camera saw it (parts are moved by shift,
    RealArm.part_shift, for the arm)."""
    import numpy as np

    hm, img, cell, (u0, v0) = scene.heightmap
    Tg, (a, b, c, d) = scene.plane
    every = max(1, int(np.ceil(np.sqrt(np.isfinite(hm).sum() / SCAN_POINTS))))
    i, j = np.mgrid[:hm.shape[0]:every, :hm.shape[1]:every]
    h = hm[i, j]
    ok = np.isfinite(h)
    i, j, h = i[ok], j[ok], h[ok]
    pts = Tg[:3, 3] + np.c_[u0 + i * cell, v0 + j * cell, h] @ Tg[:3, :3].T
    rgb = img[i, j][:, ::-1]  # the orthophoto is BGR
    blob = np.clip(np.round(pts / 1e-4), -32767, 32767).astype("<i2").tobytes() + rgb.astype(np.uint8).tobytes()
    corner = lambda u, v: (Tg[:3, 3] + u * Tg[:3, 0] + v * Tg[:3, 1]).round(4).tolist()  # noqa: E731
    out = []
    for p in parts:
        n, m = p.normal, p.meta
        pos = p.pos if shift is None else p.pos - (shift - (shift @ n) * n)
        r = m.get("radius") or m.get("pad_radius") or m.get("knob_radius") or max(p.size[:2]) / 2
        out.append({"id": p.id, "kind": p.kind, "pos": pos.round(4).tolist(), "normal": n.round(4).tolist(), "r": round(float(r), 4)})
    body = {"points": int(len(pts)), "spacing": every * cell, "panel": [corner(a, c), corner(b, c), corner(b, d), corner(a, d)],
            "normal": Tg[:3, 2].round(4).tolist(), "parts": out}
    body["id"] = hashlib.blake2b(blob + json.dumps(body).encode(), digest_size=6).hexdigest()
    return body, blob


def write_scene(folder: pathlib.Path, scene: dict, blobs: dict[str, tuple[str, bytes]]) -> None:
    for path, (_, blob) in blobs.items():
        out = folder / "scene" / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
    (folder / "scene").mkdir(parents=True, exist_ok=True)
    (folder / "scene" / "scene.json").write_text(json.dumps(scene, separators=(",", ":")))


def lcd_lines(text: Any) -> list[str]:
    if not text:
        return []
    device = sys.modules.get("device")  # the sim's way of laying out its display, when it's loaded
    return [str(line) for line in device._lcd_lines(text)] if device else [str(text)]


class Recorder:
    """What a run needs to replay: every body's pose per frame, and the cameras in one small H.264 video."""
    W, SIDE_H, CAMERA_EVERY = 360, 202, 4  # a camera frame per 4 pose frames: 7.5 fps, which is about how often they change

    def __init__(self, folder: pathlib.Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.poses = (folder / "poses.bin").open("wb")
        self.cameras, self.canvas = None, None
        self.frames = 0
        self.next_at: float | None = None
        self.lcd: list[dict] = []
        self.stages: list[dict] = []
        self.steps: list[dict] = []
        self.anchors: list[list[float]] = []
        self.lock = threading.Lock()

    @property
    def t(self) -> float:
        return round(self.frames / RECORD_FPS, 3)

    def write(self, force: float, body: list[float], lcd: list[str]) -> None:
        with self.lock:
            if self.poses.closed:
                return
            self.poses.write(struct.pack(f"<{len(body) + 1}f", force, *body))
            if not self.lcd or self.lcd[-1]["lines"] != lcd:
                self.lcd.append({"t": self.t, "lines": lcd})
            if self.frames % RECORD_FPS == 0:
                self.anchors.append([round(time.time(), 3), self.t])
            self.frames += 1

    def camera_frame(self, panels: list[tuple[str, Any]]) -> None:
        import cv2
        import numpy as np

        with self.lock:
            if self.poses.closed:
                return
            if self.cameras is None:
                import imageio_ffmpeg

                self.canvas = np.zeros((self.SIDE_H * 3, self.W, 3), np.uint8)
                self.cameras = imageio_ffmpeg.write_frames(str(self.folder / "cameras.mp4"), (self.W, self.SIDE_H * 3), pix_fmt_in="bgr24", fps=RECORD_FPS / self.CAMERA_EVERY,
                                                           quality=5, macro_block_size=2, output_params=["-preset", "veryfast", "-movflags", "+faststart"])
                self.cameras.send(None)
            self.canvas[:] = 0
            for i, (title, img) in enumerate(panels[:3]):
                cell = self.canvas[i * self.SIDE_H:(i + 1) * self.SIDE_H]
                cell[:] = cv2.resize(img, (self.W, self.SIDE_H), interpolation=cv2.INTER_AREA)
                cv2.putText(cell, title[:34], (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(cell, title[:34], (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (235, 235, 235), 1, cv2.LINE_AA)
            self.cameras.send(self.canvas.tobytes())

    def save_timeline(self, meta: dict) -> None:
        with self.lock:
            if not self.poses.closed:
                self.poses.flush()
            body = {"fps": RECORD_FPS, "duration": self.t, "meta": meta, "stages": self.stages, "events": {}, "lcd": self.lcd,
                    "steps": self.steps, "anchors": self.anchors}
        temp = self.folder / "timeline.json.tmp"
        temp.write_text(json.dumps(body))
        temp.replace(self.folder / "timeline.json")

    def close(self, meta: dict) -> None:
        self.save_timeline(meta)
        with self.lock:
            self.poses.close()
            if self.cameras is not None:
                self.cameras.close()
                self.cameras = None


class Telemetry:
    def __init__(self, speed: float = 0, record_dir: str | pathlib.Path | None = None, run_id: str | None = None,
                 status: Callable[[], Any] | None = None):
        self.record_dir = pathlib.Path(record_dir) if record_dir else None
        self.run_id = run_id or (self.record_dir.name if self.record_dir else f"s1-{int(time.time())}")
        self.status_fn = status
        self.cond = threading.Condition()
        self.scene: dict | None = None
        self.blobs: dict[str, tuple[str, bytes]] = {}
        self.scan: tuple[dict, bytes] | None = None  # the real arm's last scan (scan_cloud)
        self.poses: tuple[int, str] = (0, "")
        self.telemetry: tuple[int, str] = (0, "")
        self.frames: dict[str, tuple[int, bytes]] = {}
        self.watching: dict[str, int] = {}  # viewers per stream: "poses", "telemetry" and each camera
        self.speed = float(speed)
        self.real = False  # the real arm runs in real time: the Console offers no speeds
        self.meta = {"run_id": self.run_id, "product": "", "stages": list(RGB_STAGES), "route": ""}
        self.stage, self.substage, self.step = "", None, None
        self.status, self.sim_t, self.lcd, self.probe_n = "", 0.0, [], 0.0
        self.forces: deque[tuple[float, float]] = deque(maxlen=4000)
        self.feeds: list[str] = []
        self.arm: Any = None
        self.cameras: dict[str, Any] = {}
        self.views: dict[str, tuple[float, Any]] = {}
        self.moving: list[int] = []
        self.recorder: Recorder | None = None
        self.hooks_on = True
        self.next_pose = self.next_telemetry = self.next_panel = 0.0
        self.pace_sim: float | None = None
        self.pace_wall = 0.0
        self.server: ThreadingHTTPServer | None = None
        self.closed = threading.Event()

    # --- on the worker ---------------------------------------------------------------------------

    def instrument(self, robot: Any) -> Any:
        """Called on the worker with the robot it just built, so the renderers stay on that thread. Returns the robot."""
        for name, wrap in (("perceive", self._around_perceive), ("execute", self._around_execute), ("home", self._around_home)):
            fn = getattr(robot, name, None)
            if fn:
                setattr(robot, name, wrap(fn))
        robot.on_stage = lambda name, _scene=None: self.set_stage(STAGE_OF.get(name, self.stage or "MAP"), name)
        rig = getattr(robot, "rig", None)
        depth = bool(getattr(robot, "depth", False))
        self.meta.update(product=getattr(rig, "name", "") or "", stages=list(DEPTH_STAGES if depth else RGB_STAGES),
                         route="D405 depth camera" if depth else "USB wrist camera, OWLv2 and SAM")
        arm = getattr(robot, "arm", None)
        if arm is None or not hasattr(arm, "on_tick"):
            return robot  # nothing to watch but the stages
        self.arm = arm
        self.cameras = {name: cam for name, cam in (("wrist", getattr(rig, "wrist", None)), ("phone", getattr(rig, "phone", None))) if cam is not None}
        self.feeds = list(self.cameras)
        for name, cam in self.cameras.items():
            self._tap(name, cam)
        self._export()
        if self.record_dir:
            self.recorder = Recorder(self.record_dir)
            if self.scene:
                write_scene(self.record_dir, self.scene, self.blobs)
            self.recorder.save_timeline(self.meta)
        before = arm.on_tick

        def on_tick(a):
            if before:
                before(a)
            if self.hooks_on:
                try:
                    self.tick(a)
                except Exception:  # what people watch must never stop a routine
                    traceback.print_exc()
                    self.hooks_on = False
            self._pace(a)

        arm.on_tick = on_tick
        return robot

    def _export(self, arm: Any = None, hide: tuple[str, ...] = ()) -> None:
        """Reads a scratch copy, so that exporting can't touch the run's own state."""
        arm = self.arm if arm is None else arm
        if not hasattr(arm, "m"):
            return
        try:
            import mujoco

            m = arm.m
            d = mujoco.MjData(m)
            d.qpos[:] = arm.d.qpos
            mujoco.mj_kinematics(m, d)
            scene, blobs = build_scene(m, d, self.run_id, hide)
            self.moving = list(scene["moving"])
        except Exception:
            traceback.print_exc()
            return
        with self.cond:
            self.scene, self.blobs = scene, blobs
            self.cond.notify_all()

    def _tap(self, name: str, cam: Any) -> None:
        """A picture the pipeline took anyway costs only its JPEG, and only with someone watching."""
        capture = cam.capture

        def tapped(*a, **k):
            frame = capture(*a, **k)
            if self.watching.get(name):
                try:
                    self.publish_frame(name, frame.rgb)
                except Exception:
                    traceback.print_exc()
            return frame

        cam.capture = tapped

    def _preview(self, name: str, cam: Any):
        """The camera's view with its own renderer and none of its noise generators, redrawn at most PANEL_FPS times a real
        second however fast the sim runs, as these renders are what a watched run spends most on. None if it can't be drawn
        apart from a capture."""
        render = getattr(cam, "_render", None)
        if render is None:
            return None
        now = time.monotonic()
        at, img = self.views.get(name, (0.0, None))
        if img is None or now >= at:
            img = render(depth=False)[0]
            self.views[name] = (now + 1 / PANEL_FPS, img)
        return img

    def add_feed(self, name: str) -> Callable[[Any], None]:
        """A feed drawn elsewhere, as the real rig's live window: the call returned puts a BGR frame on /feed/<name>,
        and costs nothing with nobody watching."""
        if name not in self.feeds:
            self.feeds.append(name)
        return lambda img: self.publish_frame(name, img) if self.watching.get(name) else None

    def follow_real_arm(self, arm: Any, parts: Callable[[], Any], scene: Callable[[], Any]) -> None:
        """The real arm in the Console's 3D view, posed by what arm.d holds (RealArm's own loop poses it from the joint
        readings; nothing here reads the servo bus), with the last scan on /scan.json, again whenever parts() is a new
        list: a scan, System 2's names for its parts, or a flip."""
        def follow():
            shown = None
            self._export(arm, REAL_ARM_HIDDEN)
            while not self.closed.wait(1 / POSE_FPS):
                try:
                    if parts() is not shown:
                        shown = parts()
                        try:
                            if shown and getattr(scene(), "heightmap", None) is not None:
                                self.scan = scan_cloud(scene(), shown, getattr(arm, "part_shift", None))
                        except Exception:  # a scan it can't draw still leaves the arm moving
                            traceback.print_exc()
                    if self.watching.get("poses") and self.moving:
                        self._publish_pose(arm)
                except Exception:  # what people watch must never stop the robot
                    traceback.print_exc()
                    return

        threading.Thread(target=follow, name="telemetry-real-arm", daemon=True).start()

    def publish_frame(self, feed: str, img: Any) -> None:
        import cv2

        h, w = img.shape[:2]
        if w > FEED_WIDTH:
            img = cv2.resize(img, (FEED_WIDTH, round(h * FEED_WIDTH / w)), interpolation=cv2.INTER_AREA)
        jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()
        with self.cond:
            self.frames[feed] = (self.frames.get(feed, (0, b""))[0] + 1, jpeg)
            self.cond.notify_all()

    def tick(self, arm: Any) -> None:
        now = time.monotonic()
        force = float(arm.force_log[-1][1]) if arm.force_log else 0.0
        self.forces.append((float(arm.d.time), force))
        self.probe_n = force
        if self.watching.get("poses") and now >= self.next_pose:
            self.next_pose = now + 1 / POSE_FPS
            self._publish_pose(arm)
        if self.recorder is not None:
            self._record(arm, force)
        if now >= self.next_telemetry:
            self.next_telemetry = now + 1 / TELEMETRY_FPS
            self.sim_t, self.status = float(arm.d.time), str(getattr(arm, "status", "") or "")
            self.lcd = lcd_lines(getattr(arm.app, "lcd", None))
            self.publish_telemetry()
        if now >= self.next_panel and any(self.watching.get(name) for name in self.cameras):
            self.next_panel = now + 1 / PANEL_FPS
            for name, cam in self.cameras.items():
                if self.watching.get(name):
                    img = self._preview(name, cam)
                    if img is not None:
                        self.publish_frame(name, img)

    def _body(self, arm: Any) -> list[float]:
        return [float(v) for b in self.moving for v in (*arm.d.xpos[b], *arm.d.xquat[b])]

    def _publish_pose(self, arm: Any) -> None:
        line = json.dumps([round(v, 5) for v in self._body(arm)], separators=(",", ":"))
        with self.cond:
            self.poses = (self.poses[0] + 1, line)
            self.cond.notify_all()

    def _record(self, arm: Any, force: float) -> None:
        r = self.recorder
        t = float(arm.d.time)
        if r.next_at is None:
            r.next_at = t
        while t + 1e-9 >= r.next_at:
            r.next_at += 1 / RECORD_FPS
            frame = r.frames
            r.write(force, self._body(arm), lcd_lines(getattr(arm.app, "lcd", None)))
            if frame % r.CAMERA_EVERY == 0 and self.cameras:
                panels = [(name, img) for name, img in ((n, self._preview(n, c)) for n, c in self.cameras.items()) if img is not None]
                if panels:
                    r.camera_frame(panels)

    def _pace(self, arm: Any) -> None:
        """Holds sim time to `speed` seconds a second. It only waits: the physics takes the same steps at any speed."""
        speed = self.speed
        t = float(arm.d.time)
        if speed <= 0:
            self.pace_sim = None
            return
        now = time.monotonic()
        if self.pace_sim is None or now - (self.pace_wall + (t - self.pace_sim) / speed) > FALLEN_BEHIND_S:
            self.pace_sim, self.pace_wall = t, now
            return
        wait = self.pace_wall + (t - self.pace_sim) / speed - now
        if wait > 0.001:
            time.sleep(wait)

    def set_speed(self, rate: float) -> None:
        self.speed, self.pace_sim = float(rate), None

    def set_stage(self, stage: str, substage: str | None = None) -> None:
        if stage not in self.meta["stages"]:
            stage = self.stage or self.meta["stages"][0]  # the depth route folds segmenting into its MAP stage
            stage = "MAP" if substage == "segment" and "MAP" in self.meta["stages"] else stage
        if stage != self.stage and self.recorder is not None:
            self.recorder.stages.append({"name": stage, "t": self.recorder.t})
        self.stage, self.substage = stage, substage
        self.publish_telemetry()

    def _around_perceive(self, fn: Callable) -> Callable:
        def perceive(*a, **k):
            self.step = None
            self.set_stage("SURVEY", "survey")
            try:
                return fn(*a, **k)
            finally:
                self._refresh()
                self.set_stage("PLAN", None)
                self._save()
        return perceive

    def _around_execute(self, fn: Callable) -> Callable:
        def execute(step, *a, **k):
            self.step = step.id
            self.set_stage("TEST", f"{step.skill} {step.target}")
            started = self.recorder.t if self.recorder else None
            try:
                result = fn(step, *a, **k)
            except BaseException:
                self._save()
                raise
            if self.recorder is not None:
                self.recorder.steps.append({"id": step.id, "target": step.target, "t": started, "end": self.recorder.t, "status": result[1].status})
            self.step, self.substage = None, None
            self._refresh()
            self.publish_telemetry()
            self._save()
            return result
        return execute

    def _around_home(self, fn: Callable) -> Callable:
        def home(*a, **k):
            self.substage = "home"
            self.publish_telemetry()
            try:
                return fn(*a, **k)
            finally:
                self.substage = None
                self._refresh()
                self.publish_telemetry()
                self._save()
        return home

    def _refresh(self) -> None:
        """What the screen says once the arm has stopped, when no more ticks will update it."""
        if self.arm is not None:
            self.sim_t, self.status = float(self.arm.d.time), str(getattr(self.arm, "status", "") or "")
            self.lcd = lcd_lines(getattr(self.arm.app, "lcd", None))

    def _save(self) -> None:
        if self.recorder is not None:
            self.recorder.save_timeline(self.meta)

    # --- from any thread -------------------------------------------------------------------------

    def _paused(self) -> bool:
        try:
            return bool(self.status_fn) and self.status_fn().state == "paused"
        except Exception:
            return False

    def publish_telemetry(self) -> None:
        if not self.watching.get("telemetry"):
            return
        new = []
        while self.forces:
            try:
                new.append(self.forces.popleft())
            except IndexError:
                break
        force = []
        if new:
            stride = max(1, len(new) // 8)
            for i in range(0, len(new), stride):  # the peak of each slice, so a short spike isn't lost
                part = new[i:i + stride]
                force.append([round(part[-1][0], 3), round(max(f for _, f in part), 3)])
        body = {"wall": round(time.monotonic(), 2), "sim_t": round(self.sim_t, 2), "stage": self.stage, "status": self.status, "rate": self.speed, "real": self.real,
                "feeds": self.feeds, "force": force, "paused": self._paused(), "step": self.step, "substage": self.substage,
                "lcd": self.lcd, "probe_n": round(self.probe_n, 2)}
        line = json.dumps(body, separators=(",", ":"))
        with self.cond:
            self.telemetry = (self.telemetry[0] + 1, line)
            self.cond.notify_all()

    def health(self) -> dict:
        return {"ok": True, "run_id": self.run_id, "scene_ready": self.scene is not None, "meta": self.meta, "feeds": self.feeds, "rate": self.speed,
                "stage": self.stage, "step": self.step, "paused": self._paused(), "record_t": self.recorder.t if self.recorder else None}

    def _heartbeat(self) -> None:
        while not self.closed.wait(HEARTBEAT_S):  # no ticks while a routine holds at a stop, but the screen still has to say so
            self.publish_telemetry()

    def serve(self, port: int) -> int:
        """Starts the HTTP server on 127.0.0.1. Returns its port, or 0 if that port is taken: a run doesn't need it."""
        telemetry = self

        class Bound(Handler):
            tel = telemetry

        try:
            self.server = Server(("127.0.0.1", port), Bound)
        except OSError as e:
            print(f"telemetry off: can't listen on 127.0.0.1:{port} ({e})")
            return 0
        threading.Thread(target=self.server.serve_forever, name="telemetry-http", daemon=True).start()
        threading.Thread(target=self._heartbeat, name="telemetry-heartbeat", daemon=True).start()
        return self.server.server_address[1]

    def close(self) -> None:
        self.closed.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.recorder is not None:
            self.recorder.close(self.meta)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    tel: Telemetry

    def log_message(self, *a):
        pass

    def allowed(self) -> bool:
        """No Origin means it isn't a page's script: curl, an agent, or an <img>, which can't read what it shows."""
        origin = self.headers.get("Origin")
        return origin is None or origin in ORIGINS

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
        if not self.allowed():
            return self.reply(403, {"error": "origin not allowed"})
        path = self.path.split("?")[0]
        if path == "/health":
            self.reply(200, self.tel.health())
        elif path == "/scene.json":
            self.reply(200, self.tel.scene or {"run_id": None})  # polled while a run starts
        elif path.startswith("/scene/"):
            blob = self.tel.blobs.get(path.removeprefix("/scene/"))
            if not blob:
                return self.reply(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", blob[0])
            self.send_header("Content-Length", str(len(blob[1])))
            self.send_header("Access-Control-Allow-Origin", "*")  # geometry only, on 127.0.0.1
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")  # the Console asks for these by content hash
            self.end_headers()
            self.wfile.write(blob[1])
        elif path == "/scan.json":
            self.reply(200, self.tel.scan[0] if self.tel.scan else {"id": None})  # polled by the real arm's 3D view
        elif path == "/scan.bin":
            if not self.tel.scan:
                return self.reply(404, {"error": "no scan yet"})
            blob = self.tel.scan[1]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Access-Control-Allow-Origin", "*")  # geometry only, on 127.0.0.1
            self.end_headers()
            self.wfile.write(blob)
        elif path == "/poses":
            self.latest("poses", "", lambda: self.tel.poses)
        elif path == "/telemetry":
            self.latest("telemetry", "event: telemetry\n", lambda: self.tel.telemetry)
        elif path.startswith("/feed/"):
            self.feed(path.removeprefix("/feed/"))
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.headers.get("Origin") not in ORIGINS:  # only the Console's own pages can change a run's pace
            return self.reply(403, {"error": "origin not allowed"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.reply(400, {"error": "bad json"})
        if self.path.split("?")[0] != "/speed":
            return self.reply(404, {"error": "not found"})
        if body.get("rate") not in SPEEDS:
            return self.reply(400, {"error": "unknown speed"})
        self.tel.set_speed(body["rate"])
        return self.reply(200, {"ok": True})

    def _watch(self, name: str, delta: int) -> None:
        with self.tel.cond:
            self.tel.watching[name] = self.tel.watching.get(name, 0) + delta

    def latest(self, name: str, prefix: str, read: Callable[[], tuple[int, str]]) -> None:
        """Newest item only: anyone who falls behind skips ahead, so the view never lags."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.cors()
        self.end_headers()
        self.close_connection = True
        self._watch(name, 1)
        seen = 0
        try:
            while True:
                with self.tel.cond:
                    if read()[0] == seen or not read()[1]:
                        self.tel.cond.wait(5)
                    n, line = read()
                if n == seen or not line:
                    self.wfile.write(b": still here\n\n")
                else:
                    seen = n
                    self.wfile.write(f"{prefix}data: {line}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        finally:
            self._watch(name, -1)

    def feed(self, name: str) -> None:
        """Motion JPEG: an <img> plays it with no player code."""
        if name not in self.tel.feeds:
            return self.reply(404, {"error": "no such camera", "feeds": self.tel.feeds})
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self._watch(name, 1)
        seen = 0
        try:
            while True:
                with self.tel.cond:
                    n, jpeg = self.tel.frames.get(name, (0, b""))
                    if n == seen or not jpeg:
                        self.tel.cond.wait(1)
                        n, jpeg = self.tel.frames.get(name, (0, b""))
                if not jpeg:
                    continue  # nothing to show yet. An empty part would make Chromium show a broken image for good
                # with no new frame, the last one again, about once a second: it keeps the picture, and finds a viewer
                # who left
                seen = n
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return
        finally:
            self._watch(name, -1)


class Server(ThreadingHTTPServer):
    daemon_threads = True
