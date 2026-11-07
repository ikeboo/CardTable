"""Request limits/auth before body parsing, plus strict JSON for FastAPI routes."""

import asyncio
import hmac
import json
from collections.abc import Callable
from contextlib import suppress
from threading import Event

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from .config import WebhookSettings
from .errors import WebhookError


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WebhookError(
                400, "invalid_payload", "Duplicate JSON keys are not allowed"
            )
        result[key] = value
    return result


def _constant(value):
    raise WebhookError(400, "invalid_payload", f"Invalid JSON constant: {value}")


class StrictRequest(Request):
    async def json(self):
        try:
            return json.loads(
                (await self.body()).decode("utf-8"),
                object_pairs_hook=_object,
                parse_constant=_constant,
            )
        except (ValueError, RecursionError) as error:
            raise WebhookError(
                400, "invalid_payload", "Body must be UTF-8 JSON"
            ) from error


class JSONRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def strict(request: Request):
            return await handler(StrictRequest(request.scope, request.receive))

        return strict


class RequestLimits:
    def __init__(self, app, settings: WebhookSettings, stop_event: Event):
        self.app, self.settings = app, settings
        self.stop_event = stop_event

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def response_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)

        path, method = scope["path"], scope["method"]
        collection = path == self.settings.path
        protected = collection or path.startswith(self.settings.path + "/")
        try:
            headers = Headers(scope=scope)
            if protected and self.settings.token is not None:
                values = headers.getlist("authorization")
                scheme, _, token = (
                    values[0].partition(" ") if len(values) == 1 else ("", "", "")
                )
                if scheme.lower() != "bearer" or not hmac.compare_digest(
                    token.encode("utf-8"), self.settings.token.encode("utf-8")
                ):
                    raise WebhookError(
                        401,
                        "unauthorized",
                        "A valid Bearer token is required",
                        {"WWW-Authenticate": 'Bearer realm="cardtable"'},
                    )
            if collection and method == "POST":
                if len(headers.getlist("content-type")) != 1:
                    raise WebhookError(
                        415, "unsupported_media_type", "Send one Content-Type header"
                    )
                media = headers.get("content-type", "").lower().replace(" ", "")
                if media not in (
                    "application/json",
                    "application/json;charset=utf-8",
                    'application/json;charset="utf-8"',
                ):
                    raise WebhookError(
                        415,
                        "unsupported_media_type",
                        "Send application/json encoded as UTF-8",
                    )
                if headers.get("content-encoding", "identity").lower() != "identity":
                    raise WebhookError(
                        415,
                        "unsupported_media_type",
                        "Compressed bodies are not supported",
                    )
                lengths = headers.getlist("content-length")
                if (
                    len(lengths) > 1
                    or (lengths and not lengths[0].isascii())
                    or (lengths and not lengths[0].isdigit())
                ):
                    raise WebhookError(400, "invalid_length", "Invalid Content-Length")
                if lengths and len(lengths[0]) > 20:
                    raise WebhookError(
                        413, "body_too_large", "Body exceeds max_body_bytes"
                    )
                if lengths and int(lengths[0]) > self.settings.max_body_bytes:
                    raise WebhookError(
                        413, "body_too_large", "Body exceeds max_body_bytes"
                    )
        except WebhookError as error:
            response = JSONResponse(
                error.as_dict(), error.status, headers=error.headers
            )
            return await response(scope, receive, response_send)

        read = 0

        async def bounded_receive():
            nonlocal read
            task = asyncio.create_task(receive())
            deadline = asyncio.get_running_loop().time() + self.settings.request_timeout
            try:
                while True:
                    if self.stop_event.is_set():
                        raise WebhookError(503, "stopping", "Webhook is stopping")
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise WebhookError(
                            408, "request_timeout", "Timed out reading request body"
                        )
                    done, _ = await asyncio.wait({task}, timeout=min(remaining, 0.1))
                    if done:
                        message = task.result()
                        break
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if message["type"] == "http.request":
                read += len(message.get("body", b""))
                if read > self.settings.max_body_bytes:
                    raise WebhookError(
                        413, "body_too_large", "Body exceeds max_body_bytes"
                    )
            return message

        await self.app(scope, bounded_receive if collection else receive, response_send)
