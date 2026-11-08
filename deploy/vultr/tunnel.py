"""Forward loopback TCP streams over one authenticated, outbound WebSocket."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from http import HTTPStatus
import hmac
import logging
import os
from pathlib import Path
import struct
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidHandshake

HOST = "127.0.0.1"
HEADER = struct.Struct("!BI")
# Each frame names a TCP stream. Only the relay opens streams; either side can send or half-close.
OPEN, DATA, ACK, EOF, CLOSE = range(5)
CHUNK = 32 * 1024
MAX_STREAMS = 64
LOG = logging.getLogger("rav-tunnel")


@dataclass
class Stream:
    incoming: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2))
    ack: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    writer: asyncio.StreamWriter | None = None
    awaiting_ack: bool = False
    received_eof: bool = False


class Tunnel:
    def __init__(self, ws, target_port: int | None = None):
        self.ws = ws
        self.target_port = target_port
        self.streams: dict[int, Stream] = {}
        self.next_id = 1
        self.closed = False

    async def send(self, kind, stream_id, data=b""):
        await self.ws.send(HEADER.pack(kind, stream_id) + data)

    async def accept(self, reader, writer):
        if self.closed or len(self.streams) >= MAX_STREAMS or self.next_id >= 2**32:
            writer.close()
            return
        stream_id = self.next_id
        self.next_id += 1
        self.start(stream_id, reader, writer)

    def start(self, stream_id, reader=None, writer=None):
        stream = self.streams[stream_id] = Stream(writer=writer)
        stream.task = asyncio.create_task(self.forward(stream_id, stream, reader, writer))

    async def forward(self, stream_id, stream, reader, writer):
        async def to_websocket():
            while data := await reader.read(CHUNK):
                # One chunk per stream in flight keeps a slow reader from stalling the other streams.
                stream.ack.clear()
                stream.awaiting_ack = True
                await self.send(DATA, stream_id, data)
                await stream.ack.wait()
            await self.send(EOF, stream_id)

        async def to_tcp():
            while (data := await stream.incoming.get()) is not None:
                writer.write(data)
                await writer.drain()
                await self.send(ACK, stream_id)
            writer.write_eof()

        try:
            if writer is None:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(HOST, self.target_port), 5)
            else:
                await self.send(OPEN, stream_id)
            async with asyncio.TaskGroup() as group:
                group.create_task(to_websocket())
                group.create_task(to_tcp())
        except* (OSError, TimeoutError, ConnectionClosed):
            pass
        finally:
            if writer is not None:
                writer.close()
            if self.streams.pop(stream_id, None) is not None:
                try:
                    await self.send(CLOSE, stream_id)
                except ConnectionClosed:
                    pass

    async def receive(self):
        try:
            async for message in self.ws:
                if not self.dispatch(message):
                    await self.ws.close(1002, "invalid tunnel frame")
                    break
        finally:
            self.closed = True
            streams = list(self.streams.values())
            self.streams.clear()
            for stream in streams:
                if stream.writer is not None:
                    stream.writer.close()
                stream.task.cancel()
            await asyncio.gather(*(stream.task for stream in streams), return_exceptions=True)

    def dispatch(self, message) -> bool:
        if not isinstance(message, bytes) or len(message) < HEADER.size:
            return False
        kind, stream_id = HEADER.unpack_from(message)
        data = message[HEADER.size:]
        if not stream_id or kind > CLOSE or bool(data) != (kind == DATA):
            return False
        if kind == OPEN:
            if self.target_port is None or stream_id < self.next_id or len(self.streams) >= MAX_STREAMS:
                return False
            self.next_id = stream_id + 1
            self.start(stream_id)
            return True
        stream = self.streams.get(stream_id)
        if stream is None:
            return True  # a stream can finish with frames still in flight
        if kind == CLOSE:
            self.streams.pop(stream_id)
            if stream.writer is not None:
                stream.writer.close()
            stream.task.cancel()
        elif kind == ACK:
            if not stream.awaiting_ack:
                return False
            stream.awaiting_ack = False
            stream.ack.set()
        else:
            if stream.received_eof or stream.incoming.full():
                return False
            stream.received_eof = kind == EOF
            stream.incoming.put_nowait(None if stream.received_eof else data)
        return True


async def relay(websocket_port, mcp_port, token):
    active = None

    def authorize(connection, request):
        if request.path != "/tunnel":
            return connection.respond(HTTPStatus.NOT_FOUND, "unknown route\n")
        headers = request.headers.get_all("Authorization")
        if len(headers) != 1 or not hmac.compare_digest(headers[0].encode(), token.encode()):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid tunnel token\n")
        if active is not None:
            return connection.respond(HTTPStatus.CONFLICT, "System 1 is already connected\n")

    async def connected(ws):
        nonlocal active
        if active is not None:
            await ws.close(1008, "System 1 is already connected")
            return
        active = Tunnel(ws)
        LOG.info("System 1 connected")
        try:
            await active.receive()
        except ConnectionClosed:
            pass
        finally:
            active = None
            LOG.info("System 1 disconnected")

    async def accept(reader, writer):
        if active is None:
            writer.close()
        else:
            await active.accept(reader, writer)

    async with serve(connected, HOST, websocket_port, process_request=authorize,
                     max_size=HEADER.size + CHUNK, compression=None):
        async with await asyncio.start_server(accept, HOST, mcp_port) as listener:
            LOG.info("Relay listening on loopback ports %d (WebSocket) and %d (MCP)", websocket_port, mcp_port)
            await listener.serve_forever()


async def client(url, target_port, token):
    delay = 1
    LOG.info("Connecting to %s", url)
    while True:
        try:
            async with connect(url, additional_headers={"Authorization": token},
                               max_size=HEADER.size + CHUNK, compression=None) as ws:
                LOG.info("Connected to Vultr")
                delay = 1
                await Tunnel(ws, target_port).receive()
        except (OSError, TimeoutError, ConnectionClosed) as exc:
            LOG.warning("Tunnel disconnected: %s", exc)
        except InvalidHandshake as exc:
            LOG.warning("Tunnel upgrade failed: %s", exc)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["relay", "client"])
    parser.add_argument("--url", help="client: wss://your-vps.example/tunnel")
    parser.add_argument("--mcp-port", type=int, default=8780)
    parser.add_argument("--relay-port", type=int, default=7000)
    args = parser.parse_args()
    token_file = os.environ.get("RAV_TUNNEL_TOKEN_FILE")
    if not token_file and os.environ.get("CREDENTIALS_DIRECTORY"):
        token_file = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "tunnel-token"
    if not token_file:
        parser.error("set RAV_TUNNEL_TOKEN_FILE to a private token file")
    token = Path(token_file).read_text(encoding="ascii").strip()
    if len(token) < 32 or not all(c.isalnum() or c in "-_" for c in token):
        parser.error("the tunnel token must have at least 32 URL-safe characters")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.mode == "relay":
        asyncio.run(relay(args.relay_port, args.mcp_port, f"Bearer {token}"))
    else:
        url = urlsplit(args.url or "")
        if url.scheme != "wss" or not url.hostname or url.path != "/tunnel" or url.username or url.query or url.fragment:
            parser.error("client requires --url wss://your-vps.example/tunnel")
        asyncio.run(client(args.url, args.mcp_port, f"Bearer {token}"))


if __name__ == "__main__":
    main()
