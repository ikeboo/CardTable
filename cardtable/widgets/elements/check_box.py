"""CheckBox input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .._layout import element_padding
from ._boolean import _BooleanElement
from ._input import _InputUI


@dataclass(slots=True)
class CheckBox(_BooleanElement):
    """A check box."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _CheckBoxUI(self, emit)


class _CheckBoxUI(_InputUI):
    __slots__ = ("_variable",)

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        element = self.element
        variable = tk.BooleanVar(master=parent, value=element.initial_value)
        self._variable = variable
        control = ctk.CTkCheckBox(
            parent,
            font=element._scaled_font(),
            text=element.display_label,
            variable=variable,
            onvalue=True,
            offvalue=False,
            command=lambda current=element: self._emit_variable(current),
        )
        control.pack(fill="x", **element_padding(parent))
        self._label = control
        self._controls = [control]

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._variable.set(normalized)


__all__ = ["CheckBox"]
