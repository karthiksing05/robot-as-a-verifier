"""rav-server: System 1's tool server. It waits for System 2 and starts nothing on its own.

    uv run rav-server --robot mock                 # no sim or hardware
    uv sync --extra sim
    uv run rav-server --robot sim --depth          # the sim, D405 route: no model downloads
    RAV_TOKEN=... uv run rav-server --robot sim --host 0.0.0.0     # System 2 on another laptop
    uv sync --extra sim --extra arm
    uv run rav-server --robot real --arm-port COM5 --calibration makecu.json   # asks before torque goes on
    uv run rav-server --robot real --arm-port COM5 --calibration makecu.json --readout-port COM7   # Pico verdicts
    RAV_TOKEN=... RAV_DEVICE_KEYS=... ... --readout http --readout-device mc6-01   # the board over WiFi (or Vultr)
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hmac
from ipaddress import IPv4Address
import json
import os
import re
import socket

import uvicorn

from .device_api import DeviceApi, Router
from .engine import RoutineEngine
from .mcp_server import build_server
from .telemetry import Telemetry

LOOPBACK = {"localhost", "127.0.0.1", "::1"}
DEVICE_PORT = 8782


class RequireToken:
    """Every request needs the shared token. This server can move an arm."""

    def __init__(self, app, token: str):
        self.app, self.expected = app, f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"this server needs a token"})
                return
        await self.app(scope, receive, send)


class Server(uvicorn.Server):
    """Ctrl+C during a routine's motion stops the real arm where it is and the routine at its next step, before uvicorn
    waits for open requests (a routine_wait can hold one for a minute). With the arm still (no routine, or one holding
    at a stop), it ends the routine and the real arm goes home and back to rest as the server closes (RealBackend)."""

    def __init__(self, config, engine, real=None):
        super().__init__(config)
        self.engine, self.real = engine, real

    def handle_exit(self, sig, frame):
        r = self.engine.active
        if self.real and r is not None and not r.paused:  # RealArm writes no more goals and its next send() raises
            self.real.arm.torque = False  # Torque stays on until close(), which then leaves the arm where it is
        if r is not None:
            self.engine.stop(r.id)
        super().handle_exit(sig, frame)


def make_robot(args):
    if args.robot == "mock":
        from .mock_robot import MockRobot
        return lambda: MockRobot()
    if args.robot == "real":  # built once, here on the main thread, so that main can ask before torque goes on
        from .real_backend import RealBackend
        robot = RealBackend(args.arm_port, args.calibration, refine=not args.no_refine,
                            readout_port=args.readout_port if args.readout == "serial" else None,
                            readout_device=args.readout_device if args.readout == "http" else None,
                            readout_url=readout_url(args))
        return lambda: robot
    from .sim_backend import SimBackend  # imports MuJoCo and torch

    def build():
        sim = SimBackend(seed=args.seed, sensing=args.sensing, depth=args.depth, refine=not args.no_refine, placement=args.placement,
                         faults=tuple(args.fault), fault_seed=args.fault_seed, answer_key=args.answer_key,
                         device=args.device, rev=args.rev, effector=args.effector,
                         mounts=dict(m.split("=") for m in args.mount) or None)
        if args.error_rate or args.error_schedule:
            from .unreliable import UnreliableRobot
            return UnreliableRobot(sim, args.error_rate, args.error_seed, args.error_schedule)
        return sim
    return build


def enable_torque(robot, confirmed: bool) -> None:
    """The real arm's gate: say what torque on means, then turn it on only on a yes, or with --enable-torque."""
    print(f"{robot.rig.name}: torque goes on next, and the five arm joints hold where they are. System 2 can then start "
          "routines that move the arm, and after each test motion the device's board, its Pico, or without "
          "--readout this terminal, says what changed on the device. "
          "Ctrl+C with the arm still takes it home and back to where it rests now, then turns torque off. Ctrl+C while it "
          "moves stops it where it is, then turns torque off: the arm goes limp and falls, so support it first. In an "
          "emergency, switch off the arm's power.")
    if confirmed:
        print("--enable-torque: not asking")
    elif input("Type yes to turn torque on: ").strip().lower() != "yes":
        raise SystemExit("torque stays off, so the server won't start")
    robot.enable()


def readout_url(args) -> str | None:
    if args.readout != "http":
        return None
    if args.device_host:
        return f"http://{args.device_host}:{DEVICE_PORT}/readout/{args.readout_device}"
    host = socket.gethostname() if args.host in ("0.0.0.0", "::") else args.host
    return f"http://{host}:{args.port}/readout/{args.readout_device}"


