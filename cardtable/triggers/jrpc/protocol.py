"""Delegate JSON-RPC validation, errors and notifications to jsonrpcserver."""

import asyncio
import base64
import json
from math import isfinite

import cv2
import numpy as np
from jsonrpcserver import Error, Success, async_dispatch_to_serializable

from .models import RequestParams


def encode_result(
    texts: dict, images: dict[str, np.ndarray], image_format: str = "jpg"
) -> dict:
    if not isinstance(image_format, str):
        raise TypeError("image_format must be a str")
    if image_format not in ("jpg", "png"):
        raise ValueError("image_format must be 'jpg' or 'png'")
    if not isinstance(texts, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in texts.items()
    ):
        raise TypeError("texts must be a dict[str, str]")
    if not isinstance(images, dict):
        raise TypeError("images must be a dict[str, numpy.ndarray]")
    encoded = {}
    for name, image in images.items():
        if not isinstance(name, str) or not isinstance(image, np.ndarray):
            raise TypeError("images must be a dict[str, numpy.ndarray]")
        if (
            image.dtype != np.uint8
            or image.size == 0
            or not (
                image.ndim == 2 or (image.ndim == 3 and image.shape[2] in (1, 3, 4))
            )
        ):
            raise ValueError("images must be nonempty uint8 gray, BGR or BGRA arrays")
        if image_format == "jpg" and image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        success, content = cv2.imencode(f".{image_format}", image)
        if not success:
            raise ValueError(f"image could not be encoded as {image_format}")
        encoded[name] = base64.b64encode(content).decode("ascii")
    return {"texts": dict(texts), "images": encoded}


def error(code: int, message: str, request_id=None) -> dict:
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": request_id,
    }


def loads(value):
    def invalid_constant(constant):
        raise ValueError(f"Invalid JSON constant: {constant}")

    def finite_float(value):
        number = float(value)
        if not isfinite(number):
            raise ValueError("JSON number is not finite")
        return number

    return json.loads(value, parse_constant=invalid_constant, parse_float=finite_float)


async def dispatch(line: bytes, trigger):
    try:
        request = loads(line)
    except (ValueError, UnicodeError, RecursionError):
        return error(-32700, "Parse error")

    async def one(item):
        # A batch entry is a request, never another batch. The library validates
        # each entry so mixed valid/invalid batches remain independent.
        if isinstance(item, list):
            return error(-32600, "Invalid request")

        async def invoke(*args, **kwargs):
            try:
                params = RequestParams.model_validate(item.get("params")).to_data()
            except (ValueError, TypeError, cv2.error):
                return Error(-32602, "Invalid params")
            return await trigger._invoke({**item, "params": params})

        async def discover():
            return Success(trigger.discovery)

        async def invalid_id(*args, **kwargs):
            return Error(-32600, "Request id must be a string")

        methods = {trigger.method: invoke, "rpc.discover": discover}
        if isinstance(item, dict) and "id" in item:
            if not isinstance(item["id"], str):
                methods[trigger.method] = invalid_id
        return await async_dispatch_to_serializable(
            item, methods=methods, deserializer=lambda value: value
        )

    if isinstance(request, list) and request:
        if len(request) > trigger.max_batch_size:
            return error(-32000, "Batch is too large")
        results = await asyncio.gather(*(one(item) for item in request))
        return [result for result in results if result is not None] or None
    return await one(request)
