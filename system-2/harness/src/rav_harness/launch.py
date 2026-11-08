"""Starts System 1's server for one device, as its own process. It gets no model keys, and it's restarted per device."""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import re
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field

from .client import CantReachSystem1, McpSystem1
from .model import REPO

SYSTEM_1 = REPO / "system-1"
SECRETS = ("_KEY", "_TOKEN", "_PAT", "_SECRET")  # by ending: PATH must get through. RAV_TOKEN is System 1's own, and stays
READY_S = 180.0
EFFECTORS = ("stock", "probe")  # the SO-101's own gripper (the real arm's only effector), or the sim-only fingertip probe
REV = re.compile(r"^[A-Za-z0-9]+$|^(F[0-9]+=[A-Za-z0-9]+)(,F[0-9]+=[A-Za-z0-9]+)*$")  # a revision, or fault choices like F1=B,F2=A


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if (k in ("PATH", "RAV_TOKEN") or not any(k.upper().endswith(word) for word in SECRETS)) and k != "VIRTUAL_ENV"}
    return env


@dataclass
class Device:
    """What to run on. `robot: mock` is the scripted robot, for tests."""
    robot: str = "sim"
    seed: int | None = None
    path: str | None = None
    rev: str | None = None
    faults: list[str] = field(default_factory=list)
    placement: str | None = None
    route: str = "rgb"  # the wrist camera, OWLv2 and SAM, as the real rig: it has no global camera for the depth route
    error_rate: float = 0.0
    error_seed: int = 0
    error_schedule: str | None = None
    fault_seed: int | None = None  # which fault `random` picks. System 1 uses the device seed when it's unset
    speed: float = 0.0
    effector: str = "stock"

    @classmethod
    def from_request(cls, body: dict) -> Device:
        device = dict(body.get("device") or {})
        fault = device.pop("fault", None)
        preset = device.pop("preset", None)
        if preset not in (None, "C"):
            raise ValueError(f"no preset {preset}")
        rev, revs = device.pop("rev", None), device.pop("revs", None)
        if rev is not None and (not isinstance(rev, str) or not REV.match(rev) or (revs and rev not in revs and "=" not in rev)):
            raise ValueError(f"no revision {rev}" + (f": this device has {', '.join(revs)}" if revs else ""))
        effector = device.pop("effector", None) or "stock"
        if effector not in EFFECTORS:
            raise ValueError(f"no effector {effector}: it's {' or '.join(EFFECTORS)}")
        faults = fault if isinstance(fault, list) else [fault] if fault else []
        return cls(robot=device.pop("robot", "sim"), seed=device.pop("seed", None), path=device.pop("path", None), rev=rev,
                   faults=faults, placement=device.pop("placement", None), route=device.pop("route", body.get("route", "rgb")),
                   error_rate=float(body.get("error_rate") or 0), error_seed=int(body.get("error_seed") or 0), error_schedule=body.get("error_schedule"),
                   fault_seed=device.pop("fault_seed", None),
                   speed=float(body.get("speed") or 0), effector=effector)


def server_command(device: Device, port: int, telemetry_port: int, key: pathlib.Path | None, record: pathlib.Path | None, run_id: str | None) -> list[str]:
    extra = [] if device.robot == "mock" else ["--extra", "sim"]
    cmd = ["uv", "run", "--project", str(SYSTEM_1), *extra, "rav-server", "--robot", device.robot, "--port", str(port), "--telemetry-port", str(telemetry_port)]
    if device.robot == "mock":
        return cmd
    if device.route == "depth":
        cmd.append("--depth")
    if device.seed is not None:
        cmd += ["--seed", str(device.seed)]
    if device.path:  # a project names its device file from the repo root, and the server runs in system-1
        cmd += ["--device", str(device.path if pathlib.Path(device.path).is_absolute() else REPO / device.path)]
    if device.rev:
        cmd += ["--rev", device.rev]
    cmd += ["--effector", device.effector]
    for fault in device.faults:
        cmd += ["--fault", fault]
    if device.faults and device.fault_seed is not None:
        cmd += ["--fault-seed", str(device.fault_seed)]
    if device.placement:
        cmd += ["--placement", device.placement]
    if device.error_rate:
        cmd += ["--error-rate", str(device.error_rate), "--error-seed", str(device.error_seed)]
    if device.error_schedule:
        cmd += ["--error-schedule", device.error_schedule]
    if key:
        cmd += ["--answer-key", str(key)]
    if device.speed:
        cmd += ["--speed", str(device.speed)]
    if record:
        cmd += ["--record-dir", str(record)]
        if run_id:
            cmd += ["--run-id", run_id]
    return cmd


