"""rav-server: System 1's tool server. It waits for System 2 and starts nothing on its own.

    uv run rav-server --robot mock                 # no sim or hardware
    uv sync --extra sim
    uv run rav-server --robot sim --depth          # the sim, D405 route: no model downloads
    RAV_TOKEN=... uv run rav-server --robot sim --host 0.0.0.0     # System 2 on another laptop
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import os

import uvicorn

from .engine import RoutineEngine
from .mcp_server import build_server
from .telemetry import Telemetry

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


def make_robot(args):
    if args.robot == "mock":
        from .mock_robot import MockRobot
        return lambda: MockRobot()
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
    ap.add_argument("--robot", default="mock", choices=["mock", "sim"])
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
    args = ap.parse_args(argv)
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
    build = make_robot(args)
    engine = RoutineEngine(lambda: telemetry.instrument(build()), robot_name=args.robot)
    telemetry.status_fn = engine.status
    watching = telemetry.serve(args.telemetry_port) if args.telemetry_port else 0
    app = build_app(engine, args.host, os.environ.get("RAV_TOKEN"))
    print(f"System 1 ({args.robot}) waiting on http://{args.host}:{args.port}/mcp" + (f", telemetry on http://127.0.0.1:{watching}" if watching else ""))
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
