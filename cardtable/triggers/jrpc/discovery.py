"""OpenRPC discovery document, including complete wire-envelope schemas."""

from .models import RequestParams


def document(method: str) -> dict:
    result = {
        "type": "object",
        "required": ["texts", "images"],
        "additionalProperties": False,
        "properties": {
            "texts": {
                "type": "object",
                "additionalProperties": {"type": ["string", "boolean"]},
            },
            "images": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                    "contentEncoding": "base64",
                    "anyOf": [
                        {"contentMediaType": "image/jpeg"},
                        {"contentMediaType": "image/png"},
                    ],
                },
            },
        },
    }
    params = RequestParams.wire_schema()
    request = {
        "type": "object",
        "required": ["jsonrpc", "method", "params"],
        "additionalProperties": False,
        "properties": {
            "jsonrpc": {"const": "2.0"},
            "method": {"const": method},
            "params": params,
            "id": {"type": "string"},
        },
    }
    return {
        "openrpc": "1.3.2",
        "info": {"title": "CardTable JRPCTrigger", "version": "1.0.0"},
        "methods": [
            {
                "name": method,
                "description": "Emit a TriggerEvent with texts and optional named "
                "base64 PNG/JPEG images, decoded to numpy arrays in event.data.",
                "params": [
                    {
                        "name": name,
                        "required": name in params["required"],
                        "schema": schema,
                    }
                    for name, schema in params["properties"].items()
                ],
                "paramStructure": "by-name",
                "x-request-schema": request,
                "result": {"name": "result", "schema": result},
            },
            {
                "name": "rpc.discover",
                "params": [],
                "result": {"name": "document", "schema": {"type": "object"}},
            },
        ],
    }
