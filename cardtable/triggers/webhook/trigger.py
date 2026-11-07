"""Dealer lifecycle, job admission and callback-result delivery."""

from __future__ import annotations

import logging
from threading import Lock, Thread, current_thread
from time import monotonic

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.trigger_event import TriggerEvent
from cardtable.data_classes.trigger_message import TriggerMessage
from cardtable.triggers._trigger import Trigger

from .config import WebhookSettings
from .errors import WebhookError
from .history import Job, JobHistory
from .models import CallbackResult, ErrorInfo, EventResponse, Submission
from .server import WebhookServer

_logger = logging.getLogger(__name__)


class WebhookTrigger(Trigger):
    """Named JSON text/image requests and inference results over FastAPI.

    Return a WebhookEventData-shaped dictionary from the callback, with image
    ``content`` as bytes. HTTP responses encode those bytes as Base64.
    """

    def __init__(
        self,
        port: int = 8765,
        callback: TriggerCallback | None = None,
        *,
        host: str = "127.0.0.1",
        path: str = "/events",
        token: str | None = None,
        max_body_bytes: int = 10 * 1024 * 1024,
        max_result_bytes: int = 10 * 1024 * 1024,
        max_items: int = 32,
        request_timeout: float = 5.0,
        response_timeout: float = 60.0,
        history_size: int = 100,
        drop_if_busy: bool = False,
        q_size: int = 10,
        log_level: str | int = "INFO",
    ):
        self.settings = WebhookSettings(
            port=port,
            host=host,
            path=path,
            token=token,
            max_body_bytes=max_body_bytes,
            max_result_bytes=max_result_bytes,
            max_items=max_items,
            request_timeout=request_timeout,
            response_timeout=response_timeout,
            history_size=history_size,
        )
        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self._history = JobHistory(history_size)
        self._lifecycle_lock, self._state_lock = Lock(), Lock()
        self._server: WebhookServer | None = None
        self._watch_thread: Thread | None = None
        self._accepting = False
        self._startup_error: BaseException | None = None

    @property
    def port(self) -> int:
        return self._server.port if self._server else self.settings.port

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("webhook has not been started")
        return self._server.base_url

    @property
    def url(self) -> str:
        return self.base_url + self.settings.path

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._watch_thread is not None:
                if self._watch_thread.is_alive():
                    return
                self._stop_resources()
            try:
                self._server = WebhookServer(self)
                self._startup_error = None
                self._stop_event.clear()
                with self._state_lock:
                    self._accepting = True
                    self.is_stopped = False
                self._watch_thread = Thread(
                    target=self.watching_loop,
                    name=f"WebhookTrigger-{self.id}",
                    daemon=True,
                )
                self._watch_thread.start()
                deadline = monotonic() + 5
                while not self._server.runner.started:
                    if not self._watch_thread.is_alive() or monotonic() >= deadline:
                        raise RuntimeError(
                            "Webhook server failed to start"
                        ) from self._startup_error
                    self._stop_event.wait(0.01)
            except Exception:
                self._stop_resources()
                raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_resources()

    def _stop_resources(self) -> None:
        with self._state_lock:
            self._accepting = False
            self._stop_event.set()
            self._history.cancel_pending()
        server, worker = self._server, self._watch_thread
        if server is not None:
            server.stop()
        if (
            worker is not None
            and worker.ident is not None
            and worker is not current_thread()
        ):
            worker.join()
        if server is not None:
            server.close()
        with self._state_lock:
            self.clear_event()
            self._history.clear()
            self._server = self._watch_thread = None
            self.is_stopped = True

    def watching_loop(self) -> None:
        server = self._server
        if server is None:
            return
        try:
            server.run()
        except BaseException as error:
            self._startup_error = error
            _logger.exception("Webhook server stopped unexpectedly")
        finally:
            with self._state_lock:
                self._accepting = False
                self._history.cancel_pending()
                self.is_stopped = True
            server.close()

    def _accept(self, payload: Submission) -> Job:
        data = payload.to_data()
        with self._state_lock:
            if not self._accepting:
                raise WebhookError(503, "stopping", "Webhook is stopping")
            if not self._history.can_add():
                raise WebhookError(
                    503, "history_full", "All retained jobs are still pending"
                )
            message = TriggerMessage(
                timestamp=self.get_timestamp(),
                data=data,
                texts=data["texts"],
                images=data["images"],
            )
            job = Job(
                EventResponse(
                    event_id=message.event_id,
                    text_count=len(data["texts"]),
                    image_count=len(data["images"]),
                    status="pending",
                )
            )
            if not self._set_event(message):
                _logger.warning("WebhookTrigger %s: queue is full or busy", self.id)
                raise WebhookError(
                    503, "queue_unavailable", "Event queue is full or busy"
                )
            self._history.add(job)
            return job

    def _get_result(self, event_id: str) -> EventResponse | None:
        return self._history.get(event_id)

    def _callbacks_finished(
        self,
        event: TriggerEvent,
        results: tuple[object, ...],
        errors: tuple[Exception, ...],
    ) -> None:
        result, error = None, None
        if errors:
            error = ErrorInfo(
                code="inference_failed",
                message=str(errors[0]) or type(errors[0]).__name__,
            )
        else:
            try:
                outputs = [value for value in results if value is not None]
                if len(outputs) > 1:
                    raise ValueError(
                        "Only one callback may produce an inference result"
                    )
                result = CallbackResult.model_validate(
                    outputs[0] if outputs else {}
                ).to_wire(self.settings.max_items, self.settings.max_result_bytes)
            except (ValueError, TypeError) as cause:
                error = ErrorInfo(
                    code="invalid_result",
                    message="Invalid or oversized callback text/image result",
                )
                _logger.warning(
                    "WebhookTrigger %s: invalid callback result (%s)",
                    self.id,
                    type(cause).__name__,
                )
        with self._state_lock:
            self._history.finish(event.event_id, result, error)
