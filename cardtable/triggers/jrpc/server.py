"""One asyncio loop owns every socket and cleans up connections on shutdown."""

import asyncio
import json
import socket
from threading import Event, Thread, current_thread

from .protocol import dispatch, error


class RPCServer:
    def __init__(self, trigger):
        self.trigger = trigger
        self.ready = Event()
        self.startup_error = None
        self.loop = None
        self.shutdown = None
        self.port = trigger._port
        self.thread = Thread(
            target=trigger.watching_loop, daemon=True, name=f"JRPCTrigger-{trigger.id}"
        )

    def start(self):
        self.thread.start()
        self.ready.wait()
        if self.startup_error is not None:
            self.thread.join()
            raise self.startup_error

    def run(self):
        try:
            asyncio.run(self.serve())
        except BaseException as exc:
            self.startup_error = exc
        finally:
            self.ready.set()

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.shutdown = self.loop.create_future()
        clients = {}

        def connected(reader, writer):
            async def handle_client():
                try:
                    await self.handle(reader, writer)
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (ConnectionError, OSError):
                        pass

            task = asyncio.create_task(handle_client())
            clients[task] = writer
            task.add_done_callback(lambda task: clients.pop(task, None))

        async with await asyncio.start_server(
            connected,
            self.trigger.host,
            self.trigger._port,
            limit=self.trigger.max_request_bytes,
            family=socket.AF_INET6 if ":" in self.trigger.host else socket.AF_INET,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            try:
                await self.shutdown
            finally:
                server.close()
                # Register connections synchronously on accept, and close even
                # writers whose handler has not had a chance to start yet.
                for task, writer in tuple(clients.items()):
                    writer.close()
                    task.cancel()
                await asyncio.gather(*clients, return_exceptions=True)
                await server.wait_closed()

    async def handle(self, reader, writer):
        while True:
            try:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=self.trigger.request_timeout
                )
                if not line:
                    return
                if not line.endswith(b"\n"):
                    return
                response = await dispatch(line, self.trigger)
            except (asyncio.TimeoutError, ValueError):
                response = error(-32000, "Request timed out or exceeded size limit")
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
                return
            except (ConnectionError, OSError):
                return
            if response is not None:
                try:
                    writer.write(json.dumps(response, allow_nan=False).encode() + b"\n")
                    await asyncio.wait_for(
                        writer.drain(), timeout=self.trigger.request_timeout
                    )
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    return

    def stop(self):
        def shutdown():
            if self.shutdown is not None and not self.shutdown.done():
                self.shutdown.set_result(None)

        if self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(shutdown)
            except RuntimeError:  # The server already exited and closed its loop.
                pass
        if self.thread.ident is not None and self.thread is not current_thread():
            self.thread.join()
