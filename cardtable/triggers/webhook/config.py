"""Validated, immutable HTTP endpoint settings."""

import math
import re
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WebhookSettings:
    port: int = 8765
    host: str = "127.0.0.1"
    path: str = "/events"
    token: str | None = field(default=None, repr=False)
    max_body_bytes: int = 10 * 1024 * 1024
    max_result_bytes: int = 10 * 1024 * 1024
    max_items: int = 32
    request_timeout: float = 5.0
    response_timeout: float = 60.0
    history_size: int = 100

    def __post_init__(self) -> None:
        for name in (
            "port",
            "max_body_bytes",
            "max_result_bytes",
            "max_items",
            "history_size",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if name == "port":
                if not 0 <= value <= 65535:
                    raise ValueError("port must be between 0 and 65535")
            elif value <= 0:
                raise ValueError(f"{name} must be positive")
        if not isinstance(self.host, str):
            raise TypeError("host must be a string")
        if not self.host or re.search(r"[\s/?#@\[\]]", self.host):
            raise ValueError("host must be a hostname or an unbracketed IP address")
        if not isinstance(self.path, str):
            raise TypeError("path must be a string")
        if not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", self.path):
            raise ValueError(
                "path must contain slash-separated names without a trailing slash"
            )
        if self.path in ("/docs", "/guide", "/redoc"):
            raise ValueError("path is reserved for API documentation")
        if self.token is not None:
            if not isinstance(self.token, str):
                raise TypeError("token must be a string or None")
            if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", self.token):
                raise ValueError("token must be a nonempty Bearer token")
        for name in ("request_timeout", "response_timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")

    def base_url(self, port: int) -> str:
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(self.host, self.host)
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{port}"
