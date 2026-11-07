from __future__ import annotations

import multiprocessing
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from multiprocessing.process import BaseProcess
from queue import Empty
from threading import Event, RLock
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from weakref import WeakValueDictionary

from ._logging import LogListener, run_ui_with_logging
from .deck import Deck

if TYPE_CHECKING:
    from multiprocessing.queues import Queue

    from .card import Card

_NO_PENDING_UPDATE = object()


class CardRuntimeError(RuntimeError):
    """Raised when the separate UI process cannot host a card."""


class CardRuntime:
    """Own the one CustomTkinter process shared by all card proxies."""

    _instance: CardRuntime | None = None
    _instance_lock = RLock()

    @classmethod
    def instance(cls) -> CardRuntime:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, *, startup_timeout: float = 10.0):
        self.startup_timeout = startup_timeout
        self._lock = RLock()
        self._delivery_lock = RLock()
        self._widgets: WeakValueDictionary[str, Card] = WeakValueDictionary()
        self._attachments: dict[str, str] = {}
        self._deliveries: deque[tuple[Card, str, Any, str]] = deque()
        self._ready: dict[str, Event] = {}
        self._errors: dict[str, str] = {}
        self._pending_updates: dict[str, Any] = {}
        self._updates_in_flight: set[str] = set()
        self._host_error: str | None = None
        self._process: BaseProcess | None = None
        self._command_queue: Queue[Any] | None = None
        self._event_queue: Queue[Any] | None = None
        self._log_queue: Queue[Any] | None = None
        self._log_listener: LogListener | None = None
        self._process_ready: Any = None
        self._window_active: Any = None
        self._status_text = ""
        self._deck_disable_count = 0

    def is_active(self) -> bool:
        """Return whether a window in the running UI process has focus."""
        with self._lock:
            return bool(
                self._process_is_alive()
                and self._window_active is not None
                and self._window_active.is_set()
            )

    def disable_deck(self) -> None:
        with self._lock:
            if not self._deck_disable_count and self._process_is_alive():
                self._send({"type": "deck_enabled", "enabled": False})
            self._deck_disable_count += 1

    def enable_deck(self) -> None:
        with self._lock:
            if self._deck_disable_count:
                self._deck_disable_count -= 1
                if not self._deck_disable_count and self._process_is_alive():
                    self._send({"type": "deck_enabled", "enabled": True})

    def set_status_text(self, text: str) -> None:
        """Retain the latest Deck message and update a running UI."""
        with self._lock:
            self._status_text = text
            if self._process_is_alive():
                self._send({"type": "status_text", "text": text})

    def get_cards(self) -> list[Card]:
        """Return a snapshot of connected controllers in attachment order."""
        with self._lock:
            return list(self._widgets.values())

    def attach(self, widget: Card) -> None:
        """Create a widget view in the UI process."""
        with self._lock:
            self._ensure_process()
            if widget.widget_id in self._attachments:
                return

            self._widgets[widget.widget_id] = widget
            self._ready[widget.widget_id] = Event()
            self._errors.pop(widget.widget_id, None)
            self._attachments[widget.widget_id] = uuid4().hex
            try:
                self._send(
                    {
                        "type": "create",
                        "widget_id": widget.widget_id,
                        "widget_class": widget._class_path,
                        "name": widget.name,
                        "options": deepcopy(widget._ui_options),
                    }
                )
            except Exception:
                self._attachments.pop(widget.widget_id, None)
                self._widgets.pop(widget.widget_id, None)
                self._ready.pop(widget.widget_id, None)
                raise

    def update(self, widget_id: str, payload: Any) -> None:
        with self._lock:
            if widget_id not in self._attachments:
                raise CardRuntimeError(f"widget {widget_id!r} is not attached")
            widget = self._widgets.get(widget_id)
            if widget is not None and widget._latest_only_updates:
                if widget_id in self._updates_in_flight:
                    pending = self._pending_updates.get(widget_id)
                    if isinstance(pending, Mapping) and isinstance(payload, Mapping):
                        payload = {**pending, **payload}
                    self._pending_updates[widget_id] = payload
                    return
                self._send_latest_update(widget_id, payload)
                return
            self._send({"type": "update", "widget_id": widget_id, "payload": payload})

    def set_visibility(self, widget_id: str, *, visible: bool) -> None:
        with self._lock:
            if widget_id not in self._attachments:
                raise CardRuntimeError(f"widget {widget_id!r} is not attached")
            self._send(
                {
                    "type": "show" if visible else "hide",
                    "widget_id": widget_id,
                }
            )

    def update_button(
        self,
        widget_id: str,
        button_id: str,
        *,
        state: str,
        label: str,
    ) -> None:
        with self._lock:
            if widget_id not in self._attachments:
                raise CardRuntimeError(f"widget {widget_id!r} is not attached")
            self._send(
                {
                    "type": "button_update",
                    "widget_id": widget_id,
                    "button_id": button_id,
                    "state": state,
                    "label": label,
                }
            )

    def button_finished(self, widget_id: str, button_id: str) -> None:
        with self._lock:
            if widget_id in self._attachments:
                self._send(
                    {
                        "type": "button_finished",
                        "widget_id": widget_id,
                        "button_id": button_id,
                    }
                )

    def update_element(
        self,
        widget_id: str,
        element_id: str,
        *,
        state: str,
        label: str | None,
    ) -> None:
        with self._lock:
            if widget_id not in self._attachments:
                raise CardRuntimeError(f"widget {widget_id!r} is not attached")
            self._send(
                {
                    "type": "element_update",
                    "widget_id": widget_id,
                    "element_id": element_id,
                    "state": state,
                    "label": label,
                }
            )

    def detach(self, widget_id: str) -> None:
        """Destroy one view and shut the host down after the last view."""
        with self._lock:
            if widget_id in self._attachments and self._process_is_alive():
                try:
                    self._send({"type": "destroy", "widget_id": widget_id})
                except CardRuntimeError:
                    pass
            self._attachments.pop(widget_id, None)
            self._widgets.pop(widget_id, None)
            self._ready.pop(widget_id, None)
            self._errors.pop(widget_id, None)
            self._pending_updates.pop(widget_id, None)
            self._updates_in_flight.discard(widget_id)

            if not self._attachments:
                self._shutdown_process()

    def is_attached(self, widget_id: str, attachment: str) -> bool:
        with self._lock:
            return self._attachments.get(widget_id) == attachment

    def wait_ready(self, widget_id: str, *, timeout: float) -> None:
        with self._lock:
            ready = self._ready.get(widget_id)
        if ready is None:
            return
        deadline = monotonic() + timeout
        while True:
            self.poll()
            with self._lock:
                # Stop (or stop followed by restart) cancels this wait.
                if self._ready.get(widget_id) is not ready:
                    return
                self.raise_for_widget(widget_id)
                if ready.is_set():
                    return
                if not self._process_is_alive():
                    raise CardRuntimeError(
                        self._host_error or "the widget UI process stopped unexpectedly"
                    )
            if monotonic() >= deadline:
                raise TimeoutError(f"widget {widget_id!r} was not ready in time")
            sleep(0.01)

    def poll(self) -> None:
        """Drain and deliver events in order, including reentrant polling."""
        # Take the delivery lock BEFORE dequeuing so concurrent pollers cannot
        # reverse event order. A busy delivery must not make an unrelated
        # element operation wait for validation or user callbacks.
        # Callbacks run without runtime/card state locks.
        if not self._delivery_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                self._deliveries.extend(self._drain_events())
            while self._deliveries:
                widget, event_type, payload, attachment = self._deliveries.popleft()
                with self._lock:
                    if self._blocks_input(widget, event_type, payload):
                        # A press can already have disabled its UI control before
                        # the deck-disable command reaches the UI process.
                        from .elements.button import _BtnPressed

                        if isinstance(payload, _BtnPressed) and self.is_attached(
                            widget.widget_id, attachment
                        ):
                            self.button_finished(widget.widget_id, payload.button_id)
                        continue
                if event_type == "input":
                    widget._receive_input(payload, _attachment=attachment)
                elif event_type == "geometry":
                    widget._receive_geometry(payload, _attachment=attachment)
                else:
                    widget._receive_close_requested(_attachment=attachment)
        finally:
            self._delivery_lock.release()

    def _blocks_input(self, widget: Card, event_type: str, payload: Any) -> bool:
        if (
            not self._deck_disable_count
            or widget._ui_options.get("popup")
            or event_type not in {"input", "close_requested"}
        ):
            return False
        # Viewport requests are rendering traffic, not user edits.
        from .elements.base import DisplayRequest

        return not (
            event_type == "input"
            and isinstance(payload, Mapping)
            and len(payload) == 1
            and isinstance(next(iter(payload.values())), DisplayRequest)
        )

    def _drain_events(self) -> list[tuple[Card, str, Any, str]]:
        """Read transport state under _lock; never call a card or user code."""
        deliveries = []
        if self._event_queue is None:
            return deliveries
        while True:
            try:
                event = self._event_queue.get_nowait()
            except (Empty, OSError, ValueError):
                break

            event_type = event.get("type")
            widget_id = event.get("widget_id")
            # Reject input queued before the UI received the disable command.
            if (
                self._deck_disable_count
                and event_type == "close_requested"
                and widget_id is None
            ):
                continue
            if event_type == "host_error":
                self._host_error = event.get("message", "unknown UI error")
                for ready in self._ready.values():
                    ready.set()
                continue
            if event_type == "close_requested" and widget_id is None:
                widgets = list(self._widgets.values())
                primary = next(
                    (
                        widget
                        for widget in widgets
                        if not widget._ui_options.get("popup")
                    ),
                    None,
                )
                for widget in widgets:
                    if widget is not primary and not widget._ui_options.get("popup"):
                        continue
                    deliveries.append(
                        (
                            widget,
                            "close_requested",
                            None,
                            self._attachments[widget.widget_id],
                        )
                    )
                continue
            if widget_id not in self._attachments:
                continue
            attachment = self._attachments[widget_id]
            if event.get("attachment_id") != attachment:
                continue
            if event_type == "update_done":
                self._updates_in_flight.discard(widget_id)
                payload = self._pending_updates.pop(widget_id, _NO_PENDING_UPDATE)
                if payload is not _NO_PENDING_UPDATE and widget_id in self._attachments:
                    self._send_latest_update(widget_id, payload)
            elif event_type == "ready":
                ready = self._ready.get(widget_id)
                if ready is not None:
                    ready.set()
            elif event_type == "error":
                self._errors[widget_id] = event.get("message", "unknown widget error")
                ready = self._ready.get(widget_id)
                if ready is not None:
                    ready.set()
            elif event_type in {"input", "geometry", "close_requested"}:
                widget = self._widgets.get(widget_id)
                payload = event.get("payload" if event_type == "input" else "geometry")
                if widget is not None and (
                    event_type != "geometry" or payload is not None
                ):
                    deliveries.append((widget, event_type, payload, attachment))
        return deliveries

    def raise_for_widget(self, widget_id: str) -> None:
        with self._lock:
            if self._host_error is not None:
                raise CardRuntimeError(self._host_error)
            error = self._errors.get(widget_id)
            if error is not None:
                raise CardRuntimeError(error)
            if (
                widget_id in self._attachments
                and self._process is not None
                and not self._process.is_alive()
            ):
                raise CardRuntimeError("the widget UI process stopped unexpectedly")

    def _ensure_process(self) -> None:
        if self._process_is_alive():
            return

        self._shutdown_process()
        context = multiprocessing.get_context("spawn")
        self._command_queue = context.Queue()
        self._event_queue = context.Queue()
        self._log_queue = context.Queue()
        self._log_listener = LogListener(self._log_queue)
        self._log_listener.start()
        self._process_ready = context.Event()
        self._window_active = context.Event()
        self._process = context.Process(
            target=run_ui_with_logging,
            args=(
                self._log_queue,
                self._command_queue,
                self._event_queue,
                self._process_ready,
                Deck._snapshot(),
                self._window_active,
            ),
            name="cardtable-ui",
        )
        try:
            self._process.start()
        except Exception:
            self._shutdown_process()
            raise

        if not self._process_ready.wait(self.startup_timeout):
            self._shutdown_process()
            raise TimeoutError("the widget UI process did not start in time")

        # This fresh process has no views yet. Only read startup status here:
        # attach holds a card lock and must not acquire the delivery lock.
        self._drain_events()
        if self._host_error is not None or not self._process_is_alive():
            message = self._host_error or "the widget UI process failed to start"
            self._shutdown_process()
            raise CardRuntimeError(message)

        if self._status_text:
            self._send({"type": "status_text", "text": self._status_text})
        if self._deck_disable_count:
            self._send({"type": "deck_enabled", "enabled": False})

    def _send(self, command: dict[str, Any]) -> None:
        if self._command_queue is None or not self._process_is_alive():
            raise CardRuntimeError("the widget UI process is not running")
        widget_id = command.get("widget_id")
        if widget_id in self._attachments:
            command = dict(command, attachment_id=self._attachments[widget_id])
        self._command_queue.put(command)

    def _send_latest_update(self, widget_id: str, payload: Any) -> None:
        self._send(
            {
                "type": "update",
                "widget_id": widget_id,
                "payload": payload,
                "ack": True,
            }
        )
        self._updates_in_flight.add(widget_id)

    def _process_is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def _shutdown_process(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            if self._command_queue is not None:
                self._command_queue.put({"type": "shutdown"})
            process.join(timeout=2.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)

        for queue in (self._command_queue, self._event_queue):
            if queue is not None:
                # The consumer may have died with a large frame still in the
                # feeder pipe. Joining that feeder would block stop forever.
                queue.cancel_join_thread()
                queue.close()
        if self._log_listener is not None:
            self._log_listener.stop()
        if self._log_queue is not None:
            self._log_queue.close()
            self._log_queue.join_thread()
        self._reset_process_state()

    def _reset_process_state(self) -> None:
        self._process = None
        self._command_queue = None
        self._event_queue = None
        self._log_queue = None
        self._log_listener = None
        self._process_ready = None
        self._window_active = None
        self._host_error = None
        self._pending_updates.clear()
        self._updates_in_flight.clear()
