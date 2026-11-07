"""Shared input lifecycle, state updates and UI renderer support."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .._layout import element_padding
from .base import Element as BaseElement

if TYPE_CHECKING:
    import customtkinter as ctk

Value = TypeVar("Value")
InputValue = TypeVar("InputValue")
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InputEvent(Generic[Value]):
    """A user input and its normalized value, delivered to its element."""

    element: InputElement[Value, Any]
    value: Value


@dataclass(kw_only=True)
class InputElement(BaseElement[Value, InputValue]):
    """A typed input whose build, value and state hooks run in the UI process."""

    font_scale: float = field(default=1.0, kw_only=True)
    log_level: str | int = field(default="DEBUG", repr=False, compare=False)
    log_levels: dict[str, str | int] | None = field(
        default=None, repr=False, compare=False
    )
    on_input: Callable[[InputEvent[Value]], None] | None = field(
        default=None, repr=False, compare=False
    )

    def _validate_declaration(self) -> None:
        if self.on_input is not None and not callable(self.on_input):
            raise TypeError("on_input must be callable or None")

    def _notify_input(self, value: Value) -> None:
        callback = self.on_input
        if callback is not None:
            try:
                callback(InputEvent(self, value))
            except Exception:
                _logger.exception("InputElement on_input callback failed")

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        state["on_input"] = None
        return state

    @property
    def display_label(self) -> str:
        return getattr(self, "label", None) or ""

    def disable(self, *, label: str | None = None) -> None:
        self._set_state("disabled", label)

    def enable(self, *, label: str | None = None) -> None:
        self._set_state("normal", label)

    def _set_state(self, state: str, label: str | None) -> None:
        with self._synchronized():
            if self._owner is None:
                raise RuntimeError("input element is not attached to a card")
            self._owner._set_element_state(self.name, state=state, label=label)

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__} must implement build_ui(parent, emit)"
        )

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        self._ui = self._create_renderer(emit)
        self._ui.build(parent)

    def update_ui(self, value: Any) -> None:
        self._ui._applying_update = True
        try:
            self._ui.update(value)
        finally:
            self._ui._applying_update = False

    def update_state_ui(self, state: str, label: str | None) -> None:
        self._ui.update_state(state, label)


class _InputUI:
    __slots__ = (
        "element",
        "_emit",
        "_applying_update",
        "_disabled",
        "_label",
        "_controls",
    )

    normal_state = "normal"

    def __init__(self, element: Any, emit: Callable[[Any], None]) -> None:
        self.element = element
        self._emit = emit
        self._applying_update = False

    def update_state(self, state: str, label: str | None) -> None:
        self._disabled = state == "disabled"
        for control in self._controls:
            control.configure(state=self.normal_state if state == "normal" else state)
        if label is not None:
            self._label.configure(text=label)

    @staticmethod
    def _row(parent: Any) -> ctk.CTkFrame:
        import customtkinter as ctk

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", **element_padding(parent))
        return row

    def _emit_variable(self, element: InputElement) -> None:
        if self._applying_update:
            return
        value = element.normalize(self._variable.get())
        self._emit(value)


__all__ = ["InputElement", "InputEvent"]
