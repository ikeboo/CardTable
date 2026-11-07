"""Declarative buttons shared by all widget types."""

from __future__ import annotations

from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

from cardtable._logging import _normalize_level
from cardtable.core.trigger_callback import TriggerCallback, validate_trigger_callback
from cardtable.data_classes.trigger_message import TriggerMessage
from cardtable.triggers._trigger import Trigger

from .. import theme
from .base import Element

if TYPE_CHECKING:
    from ..card import Card


@dataclass(slots=True)
class Button(Element[None, Any]):
    """A button controlled through the reference returned at construction."""

    label: str
    callback: TriggerCallback | None = None
    state: str = "normal"
    color: str = "blue"
    font_scale: float = field(default=1.0, kw_only=True)
    log_level: str | int = field(default="INFO", kw_only=True)
    log_levels: dict[str, str | int] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    id: str = field(default_factory=lambda: uuid4().hex, init=False, repr=False)
    _control: ButtonControl | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _initial_state: str = field(init=False, repr=False, compare=False)
    _initial_label: str = field(init=False, repr=False, compare=False)
    _ui_wait_for_callback: bool = field(
        default=False, init=False, repr=False, compare=False
    )
    _ui_busy: bool = field(default=False, init=False, repr=False, compare=False)

    _binding_lock: ClassVar = RLock()

    def __post_init__(self) -> None:
        if not isinstance(self.label, str):
            raise TypeError("button label must be a string")
        if not isinstance(self.state, str):
            raise TypeError("button state must be a string")
        if self.state not in {"normal", "disabled"}:
            raise ValueError("button state must be 'normal' or 'disabled'")
        if not isinstance(self.color, str):
            raise TypeError("button color must be a string")
        if self.color not in theme.BUTTON_COLOR_PALETTES:
            choices = ", ".join(theme.BUTTON_COLOR_PALETTES)
            raise ValueError(f"button color must be one of: {choices}")
        validate_trigger_callback(self.callback)
        _normalize_level(self.log_level)
        self._initial_state = self.state
        self._initial_label = self.label

    @property
    def initial_value(self) -> None:
        return None

    def normalize(self, value: Any) -> None:
        raise TypeError(
            "Button does not accept values; use configure() to change state or label"
        )

    def set(self, value: Any) -> None:
        self.normalize(value)

    def reset(self) -> None:
        """Restore the state and label supplied at construction."""
        with self._operation():
            if self._owner is None:
                self.state = self._initial_state
                self.label = self._initial_label
            else:
                self.configure(state=self._initial_state, label=self._initial_label)

    def configure(self, *, state: str | None = None, label: str | None = None) -> None:
        if self._control is None:
            raise RuntimeError("button is not attached to a card")
        self._control.configure(state=state, label=label)

    def disable(self, *, label: str | None = None) -> None:
        self.configure(state="disabled", label=label)

    def enable(self, *, label: str | None = None) -> None:
        self.configure(state="normal", label=label)

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> Any:
        """Create the control; the container chooses pack or grid placement."""
        import customtkinter as ctk

        def pressed() -> None:
            if self._ui_busy:
                return
            if self._ui_wait_for_callback:
                self._ui_busy = True
                self.update_state_ui(control, self.state, self.label)
            emit(_BtnPressed(self.id))

        control = ctk.CTkButton(
            parent,
            font=self._scaled_font(),
            text=self.label,
            state=self.state,
            fg_color=self.disabled_color
            if self.state == "disabled"
            else self.active_color,
            hover_color=self.hover_color,
            text_color=theme.BUTTON_FONT_COLOR,
            text_color_disabled=theme.BUTTON_DISABLED_FONT_COLOR,
            width=1,
            command=pressed,
        )
        return control

    def update_state_ui(self, control: Any, state: str, label: str) -> None:
        self.state, self.label = state, label
        effective_state = "disabled" if self._ui_busy else state
        control.configure(
            state=effective_state,
            text=label,
            fg_color=(
                self.disabled_color
                if effective_state == "disabled"
                else self.active_color
            ),
        )

    def _ui_copy(self) -> "Button":
        button = copy(self)
        button._ui_wait_for_callback = self.callback is not None
        button._ui_busy = False
        button.callback = None
        button._control = None
        return button

    @property
    def active_color(self) -> str:
        return theme.BUTTON_COLOR_PALETTES[self.color][0]

    @property
    def hover_color(self) -> str:
        return theme.BUTTON_COLOR_PALETTES[self.color][1]

    @property
    def disabled_color(self) -> str:
        return theme.BUTTON_COLOR_PALETTES[self.color][2]


# Backward-compatible alias for the original public name.
Btn = Button


@dataclass(frozen=True, slots=True)
class _BtnPressed:
    """Pickleable UI-process payload for a button press."""

    button_id: str


class ButtonControl(Trigger):
    """Typed trigger and state controller for a button owned by a Card."""

    def __init__(
        self, button: Button, owner: Card | None = None, *,
        log_level: str | int | None = None,
    ):
        if not isinstance(button, Button):
            raise TypeError("button must be a Button")
        self.button = button
        self._owner = owner
        super().__init__(
            callback=button.callback,
            log_level=button.log_level if log_level is None else log_level,
        )

    @property
    def button_id(self) -> str:
        return self.button.id

    def configure(self, *, state: str | None = None, label: str | None = None) -> None:
        """Update this button through its containing widget."""
        if self._owner is None:
            raise RuntimeError("this button is not attached to a widget")
        self._owner._set_button(self.button_id, state=state, label=label)

    def disable(self, *, label: str | None = None) -> None:
        """Disable the button, optionally replacing its label."""
        self.configure(state="disabled", label=label)

    def enable(self, *, label: str | None = None) -> None:
        """Enable the button, optionally replacing its label."""
        self.configure(state="normal", label=label)

    def start(self) -> None:
        with self._message_lock:
            self._stop_event.clear()
            self.is_stopped = False

    def watching_loop(self) -> None:
        self._stop_event.wait()

    def stop(self) -> None:
        with self._message_lock:
            self._stop_event.set()
            self.is_stopped = True

    def _press(self) -> None:
        self._set_event(
            TriggerMessage(
                timestamp=self.get_timestamp(),
                data={"button_id": self.button_id},
            )
        )

    def _complete_message(self) -> None:
        super()._complete_message()
        if self._owner is not None and self.callback is not None:
            self._owner._button_finished(self.button_id)


__all__ = ["Button", "Btn", "ButtonControl"]
