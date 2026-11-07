"""Dealer integration and request-local response routing."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from math import isfinite
from threading import Lock

import numpy as np
from jsonrpcserver import Error, Success

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.trigger_event import TriggerEvent
from cardtable.data_classes.trigger_message import TriggerMessage
from cardtable.triggers._trigger import Trigger

from .discovery import document
from .protocol import encode_result
from .server import RPCServer


class JRPCTrigger(Trigger):
    """JSON-RPC 2.0 over UTF-8 newline-delimited TCP (one JSON value per line).

    Call ``method`` (default ``trigger``) with params containing required
    ``texts: dict[str, str]`` and optional ``image: dict[str, base64 PNG/JPEG]``.
    Callbacks receive the JSON-RPC fields in ``event.data``, with image values
    decoded to numpy arrays and omitted image normalized to {}. Use event.texts
    and event.images for direct access to these fields. Request IDs must
    be strings; notifications omit id and never receive a response. Images in
    ``event.response(texts, images, image_format="jpg")`` are uint8 OpenCV arrays,
    returned as base64 JPEG strings (or PNG with image_format="png").
    The event automatically identifies the corresponding request.

    Requests on each connection run in order; separate connections and batch
    items wait independently. Dealer serializes callbacks for this trigger.
    Timeout/disconnect does not interrupt a callback already admitted to Dealer.
    """

    def __init__(
        self,
        port: int = 8766,
        callback: TriggerCallback | None = None,
        *,
        host: str = "127.0.0.1",
        method: str = "trigger",
        request_timeout: float = 30.0,
        response_timeout: float = 60.0,
        max_request_bytes: int = 10 * 1024 * 1024,
        max_batch_size: int = 32,
        drop_if_busy: bool = False,
        q_size: int = 10,
        log_level: str | int = "INFO",
    ):
        for name, value in (
            ("port", port),
            ("max_request_bytes", max_request_bytes),
            ("max_batch_size", max_batch_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if not (0 <= value <= 65535 if name == "port" else value > 0):
                raise ValueError(f"Invalid {name}")
        if not isinstance(host, str) or not host:
            raise ValueError("host must be a nonempty string")
        if not isinstance(method, str) or not method or method.startswith("rpc."):
            raise ValueError("method must be nonempty and must not start with rpc.")
        for name, value in (
            ("request_timeout", request_timeout),
            ("response_timeout", response_timeout),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self.host, self._port, self.method = host, port, method
        self.request_timeout, self.response_timeout = request_timeout, response_timeout
        self.max_request_bytes, self.max_batch_size = max_request_bytes, max_batch_size
        self._lifecycle_lock, self._state_lock = Lock(), Lock()
        self._server: RPCServer | None = None
        self._pending: dict[str, Future] = {}
        self._accepting = False

    @property
    def port(self) -> int:
        return self._server.port if self._server else self._port

    @property
    def discovery(self) -> dict:
        return document(self.method)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._server is not None and self._server.thread.is_alive():
                return
            server = RPCServer(self)
            self._server = server
            with self._state_lock:
                self._accepting = True
                self.is_stopped = False
                self._stop_event.clear()
            try:
                server.start()
            except BaseException:
                with self._state_lock:
                    self._accepting = False
                    self.is_stopped = True
                self._server = None
                raise

    def watching_loop(self) -> None:
        server = self._server
        if server is not None:
            try:
                server.run()
            finally:
                with self._state_lock:
                    self._accepting = False
                    self.is_stopped = True

    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._state_lock:
                self._accepting = False
                self._stop_event.set()
                for pending in self._pending.values():
                    if not pending.done():
                        pending.set_result(Error(-32000, "Server stopped"))
                self.clear_event()
            if self._server is not None:
                self._server.stop()
                self._server = None
            self.is_stopped = True

    async def _invoke(self, request: dict):
        message = TriggerMessage(
            timestamp=self.get_timestamp(),
            texts=request["params"]["texts"],
            images=request["params"]["image"],
            data={
                "jsonrpc": "2.0",
                "method": request["method"],
                "params": request.get("params", {}),
                "id": request.get("id"),
            },
        )
        pending = Future()
        with self._state_lock:
            if not self._accepting:
                return Error(-32000, "Server stopped")
            self._pending[message.event_id] = pending
            if not self._set_event(message):
                del self._pending[message.event_id]
                return Error(-32000, "Event queue is full or busy")
        try:
            # Shield the concurrent future: timeout must not race a callback's
            # set_result, and callback completion must not cancel another request.
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(pending)), self.response_timeout
            )
        except asyncio.TimeoutError:
            return Error(-32000, "Callback timed out")
        finally:
            with self._state_lock:
                self._pending.pop(message.event_id, None)

    def _respond(
        self,
        event_id: str,
        texts: dict[str, str],
        images: dict[str, np.ndarray],
        image_format: str = "jpg",
    ) -> None:
        """Resolve only the pending request belonging to this event."""
        result = encode_result(texts, images, image_format)
        with self._state_lock:
            pending = self._pending.get(event_id)
            if pending is None or pending.done():
                raise RuntimeError("Request has expired or already has a response")
            pending.set_result(Success(result))

    def _callbacks_finished(
        self,
        event: TriggerEvent,
        results: tuple[object, ...],
        errors: tuple[Exception, ...],
    ) -> None:
        with self._state_lock:
            pending = self._pending.get(event.event_id)
            if pending is not None and not pending.done():
                pending.set_result(
                    Error(-32603, "Internal error")
                    if errors
                    else Success({"texts": {"success": True}, "images": {}})
                )
