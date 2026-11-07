"""Synchronous message dialogs, serialized across caller threads."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from threading import Condition, get_ident
from typing import Iterator

from cardtable.core.dealer import _callback_stop_event

from ._layout import Row
from .card.popup_card import PopupCard
from .deck import Deck
from .elements.label import Label
from .elements.result_button import CancelBtn, FalseBtn, TrueBtn

_turns = Condition()
_queue: deque[object] = deque()
_owner: int | None = None


def _check_stopped() -> None:
    stop_event = _callback_stop_event.get()
    if stop_event is not None and stop_event.is_set():
        raise RuntimeError("Dealer stopped while waiting for show_message")


@contextmanager
def _message_turn() -> Iterator[None]:
    global _owner
    token = object()
    with _turns:
        _check_stopped()
        if _owner == get_ident():
            raise RuntimeError("show_message cannot be called reentrantly")
        Deck.disable()
        _queue.append(token)
    try:
        with _turns:
            while _queue[0] is not token:
                _check_stopped()
                _turns.wait(0.05)
            _check_stopped()
            _owner = get_ident()
        yield
    finally:
        with _turns:
            if _queue[0] is token:
                _owner = None
            _queue.remove(token)
            try:
                Deck.enable()
            finally:
                _turns.notify_all()


def show_message(
    message: str,
    *,
    true_btn: str | None = "OK",
    false_btn: str | None = None,
    none_btn: str | None = "Cancel",
    default: bool | None = None,
    title: str = "Message",
    auto_close_sec: int | None = None,
) -> bool | None:
    """Display a modal message and wait for True, False, or None.

    Callers display dialogs in arrival order. Only the calling thread waits;
    main-window user input is blocked until all waiting dialogs complete.
    Enter and auto_close_sec return default. If default=None and there is no
    Cancel button, prefer False, then True. An explicit bool default must have
    a visible button. With no buttons, only closing is available (returns None).
    Closing returns None if Cancel exists, the sole button's value if there is
    one, and is otherwise disabled. Escape follows the same rule.
    Dealer shutdown, stopped popups and UI failures raise exceptions.
    """
    for name, value in (("message", message), ("title", title)):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
    labels = (true_btn, false_btn, none_btn)
    for name, value in zip(("true_btn", "false_btn", "none_btn"), labels):
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{name} must be a string or None")
    if default is not None and type(default) is not bool:
        raise TypeError("default must be bool or None")
    if auto_close_sec is not None:
        if type(auto_close_sec) is not int:
            raise TypeError("auto_close_sec must be an integer or None")
        if auto_close_sec < 0:
            raise ValueError("auto_close_sec must be non-negative")
    visible = [
        value for value, label in zip((True, False, None), labels) if label is not None
    ]
    if default is not None and not any(value is default for value in visible):
        raise ValueError("default must have a visible button")
    if default is None and none_btn is None:
        default = next(
            (
                value
                for value in (False, True)
                if any(value is item for item in visible)
            ),
            None,
        )
    close_enabled = none_btn is not None or len(visible) <= 1
    close_result = visible[0] if len(visible) == 1 else None
    with _message_turn():
        with PopupCard(
            title,
            default=default,
            close_enabled=close_enabled,
            close_result=close_result,
            auto_close_sec=auto_close_sec,
            popup_min_content_width=320,
            message_dialog=True,
        ) as card:
            Label(message, anchor="center")
            if visible:
                with Row():
                    for button_type, label in zip(
                        (TrueBtn, FalseBtn, CancelBtn), labels
                    ):
                        if label is not None:
                            button_type(label)
        return card.wait()


__all__ = ["show_message"]