def build_app(engine: RoutineEngine, host: str, token: str | None, readouts: dict | None = None,
              device_key: str | dict[str, str] | None = None, device_port: int | None = None):
    """The MCP app behind RAV_TOKEN, and with readouts ({device: HttpReadout}) the boards' /readout/<device> beside it,
    behind RAV_DEVICE_KEY (device_api.py)."""
    if host not in LOOPBACK and not token:
        raise SystemExit(f"refusing to listen on {host} without a token: set RAV_TOKEN")
    if readouts and (host not in LOOPBACK or device_port is not None) and not device_key:
        raise SystemExit("refusing to expose device readouts without a key: set RAV_DEVICE_KEYS or RAV_DEVICE_KEY")
    keys = device_key.values() if isinstance(device_key, dict) else (device_key,) if device_key else ()
    if token and token in keys:
        raise SystemExit("RAV_DEVICE_KEY must differ from RAV_TOKEN: the boards should never hold the key that moves the arm")
    devices = DeviceApi(readouts, device_key) if readouts else None
    mcp = build_server(engine, devices)
    # Off a loopback address the token is the guard, and the SDK's host check would reject the laptop's LAN address.
    from mcp.server.transport_security import TransportSecuritySettings
    security = None if host in LOOPBACK else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(host=host, transport_security=security)
    app = RequireToken(app, token) if token else app
    return Router(devices, app, device_port) if devices else app


def bind_listener(host, port):
    try:
        return socket.create_server((host, port), family=socket.AF_INET6 if ":" in host else socket.AF_INET)
    except OSError as e:
        raise SystemExit(f"can't listen on {host}:{port}: {e}") from e


