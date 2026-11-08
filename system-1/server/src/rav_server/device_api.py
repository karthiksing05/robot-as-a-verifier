"""The appliance boards' way in over WiFi: each POSTs its snapshot, the same JSON object the Pico prints over USB, to
/readout/<device>, and the server hands it to that device's http_readout.HttpReadout.

    POST /readout/mw1   Authorization: Bearer <RAV_DEVICE_KEY>   {"BTN1": 0, "DOOR": 1, "LCD": "READY"}   -> 204
    GET  /readout/mw1   Authorization: Bearer <RAV_DEVICE_KEY>   -> {"readings": {...}, "lcd": ..., "age_s": 0.3}

With RAV_DEVICE_KEYS each board's key is scoped to its ID and its POST replaces the complete snapshot. The legacy
single-key mode also accepts partial updates. Only RAV_TOKEN grants MCP access. Without a key (the server on loopback)
any local caller may post. 400: not one JSON object of numbers, strings, bools or nulls.
401: wrong key. 404: no such device on this server. 413: over MAX_BODY.
"""
from __future__ import annotations

import hmac
import json
import math

PREFIX = "/readout/"
MAX_BODY = 4096
SCALAR = (int, float, str, bool, type(None))


class DeviceApi:
    def __init__(self, readouts: dict, key: str | dict[str, str] | None):
        self.readouts, self.key = readouts, key

    def snapshot(self, name: str) -> dict:
        return self.readouts[name].snapshot()

    async def __call__(self, scope, receive, send):
        status, body = await self.handle(scope, receive)
        headers = [(b"content-type", b"application/json" if isinstance(body, dict) else b"text/plain")]
        payload = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        if status != 204:
            headers.append((b"content-length", str(len(payload)).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload if status != 204 else b""})

    async def handle(self, scope, receive):
        name = scope["path"][len(PREFIX):].strip("/")
        key = self.key.get(name) if isinstance(self.key, dict) else self.key
        if self.key is not None:
            got = dict(scope["headers"]).get(b"authorization", b"")
            if key is None or not hmac.compare_digest(got, f"Bearer {key}".encode()):
                return 401, "this endpoint needs the device key"
        readout = self.readouts.get(name)
        if readout is None:
            return 404, f"no device '{name}' on this server: start it with --readout http --readout-device {name}"
        if scope["method"] == "GET":
            return 200, self.snapshot(name)
        if scope["method"] != "POST":
            return 405, "POST a snapshot, or GET the latest"
        raw = b""
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return 400, "incomplete snapshot"
            raw += msg.get("body", b"")
            if len(raw) > MAX_BODY:
                return 413, f"a snapshot is at most {MAX_BODY} bytes"
            if not msg.get("more_body"):
                break
        try:
            snap = json.loads(raw)
        except ValueError:
            return 400, "the body must be one JSON object"
        if not isinstance(snap, dict) or not snap or not all(
            isinstance(v, SCALAR) and (not isinstance(v, float) or math.isfinite(v)) for v in snap.values()
        ) or not any(name != "LCD" for name in snap):
            return 400, "the body must be one flat JSON object: {\"BTN1\": 0, \"FAN\": 0.42, \"LCD\": \"...\"}"
        readout.ingest(snap, replace=isinstance(self.key, dict))
        return 204, ""


class Router:
    """/readout/... to the boards' DeviceApi, everything else to the MCP app behind RAV_TOKEN."""

    def __init__(self, devices, app, device_port=None):
        self.devices, self.app = devices, app
        self.device_port = device_port

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            readout = scope["path"].startswith(PREFIX)
            if self.device_port is not None:
                # ASGI's server address comes from the accepted socket, independent of the Host header.
                on_device_port = scope["server"][1] == self.device_port
                if readout != on_device_port:
                    await send({"type": "http.response.start", "status": 404, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                    return
            if readout:
                return await self.devices(scope, receive, send)
        await self.app(scope, receive, send)