# Every server this process starts, so none outlives it: on exit, on a signal, and, after a crash, at the next start.
LIVE: set["System1Process"] = set()
REGISTRY = pathlib.Path(os.environ.get("RAV_SERVER_REGISTRY") or SYSTEM_1.parent / "system-2" / "runs" / ".servers.json")


def _registered() -> dict[str, dict]:
    try:
        return json.loads(REGISTRY.read_text())
    except (OSError, ValueError):
        return {}


def _register(pgid: int, info: dict | None) -> None:
    rows = _registered()
    if info is None:
        rows.pop(str(pgid), None)
    else:
        rows[str(pgid)] = info
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    temp = REGISTRY.with_suffix(".tmp")
    temp.write_text(json.dumps(rows))
    temp.replace(REGISTRY)


def _is_our_server(pgid: int) -> bool:
    try:
        out = subprocess.run(["ps", "-o", "command=", "-g", str(pgid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "rav-server" in out


def reap_stale_servers() -> list[str]:
    """Servers a crashed run left behind, by the process group each was started in. Only ones that are still rav-server."""
    said = []
    for pgid, info in _registered().items():
        if _is_our_server(int(pgid)):
            try:
                os.killpg(int(pgid), signal.SIGTERM)
                said.append(f"stopped a rav-server left from an earlier run: {info.get('run_id')} on port {info.get('port')}")
            except OSError:
                pass
        _register(int(pgid), None)
    return said


def stop_all() -> None:
    for process in list(LIVE):
        process.stop()


def stop_servers_on_exit() -> None:
    """SIGINT, SIGTERM or a normal exit takes every server down too. An uncaught crash goes through atexit."""
    atexit.register(stop_all)

    def on_signal(signum, frame):
        stop_all()
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, on_signal)


class System1Process:
    """rav-server for one device. A context manager that always takes the process down with it."""

    def __init__(self, device: Device, folder: pathlib.Path, run_id: str | None = None, port: int | None = None, telemetry_port: int | None = None,
                 record: bool = False):
        self.device, self.folder = device, pathlib.Path(folder).resolve()
        self.port, self.telemetry_port = port or free_port(), telemetry_port if telemetry_port is not None else free_port()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.key = None if device.robot == "mock" else self.folder / "answer_key.json"
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self.telemetry_url = f"http://127.0.0.1:{self.telemetry_port}" if self.telemetry_port else None
        self.cmd = server_command(device, self.port, self.telemetry_port, self.key, self.folder if record else None, run_id)
        self.process: subprocess.Popen | None = None

    def start(self) -> McpSystem1:
        log = (self.folder / "system1.log").open("w")
        self.process = subprocess.Popen(self.cmd, cwd=SYSTEM_1, env=_env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        LIVE.add(self)
        _register(self.process.pid, {"port": self.port, "telemetry_port": self.telemetry_port, "run_id": self.folder.name})
        deadline = time.monotonic() + READY_S
        while True:
            if self.process.poll() is not None:
                raise CantReachSystem1(f"rav-server exited with {self.process.returncode}: see {self.folder / 'system1.log'}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return McpSystem1(self.url)
            except OSError:
                if time.monotonic() > deadline:
                    self.stop()
                    raise CantReachSystem1(f"rav-server didn't start in {READY_S:.0f} s: see {self.folder / 'system1.log'}") from None
                time.sleep(0.5)

    def stop(self) -> None:
        LIVE.discard(self)
        if not self.process:
            return
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)  # the whole group: uv and the server under it
                self.process.wait(30)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(5)
            except ProcessLookupError:
                pass
        _register(self.process.pid, None)