def device_keys(raw: str) -> dict[str, str]:
    try:
        keys = json.loads(raw)
    except ValueError:
        keys = None
    if not isinstance(keys, dict) or not keys or not all(
        re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) and isinstance(key, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key) for name, key in keys.items()
    ) or len(set(keys.values())) != len(keys):
        raise SystemExit("RAV_DEVICE_KEYS must be a JSON map of device IDs to distinct URL-safe keys (32–128 characters)")
    return keys


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav-server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", default="mock", choices=["mock", "sim", "real"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--seed", type=int, default=None, help="generated device (default: preset C)")
    ap.add_argument("--sensing", default=None, choices=["tactile", "loadcell", "current", "perfect"], help="default: current, the servos' own, on the stock gripper; tactile, the pad, on the probe")
    ap.add_argument("--depth", action="store_true", help="the D405 pipeline: no OWLv2 or SAM download")
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--placement", default="nominal", choices=["nominal", "random"], help="random moves the device on the desk, drawn from the seed")
    ap.add_argument("--device", default=None, metavar="PATH", help="sim only: a device file (appliances/<name>/device.yaml) in place of a generated device")
    ap.add_argument("--rev", default="B", help="with --device: its revision, or fault choices like F1=B,F2=B,F3=A")
    ap.add_argument("--effector", default="stock", choices=["stock", "probe"], help="the SO-101's own gripper, as the real arm has, or (sim only) the fingertip probe, kept as a reference")
    ap.add_argument("--mount", action="append", default=[], metavar="ROOT=clamped|free", help="with --device: override how a root is held to the bench. Repeatable")
    ap.add_argument("--fault", action="append", default=[], metavar="NAME[:PART]", help="sim only: plant a fault, or 'random'. Repeatable. See sim/faults.py")
    ap.add_argument("--fault-seed", type=int, default=None, help="for --fault random (default: --seed)")
    ap.add_argument("--answer-key", default=None, metavar="PATH", help="sim only: write the device's truth, faults and injected errors here, for scoring. No tool can read it")
    ap.add_argument("--error-rate", type=float, default=0.0, help="sim only: the chance per action that the world misbehaves. See rav_server/unreliable.py")
    ap.add_argument("--error-seed", type=int, default=0)
    ap.add_argument("--error-schedule", default=None, metavar="WHEN:KIND,...", help="sim only: force errors. WHEN is an action number, or a control id for its first attempt")
    ap.add_argument("--telemetry-port", type=int, default=8781, help="what the Console watches, on 127.0.0.1. 0: off")
    ap.add_argument("--speed", type=float, default=0, help="sim seconds per second, to watch a run. 0: as fast as the sim goes")
    ap.add_argument("--record-dir", default=None, help="write poses.bin, scene/, cameras.mp4 and timeline.json here, so the run replays")
    ap.add_argument("--run-id", default=None, help="the scene's run id, which the Console matches. Default: --record-dir's name")
    ap.add_argument("--arm-port", help="real: the servo bus's serial port, such as COM5")
    ap.add_argument("--calibration", help="real: the file lerobot-calibrate wrote for the arm")
    ap.add_argument("--enable-torque", action="store_true", help="real: turn torque on at startup without asking")
    ap.add_argument("--readout", default="operator", choices=["operator", "serial", "http"],
                    help="real: where verdicts read the device: the operator at this terminal, the appliance's Pico on "
                         "--readout-port, or a board POSTing to /readout/<--readout-device> over WiFi (RAV_DEVICE_KEY)")
    ap.add_argument("--readout-port", help="real: the Pico's serial port, such as COM7 (implies --readout serial)")
    ap.add_argument("--readout-device", help="real, --readout http: the board's name in its URL, such as mw1")
    ap.add_argument("--device-host", help=f"System 1's hotspot IPv4 address for the appliance listener on port {DEVICE_PORT}")
    args = ap.parse_args(argv)
    if args.readout_port and args.readout == "operator":  # --readout-port alone, as before --readout
        args.readout = "serial"
    token = os.environ.get("RAV_TOKEN")
    keys = device_keys(raw) if (raw := os.environ.get("RAV_DEVICE_KEYS")) is not None else None
    if keys is not None and (not token or token in keys.values() or (args.readout_device and args.readout_device not in keys)):
        ap.error("RAV_DEVICE_KEYS requires a separate RAV_TOKEN and a key for --readout-device")
    if args.device_host:
        try:
            address = IPv4Address(args.device_host)
        except ValueError:
            ap.error("--device-host requires a hotspot IPv4 address")
        if not address.is_private or address.is_unspecified or address.is_reserved:
            ap.error("--device-host requires a specific private IPv4 address")
        if not keys or args.host not in LOOPBACK or args.port == DEVICE_PORT:
            ap.error("--device-host requires RAV_DEVICE_KEYS, loopback MCP and an MCP port other than 8782")
    if args.robot == "real" and (args.depth or not (args.arm_port and args.calibration)):
        ap.error("--robot real needs --arm-port and --calibration, and has no depth camera for --depth")
    if args.readout != "operator" and args.robot != "real":
        ap.error("--readout is for --robot real")
    if (args.readout == "serial") != bool(args.readout_port) or (args.readout == "http") != bool(args.readout_device):
        ap.error("--readout serial takes --readout-port, and --readout http takes --readout-device")
    if args.readout_device and not all(c.isalnum() or c in "-_" for c in args.readout_device):
        ap.error("--readout-device is letters, digits, - and _: it goes in the URL")
    if args.robot != "sim" and (args.fault or args.answer_key or args.error_rate or args.error_schedule or args.placement != "nominal"
                                or args.device or args.mount or args.effector != "stock"):
        ap.error("--fault, --placement, --answer-key, --device, --mount, --effector probe and --error-* are for --robot sim only: they must never reach a real arm")
    if args.device and args.fault:
        ap.error("a device file's faults are its revision's parts: use --rev, not --fault")
    if any(m.count("=") != 1 or m.split("=")[1] not in ("clamped", "free") for m in args.mount):
        ap.error("--mount is ROOT=clamped or ROOT=free")
    if not 0 <= args.error_rate <= 1:
        ap.error("--error-rate is a chance, between 0 and 1")
    telemetry = Telemetry(args.speed, args.record_dir, args.run_id)
    make = make_robot(args)
    real = make() if args.robot == "real" else None  # the backend make_robot built, torque still off
    engine = RoutineEngine(lambda: telemetry.instrument(make()), robot_name=args.robot)
    telemetry.status_fn = engine.status
    try:
        readouts = {args.readout_device: real.http_readout} if real and real.http_readout else {}
        if keys:
            from .sim_backend import CORE_DIR, HARDWARE_DIR, on_path
            on_path(CORE_DIR, HARDWARE_DIR)
            from http_readout import HttpReadout
            for name in keys.keys() - readouts.keys():
                readouts[name] = HttpReadout(name, track_events=False)
        app = build_app(engine, args.host, token, readouts, keys or os.environ.get("RAV_DEVICE_KEY"),
                        DEVICE_PORT if args.device_host else None)
        with ExitStack() as listeners:  # bind both before enabling torque
            sockets = [listeners.enter_context(bind_listener(args.host, args.port))]
            if args.device_host:
                sockets.append(listeners.enter_context(bind_listener(args.device_host, DEVICE_PORT)))
                print(f"Appliances POST to http://{args.device_host}:{DEVICE_PORT}/readout/<device-id>")
            print(f"System 1 server source: {__file__}", flush=True)
            if readouts:
                print(f"MCP appliance_readout enabled for: {', '.join(sorted(readouts))}", flush=True)
                if not keys:
                    print("Vultr appliance publishing requires RAV_DEVICE_KEYS in this server's environment.", flush=True)
            if real:
                enable_torque(real, args.enable_torque)
            watching = telemetry.serve(args.telemetry_port) if args.telemetry_port else 0
            print(f"System 1 ({args.robot}) waiting on http://{args.host}:{args.port}/mcp" + (f", telemetry on http://127.0.0.1:{watching}" if watching else ""))
            if args.readout_device:
                print(f"device readout: {args.readout_device} POSTs to {readout_url(args)}. No step runs until it does")
            Server(uvicorn.Config(app, log_level="warning"), engine, real).run(sockets=sockets)
    finally:
        try:
            engine.shutdown()  # the worker closes the robot once the routine stops
        finally:
            try:
                if real:
                    real.close()  # torque off even if no routine ran, the worker is stuck, or Ctrl+C cut the wait short
            finally:
                telemetry.close()


if __name__ == "__main__":
    main()
