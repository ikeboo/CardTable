"""Switch input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._boolean import _BooleanElement
from ._input import _InputUI


@dataclass(slots=True)
class Switch(_BooleanElement):
    """An on/off switch."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _SwitchUI(self, emit)


class _SwitchUI(_InputUI):
    __slots__ = ("_variable",)

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        element = self.element
        row = self._row(parent)
        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        label.pack(side="left")
        variable = tk.BooleanVar(master=parent, value=element.initial_value)
        self._variable = variable
        control = ctk.CTkSwitch(
            row,
            font=element._scaled_font(),
            text="",
            width=36,
            variable=variable,
            onvalue=True,
            offvalue=False,
            command=lambda current=element: self._emit_variable(current),
        )
        control.pack(side="right", padx=(12, 0))
        self._label = label
        self._controls = [control]

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._variable.set(normalized)


__all__ = ["Switch"]
