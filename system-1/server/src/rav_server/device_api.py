"""The appliance boards' way in over WiFi: each POSTs its snapshot, the same JSON object the Pico prints over USB, to
/readout/<device>, and the server hands it to that device's http_readout.HttpReadout.

    POST /readout/mw1   Authorization: Bearer <RAV_DEVICE_KEY>   {"BTN1": 0, "DOOR": 1, "LCD": "READY"}   -> 204
    GET  /readout/mw1   Authorization: Bearer <RAV_DEVICE_KEY>   -> {"readings": {...}, "lcd": ..., "age_s": 0.3}

The device key is not RAV_TOKEN: a board holds only a key that feeds readings, never one that moves the arm. Without a
key (the server on loopback) any local caller may post. 400: not one JSON object of numbers, strings, bools or nulls.
401: wrong key. 404: no such device on this server. 413: over MAX_BODY.
"""
from __future__ import annotations

import hmac
import json
import time

PREFIX = "/readout/"
MAX_BODY = 4096
SCALAR = (int, float, str, bool, type(None))


class DeviceApi:
    def __init__(self, readouts: dict, key: str | None):
        self.readouts, self.expected = readouts, f"Bearer {key}".encode() if key else None

    async def __call__(self, scope, receive, send):
        status, body = await self.handle(scope, receive)
        headers = [(b"content-type", b"application/json" if isinstance(body, dict) else b"text/plain")]
        payload = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload if status != 204 else b""})

    async def handle(self, scope, receive):
        if self.expected is not None:
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                return 401, "this endpoint needs the device key"
        name = scope["path"][len(PREFIX):].strip("/")
        readout = self.readouts.get(name)
        if readout is None:
            return 404, f"no device '{name}' on this server: start it with --readout http --readout-device {name}"
        if scope["method"] == "GET":
            return 200, {"readings": dict(readout._readings), "lcd": readout.lcd,
                         "age_s": round(time.monotonic() - readout.last, 3) if readout.started else None}
        if scope["method"] != "POST":
            return 405, "POST a snapshot, or GET the latest"
        raw = b""
        while True:
            msg = await receive()
            raw += msg.get("body", b"")
            if len(raw) > MAX_BODY:
                return 413, f"a snapshot is at most {MAX_BODY} bytes"
            if not msg.get("more_body"):
                break
        try:
            snap = json.loads(raw)
        except ValueError:
            return 400, "the body must be one JSON object"
        if not isinstance(snap, dict) or not all(isinstance(v, SCALAR) for v in snap.values()):
            return 400, "the body must be one flat JSON object: {\"BTN1\": 0, \"FAN\": 0.42, \"LCD\": \"...\"}"
        readout.ingest(snap)
        return 204, ""


class Router:
    """/readout/... to the boards' DeviceApi, everything else to the MCP app behind RAV_TOKEN."""

    def __init__(self, devices, app):
        self.devices, self.app = devices, app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(PREFIX):
            return await self.devices(scope, receive, send)
        await self.app(scope, receive, send)
