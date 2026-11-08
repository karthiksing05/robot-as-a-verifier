"""rav-agent: System 2 as a service. The Console starts a run here, watches it and steers it. System 1 is a separate process,
started per device, and its telemetry (poses and cameras) goes straight to the Console.

    GET  /health    {ok, running, project, run_id, model, models}
    GET  /events    server-sent: reset, meta, run (a RunEvent), delta (reasoning as it's written; not stored)
    POST /start     {project, device: {seed | preset | path, rev, effector, fault, placement, route}, model, max_turns, error_rate, error_seed,
                     auto_approve}. A project's sim (its device file, revisions and manual) fills in what the device leaves out
    POST /steer     a SteerCommand
    POST /approve   {kind, ref, by, ok}

Local only: it binds to 127.0.0.1 and takes commands only from the Console's own origins.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import queue
import threading
import time
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from rav_contracts import RunEvent, SteerCommand, TestRequest

from .agent import AgentConfig, run_agent, sim_auto_approve
from .client import McpSystem1
from .launch import Device, System1Process, reap_stale_servers, stop_servers_on_exit
from .loop import Steering, run_test, auto_approve, robot_may_auto_approve
from .manual import Manual
from .model import DEFAULT_MODEL, MODELS, LedgeredClient, REPO, ModelError, default_fallback, make_client
from .runlog import RunLog, read_events
from .survey import part_namer

SYSTEM_2 = REPO / "system-2"
ORIGINS = {f"http://{h}:{p}" for h in ("127.0.0.1", "localhost") for p in (5173, 5174)}  # 5174: Vite's next port when 5173 is taken
STAGES = ["MAP", "PLAN", "TEST", "REPORT"]
RUN_ID_SAFE = str.maketrans({c: "-" for c in " /\\:"})
ASK_TIMEOUT_S = 300.0


def project_of(project_id: str | None, subjects: pathlib.Path = SYSTEM_2 / "subjects") -> dict:
    if not project_id:
        return {}
    path = subjects / project_id / "project.json"
    if ".." in project_id or "/" in project_id or not path.is_file():
        raise ValueError(f"no project {project_id}")
    return json.loads(path.read_text())


def manual_of(project: dict, subjects: pathlib.Path = SYSTEM_2 / "subjects") -> Manual | None:
    if project.get("manual"):
        path = (REPO / project["manual"]).resolve()
        return Manual(path) if path.is_file() else None
    folder = subjects / str(project.get("id")) / "manual"
    if folder.is_dir():
        for suffix in (".pdf", ".md", ".txt"):
            for path in sorted(folder.glob(f"*{suffix}")):
                return Manual(path)
    return None


def config_for(body: dict, config: AgentConfig | None) -> AgentConfig:
    """A run can ask for fewer turns than the service allows, never more."""
    config = config or AgentConfig()
    asked = body.get("max_turns")
    if asked in (None, ""):
        return config
    if isinstance(asked, bool) or not isinstance(asked, int | float) or asked != int(asked) or asked < 1:
        raise ValueError(f"max_turns is a whole number of turns, at least 1, not {asked!r}")
    return dataclasses.replace(config, max_turns=min(int(asked), config.max_turns))


def available_models() -> list[str]:
    return list(MODELS)


def at_recording_time(wall: float, anchors: list[list[float]]) -> float:
    """Seconds into the recording for a wall-clock time, between the anchors the recorder wrote."""
    if not anchors:
        return 0.0
    if wall <= anchors[0][0]:
        return anchors[0][1]
    for (w0, t0), (w1, t1) in zip(anchors, anchors[1:]):
        if wall <= w1:
            return t0 + (t1 - t0) * (wall - w0) / (w1 - w0) if w1 > w0 else t1
    return anchors[-1][1]


def merge_timeline(log: RunLog, product: str) -> None:
    """The recorder's timeline starts with no events: this run's log owns them. Fills in when each one happens in the video."""
    path = log.dir / "timeline.json"
    if not path.is_file():
        return
    timeline = json.loads(path.read_text())
    anchors = timeline.get("anchors") or []
    timeline["events"] = {str(e.seq): round(at_recording_time(log.wall0 + e.t, anchors), 3) for e in read_events(log.path)}
    timeline.setdefault("meta", {})["product"] = product
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(timeline))
    temp.replace(path)


class NotLive(Exception):
    pass


class Hub:
    """Everything the Console hears. A new listener gets the run so far, then each thing as it happens."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.history: list[tuple[str, str]] = []
        self.listeners: list[queue.Queue] = []
        self.running = False
        self.project: str | None = None
        self.run_id: str | None = None
        self.model: str | None = None
        self.steering = Steering()
        self.approvals: dict[tuple[str, str], dict | None] = {}
        self.approved = threading.Condition(self.lock)
        self.system1 = None  # the live run's System 1, for /evidence

    def evidence(self, ref: str) -> dict:
        """A step's trace, or a frame with its image, from the live run's System 1."""
        system1 = self.system1
        if system1 is None:
            raise NotLive("no run is live, so there's no evidence to fetch: a finished run's traces are in its events")
        if ref.startswith("frame:"):
            return {"frame": system1.evidence_frame(ref).model_dump(mode="json")}
        return {"trace": system1.evidence_get(ref).model_dump(mode="json")}

    def publish(self, name: str, body: dict, keep: bool = True) -> None:
        line = json.dumps(body, default=str)
        with self.lock:
            if keep:
                self.history.append((name, line))
            for listener in self.listeners:
                listener.put((name, line))

    def reset(self) -> None:
        with self.lock:
            self.history, self.approvals = [], {}
            for listener in self.listeners:
                listener.put(("reset", "{}"))

    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            q.put(("reset", "{}"))
            for item in self.history:
                q.put(item)
            self.listeners.append(q)
        return q

    def forget(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def person_approves(self, kind: str, ref: str) -> str | None:
        """Waits for POST /approve, however long that takes. Nobody can approve what they haven't been shown."""
        with self.approved:
            self.approvals[(kind, ref)] = None
            while self.approvals.get((kind, ref)) is None:
                if any(c.kind == "stop" for c in self.steering.commands):
                    return None
                self.approved.wait(1.0)
            answer = self.approvals.pop((kind, ref))
        return answer["by"] if answer.get("ok", True) else None

    def answer(self, kind: str, ref: str, by: str, ok: bool) -> bool:
        with self.approved:
            if (kind, ref) not in self.approvals:
                return False
            self.approvals[(kind, ref)] = {"by": by, "ok": ok}
            self.approved.notify_all()
            return True

    def operator_answers(self, question: str) -> str | None:
        deadline = time.monotonic() + ASK_TIMEOUT_S
        while time.monotonic() < deadline:
            for c in list(self.steering.commands):
                if c.kind == "stop":
                    return None
                if c.kind == "message":
                    self.steering.commands.remove(c)
                    return c.text
            time.sleep(0.2)
        return None


@dataclasses.dataclass
class Attached:
    """A System 1 someone already started, such as the real arm's. Runs use it as it is and never stop it."""
    url: str
    telemetry: str | None = None
    reuse_scan: bool = False  # start each run from the scene it holds


def run_once(hub: Hub, body: dict, runs_root: pathlib.Path, make=make_client, config: AgentConfig | None = None, attach: Attached | None = None) -> None:
    project = project_of(body.get("project"))
    device_body = {**(project.get("sim") or {}), **(body.get("device") or {})}
    device = Device.from_request({**body, "device": device_body})
    device.speed = device.speed or 1.0  # a run someone is watching goes at sim speed; evals go as fast as they can
    config = config_for(body, config)
    model = body.get("model") or DEFAULT_MODEL
    name = project.get("id") or ("mock" if device.robot == "mock" else f"seed-{device.seed}" if device.seed is not None else "preset-C")
    run_id = f"agent-{name}-{time.strftime('%H%M%S')}".translate(RUN_ID_SAFE)
    hub.run_id, hub.model = run_id, model
    log = RunLog(run_id, runs_root, on_event=lambda e: hub.publish("run", e.model_dump(mode="json")))
    process = None if attach else System1Process(device, log.dir, run_id, record=device.robot != "mock")
    product = (project.get("name") if attach else None) or project.get("products", [None])[0] or project.get("name") or "Device under test"
    hub.publish("meta", {"run_id": run_id, "product": product, "stages": STAGES, "route": device.route, "model": model, "project": project.get("id"),
                         "telemetry": attach.telemetry if attach else process.telemetry_url})
    # The request holds what the record needs. Anything planted stays in the answer key, so it can't reach a prompt.
    request = TestRequest(request_id=run_id, product=product, project=project.get("id"), instruction=project.get("instruction") or TestRequest.model_fields["instruction"].default,
                          revision=device.rev or "A")
    system1 = None
    try:
        system1 = McpSystem1(attach.url) if attach else process.start()
        hub.system1 = system1
        real = not robot_may_auto_approve(system1.system_status().robot)
        if real:  # as rav agent on a real arm: the operator's answers are the readout, so there's nothing to check back on
            config = dataclasses.replace(config, check_back=False)
        auto = bool(body.get("auto_approve"))
        if model == "rules":
            run_test(system1, request, log, approve=auto_approve if auto else hub.person_approves, steering=hub.steering, wait=lambda: time.sleep(0.2))
            return
        fallback = body.get("fallback") or default_fallback(model)
        if fallback not in (None, *MODELS):
            raise ValueError(f"{fallback} isn't one of the compared models")

        def on_delta(delta: dict) -> None:
            hub.publish("delta", delta, keep=False)
        client = LedgeredClient(make(model, fallback=fallback, **({"effort": body["effort"]} if body.get("effort") else {}),
                                     on_switch=lambda gone, why: log.emit("message", {"role": "harness", "text": f"switching model: {gone}: {why}"})), None, run_id)
        manual = manual_of(project)
        run_agent(system1, request, log, client, approve=sim_auto_approve if auto else hub.person_approves, steering=hub.steering,
                  wait=lambda: time.sleep(0.2), config=config, manual=manual, ask=None if auto else hub.operator_answers, on_delta=on_delta,
                  review=part_namer(system1, log, manual) if real and manual else None, reuse_scan=bool(attach and attach.reuse_scan))
    except Exception as e:  # noqa: BLE001 - shown on the run, whatever it was
        traceback.print_exc()
        log.emit("message", {"role": "harness", "text": f"the run failed: {type(e).__name__}: {e}"})
        log.emit("run_finished", {"status": "aborted"})
    finally:
        hub.system1 = None
        if system1 is not None:
            try:
                system1.close()
            except Exception:  # noqa: BLE001, S110 - it's on its way down anyway
                pass
        if process:
            process.stop()  # SIGTERM, so the recorder finishes cameras.mp4 and timeline.json
        merge_timeline(log, product)


def build_handler(hub: Hub, start: Callable[[dict], str | None]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

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
            if path == "/evidence":
                if self.headers.get("Origin") not in ORIGINS:  # it carries camera frames: the Console's only
                    return self.reply(403, {"error": "only the Console can fetch evidence"})
                ref = (parse_qs(urlsplit(self.path).query).get("ref") or [""])[0]
                if not ref:
                    return self.reply(400, {"error": "say which: /evidence?ref=..."})
                try:
                    return self.reply(200, hub.evidence(ref))
                except NotLive as e:
                    return self.reply(409, {"error": str(e)})
                except Exception as e:  # noqa: BLE001 - System 1 said no: pass on what it said
                    return self.reply(404, {"error": f"{ref} isn't available: {e}"})
            if path == "/health":
                self.reply(200, {"ok": True, "running": hub.running, "project": hub.project if hub.running else None, "run_id": hub.run_id,
                                 "model": hub.model, "models": available_models()})
            elif path == "/events":
                self.events()
            else:
                self.reply(404, {"error": "no such path"})

        def events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.cors()
            self.end_headers()
            self.close_connection = True
            q = hub.listen()
            try:
                while True:
                    try:
                        name, line = q.get(timeout=10)
                        self.wfile.write(f"event: {name}\ndata: {line}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                hub.forget(q)

        def do_POST(self):
            if self.headers.get("Origin") not in ORIGINS:
                return self.reply(403, {"error": "only the Console can send commands"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self.reply(400, {"error": "that isn't JSON"})
            path = self.path.split("?")[0]
            if path == "/start":
                problem = start(body)
                return self.reply(409 if problem else 200, {"error": problem} if problem else {"ok": True})
            if path == "/steer":
                if not hub.running:
                    return self.reply(409, {"error": "no run to steer"})
                try:
                    hub.steering.send(SteerCommand(**body))
                except (ValidationError, TypeError) as e:
                    return self.reply(400, {"error": str(e)})
                return self.reply(200, {"ok": True})
            if path == "/approve":
                ok = hub.answer(str(body.get("kind")), str(body.get("ref")), str(body.get("by") or "operator"), bool(body.get("ok", True)))
                return self.reply(200 if ok else 409, {"ok": ok} if ok else {"error": "nothing is waiting for that approval"})
            return self.reply(404, {"error": "no such path"})

    return Handler


class Service:
    def __init__(self, runs_root: str | pathlib.Path = SYSTEM_2 / "runs", port: int = 8790, make=make_client, config: AgentConfig | None = None,
                 attach: Attached | None = None):
        self.hub, self.runs_root, self.make, self.config, self.attach = Hub(), pathlib.Path(runs_root), make, config, attach
        self.server = ThreadingHTTPServer(("127.0.0.1", port), build_handler(self.hub, self.start))
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]

    def start(self, body: dict) -> str | None:
        hub = self.hub
        with hub.lock:
            if hub.running:
                return "a run is already going"
            hub.running = True
        hub.project = body.get("project")
        hub.steering = Steering()
        hub.reset()

        def work() -> None:
            try:
                run_once(hub, body, self.runs_root, self.make, self.config, self.attach)
            except (ValueError, ModelError) as e:
                hub.publish("run", RunEvent(seq=0, t=0, run_id=hub.run_id or "", type="message",
                                            payload={"role": "harness", "text": str(e)}).model_dump(mode="json"))
            finally:
                hub.running = False
        threading.Thread(target=work, name="agent-run", daemon=True).start()
        return None

    def serve(self) -> None:
        self.server.serve_forever()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav-agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--runs", default=str(SYSTEM_2 / "runs"), help="where run folders go")
    args = ap.parse_args(argv)
    for line in reap_stale_servers():
        print(line)
    try:
        service = Service(args.runs, args.port)
    except OSError as e:
        raise SystemExit(f"port {args.port} is taken ({e}). See what holds it: lsof -iTCP:{args.port} -sTCP:LISTEN") from None
    stop_servers_on_exit()
    print(f"RAAV agent service on http://127.0.0.1:{service.port}")
    try:
        service.serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
