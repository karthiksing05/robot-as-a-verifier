"""rav-server: System 1's tool server. It waits for System 2 and starts nothing on its own.

    uv run rav-server --robot mock                 # no sim or hardware
    uv sync --extra sim
    uv run rav-server --robot sim --depth          # the sim, D405 route: no model downloads
    RAV_TOKEN=... uv run rav-server --robot sim --host 0.0.0.0     # System 2 on another laptop
    uv sync --extra sim --extra arm
    uv run rav-server --robot real --arm-port COM5 --calibration makecu.json   # asks before torque goes on
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import os
import socket

import uvicorn

from .engine import RoutineEngine
from .mcp_server import build_server

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


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
    """Ctrl+C stops the real arm where it is and the routine at its next step, before uvicorn waits for open requests (a
    routine_wait can hold one for a minute)."""

    def __init__(self, config, engine, real=None):
        super().__init__(config)
        self.engine, self.real = engine, real

    def handle_exit(self, sig, frame):
        if self.real:  # RealArm writes no more goals and its next send() raises. Torque stays on until close()
            self.real.arm.torque = False
        if (r := self.engine.active) is not None:
            self.engine.stop(r.id)
        super().handle_exit(sig, frame)


def make_robot(args):
    if args.robot == "mock":
        from .mock_robot import MockRobot
        return lambda: MockRobot()
    if args.robot == "real":  # built once, here on the main thread, so that main can ask before torque goes on
        from .real_backend import RealBackend
        robot = RealBackend(args.arm_port, args.calibration, refine=not args.no_refine)
        return lambda: robot
    from .sim_backend import SimBackend  # imports MuJoCo and torch
    return lambda: SimBackend(seed=args.seed, sensing=args.sensing, depth=args.depth, refine=not args.no_refine)


def enable_torque(robot, confirmed: bool) -> None:
    """The real arm's gate: say what torque on means, then turn it on only on a yes, or with --enable-torque."""
    print(f"{robot.rig.name}: torque goes on next, and the five arm joints hold where they are. System 2 can then start "
          "routines that move the arm, and after each test motion this terminal asks what changed on the device. "
          "Ctrl+C stops the arm where it is, then turns torque off as the server stops: the arm goes limp and falls, "
          "so support it first. In an emergency, switch off the arm's power.")
    if confirmed:
        print("--enable-torque: not asking")
    elif input("Type yes to turn torque on: ").strip().lower() != "yes":
        raise SystemExit("torque stays off, so the server won't start")
    robot.arm.enable(confirm=True)


def build_app(engine: RoutineEngine, host: str, token: str | None):
    if host not in LOOPBACK and not token:
        raise SystemExit(f"refusing to listen on {host} without a token: set RAV_TOKEN")
    mcp = build_server(engine)
    # Off a loopback address the token is the guard, and the SDK's host check would reject the laptop's LAN address.
    from mcp.server.transport_security import TransportSecuritySettings
    security = None if host in LOOPBACK else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(host=host, transport_security=security)
    return RequireToken(app, token) if token else app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="rav-server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", default="mock", choices=["mock", "sim", "real"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--seed", type=int, default=None, help="generated device (default: preset C)")
    ap.add_argument("--sensing", default="tactile", choices=["tactile", "loadcell", "current", "perfect"])
    ap.add_argument("--depth", action="store_true", help="the D405 pipeline: no OWLv2 or SAM download")
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--arm-port", help="real: the servo bus's serial port, such as COM5")
    ap.add_argument("--calibration", help="real: the file lerobot-calibrate wrote for the arm")
    ap.add_argument("--enable-torque", action="store_true", help="real: turn torque on at startup without asking")
    args = ap.parse_args(argv)
    if args.robot == "real" and (args.depth or not (args.arm_port and args.calibration)):
        ap.error("--robot real needs --arm-port and --calibration, and has no depth camera for --depth")
    make = make_robot(args)
    real = make() if args.robot == "real" else None  # the backend make_robot built, torque still off
    engine = RoutineEngine(make, robot_name=args.robot)
    try:
        app = build_app(engine, args.host, os.environ.get("RAV_TOKEN"))
        try:  # before torque: a port in use would otherwise stop the server, and drop the arm, right after the yes
            sock = socket.create_server((args.host, args.port), family=socket.AF_INET6 if ":" in args.host else socket.AF_INET)
        except OSError as e:
            raise SystemExit(f"can't listen on {args.host}:{args.port}: {e}")
        if real:
            enable_torque(real, args.enable_torque)
        print(f"System 1 ({args.robot}) waiting on http://{args.host}:{args.port}/mcp")
        Server(uvicorn.Config(app, log_level="warning"), engine, real).run(sockets=[sock])
    finally:
        try:
            engine.shutdown()  # the worker closes the robot once the routine stops
        finally:
            if real:
                real.close()  # torque off even if no routine ran, the worker is stuck, or Ctrl+C cut the wait short


if __name__ == "__main__":
    main()
