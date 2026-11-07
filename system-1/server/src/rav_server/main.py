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
    return lambda: SimBackend(seed=args.seed, sensing=args.sensing, depth=args.depth, refine=not args.no_refine)


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
    ap.add_argument("--sensing", default="tactile", choices=["tactile", "loadcell", "current", "perfect"])
    ap.add_argument("--depth", action="store_true", help="the D405 pipeline: no OWLv2 or SAM download")
    ap.add_argument("--no-refine", action="store_true")
    args = ap.parse_args(argv)
    engine = RoutineEngine(make_robot(args), robot_name=args.robot)
    app = build_app(engine, args.host, os.environ.get("RAV_TOKEN"))
    print(f"System 1 ({args.robot}) waiting on http://{args.host}:{args.port}/mcp")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
