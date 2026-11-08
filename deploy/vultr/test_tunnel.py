import asyncio
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tunnel import CHUNK, HEADER, HOST, Tunnel


class TunnelTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_streams_and_half_close(self):
        async def echo(reader, writer):
            async with asyncio.timeout(5):
                try:
                    # The response starts only after the caller half-closes the request.
                    writer.write(await reader.read())
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

        async with await asyncio.start_server(echo, HOST, 0) as backend:
            target_port = backend.sockets[0].getsockname()[1]

            async def connected(ws):
                await Tunnel(ws, target_port).receive()

            async with serve(connected, HOST, 0, max_size=HEADER.size + CHUNK) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://{HOST}:{port}", max_size=HEADER.size + CHUNK) as ws:
                    relay = Tunnel(ws)
                    receive = asyncio.create_task(relay.receive())
                    try:
                        async with await asyncio.start_server(relay.accept, HOST, 0) as proxy:
                            proxy_port = proxy.sockets[0].getsockname()[1]

                            async def round_trip(payload):
                                reader, writer = await asyncio.open_connection(HOST, proxy_port)
                                try:
                                    writer.write(payload)
                                    await writer.drain()
                                    writer.write_eof()
                                    self.assertEqual(await reader.read(), payload)
                                finally:
                                    writer.close()
                                    await writer.wait_closed()

                            async with asyncio.timeout(5):
                                await asyncio.gather(round_trip(bytes(range(256)) * 1024), round_trip(b"other stream"))
                    finally:
                        await ws.close()
                        await receive
