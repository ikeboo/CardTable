"""Uvicorn runner with an explicitly owned socket for predictable lifecycle."""

import socket

import uvicorn

from .api import WebhookEndpoint, create_app


class WebhookServer:
    def __init__(self, endpoint: WebhookEndpoint):
        settings = endpoint.settings
        family = socket.AF_INET6 if ":" in settings.host else socket.AF_INET
        self.socket = socket.create_server(
            (settings.host, settings.port), family=family
        )
        self.port = self.socket.getsockname()[1]
        self.base_url = settings.base_url(self.port)
        try:
            self.app = create_app(endpoint, self.base_url)
            self.runner = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host=settings.host,
                    port=self.port,
                    loop="asyncio",
                    http="h11",
                    ws="none",
                    access_log=False,
                    log_config=None,
                    proxy_headers=False,
                    timeout_graceful_shutdown=1,
                )
            )
        except Exception:
            self.socket.close()
            raise

    def run(self) -> None:
        self.runner.run(sockets=[self.socket])

    def stop(self) -> None:
        self.runner.should_exit = True

    def close(self) -> None:
        self.socket.close()
