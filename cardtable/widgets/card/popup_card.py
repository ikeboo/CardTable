"""Temporary, centered windows with synchronous result collection."""

from __future__ import annotations

from threading import Event, Timer
from typing import Any

from cardtable.core.closure import Closure
from cardtable.core.dealer import _callback_stop_event

from .._runtime import CardRuntime
from ..deck import Deck
from ..elements.button import Button, _BtnPressed
from ..elements.result_button import _ResultBtn
from .card import Card


class PopupCard(Card):
    """Display an independent window and wait for True, False, or cancellation.

    Dimensions use Deck's geometry units. The default width is 6 grid cells
    (limited to the configured column count), or 480 pixels. By default the
    height fits the elements, up to the screen height.
    The window is centered on the screen. Leaving a successful declaration
    context starts it and waits for UI readiness. wait() collects the result
    and disposes it; it also starts popups declared without a context.
    auto_close_sec counts from UI readiness and returns default on expiry.
    """

    def __init__(
        self,
        title: str | None,
        *,
        w: int | None = None,
        h: int | None = None,
        auto_close_sec: int | None = None,
        default: bool | None = None,
        close_result: bool | None = None,
        close_enabled: bool = True,
        runtime: CardRuntime | None = None,
        **ui_options: Any,
    ) -> None:
        if auto_close_sec is not None:
            if isinstance(auto_close_sec, bool) or not isinstance(auto_close_sec, int):
                raise TypeError("auto_close_sec must be an integer or None")
            if auto_close_sec < 0:
                raise ValueError("auto_close_sec must be non-negative")
        for name, value in (("default", default), ("close_result", close_result)):
            if value is not None and type(value) is not bool:
                raise TypeError(f"{name} must be bool or None")
        if type(close_enabled) is not bool:
            raise TypeError("close_enabled must be bool")
        settings = Deck._snapshot()
        grid = settings.geometry_unit == "grid"
        super().__init__(
            0,
            0,
            (min(6, settings.grid_columns) if grid else 480) if w is None else w,
            (3 if grid else 240) if h is None else h,
            title,
            runtime=runtime,
            **ui_options,
        )
        self._ui_options.update(
            popup=True, popup_default=default, popup_close_enabled=close_enabled,
            popup_auto_height=h is None,
        )
        self._default = default
        self._close_result = close_result
        self._close_enabled = close_enabled
        self._cancelled = False
        self._failure: Exception | None = None
        self._completed = Event()
        self._result: bool | None = None
        self._waiting = False
        self._disposed = False
        self._auto_close_sec = auto_close_sec
        self._auto_close_timer: Timer | None = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
            if exc_type is None:
                self.start()
        except BaseException:
            self.stop()
            raise
        if exc_type is not None:
            self.stop()

    def _add_button(self, button: Button) -> None:
        super()._add_button(button)
        # Popup result buttons are delivered directly, even when created inside
        # a running Trigger callback. They need no Dealer-managed Trigger.
        if isinstance(button, _ResultBtn):
            Closure().close(self._button_triggers[button.id])

    def _receive_button_press(self, payload: Any) -> bool:
        if isinstance(payload, _BtnPressed):
            button = self._buttons_by_id.get(payload.button_id)
            if isinstance(button, _ResultBtn):
                if button.state != "disabled":
                    self._finish(button.result)
                return True
        return super()._receive_button_press(payload)

    def _finish(self, result: bool | None) -> None:
        with self._state_lock:
            if not self._completed.is_set():
                self._result = result
                self._completed.set()

    def _receive_close_requested(self, *, _attachment: str | None = None) -> None:
        with self._state_lock:
            if self._accept_event(_attachment) and self._close_enabled:
                self._finish(self._close_result)

    def wait(self) -> bool | None:
        """Open the popup, process events, and dispose it after a selection.

        Close requests return close_result (unless close_enabled=False).
        Enter and automatic expiry return default. Dealer shutdown or stop()
        before a result raises RuntimeError; UI failures propagate.
        Only the calling thread waits; other Dealer callbacks and the UI continue running.
        A completed popup retains its result; it cannot be opened again.
        """
        with self._state_lock:
            if self._waiting:
                raise RuntimeError("PopupCard.wait() is already active")
            if self._disposed:
                if self._failure is not None:
                    raise self._failure
                if self._cancelled:
                    raise RuntimeError("PopupCard was stopped before a result")
                stop_event = _callback_stop_event.get()
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Dealer stopped while waiting for PopupCard")
                return self._result
            if self._layout_token is not None:
                raise RuntimeError("finish the PopupCard context before waiting")
            self._waiting = True
            needs_start = not self._started and not self._completed.is_set()
        try:
            stop_event = _callback_stop_event.get()
            if needs_start:
                self.start()
            else:
                self.wait_ready()
            while not self._completed.is_set():
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Dealer stopped while waiting for PopupCard")
                self.poll()
                self._completed.wait(0.01)
            if self._failure is not None:
                raise self._failure
            if self._cancelled:
                raise RuntimeError("PopupCard was stopped before a result")
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("Dealer stopped while waiting for PopupCard")
            return self._result
        finally:
            self.stop()
            with self._state_lock:
                self._waiting = False

    def start(self) -> None:
        """Open and wait for rendering, then start the automatic-close timer."""
        with self._state_lock:
            if self._disposed:
                raise RuntimeError("a disposed PopupCard cannot be restarted")
        try:
            with self._state_lock:
                if self._disposed:
                    raise RuntimeError("a disposed PopupCard cannot be restarted")
                super().start()
            self.wait_ready()
            with self._state_lock:
                if (
                    not self._disposed
                    and self._auto_close_sec is not None
                    and self._auto_close_timer is None
                ):
                    self._auto_close_timer = Timer(self._auto_close_sec, self._expire)
                    self._auto_close_timer.daemon = True
                    self._auto_close_timer.start()
        except BaseException:
            self.stop()
            raise

    def _expire(self) -> None:
        try:
            self.poll()
        except Exception as error:
            with self._state_lock:
                if not self._completed.is_set():
                    self._failure = error
        finally:
            self._finish(self._default)
            self.stop()

    def close(self) -> None:
        """Close the popup with close_result, even if UI closing is disabled.

        Safe to call from another thread or repeatedly. A result already
        selected by a button is retained.
        """
        self._finish(self._close_result)
        self.stop()

    def stop(self) -> None:
        """Cancel a pending wait and release the popup's lifecycle registrations."""
        with self._state_lock:
            if self._disposed:
                return
            self._cancelled = not self._completed.is_set()
            self._completed.set()
            self._disposed = True
            if self._auto_close_timer is not None:
                self._auto_close_timer.cancel()
                self._auto_close_timer = None
            try:
                super().stop()
            finally:
                for control in self._button_triggers.values():
                    Closure().close(control)
                Closure().close(self)


__all__ = ["PopupCard"]
