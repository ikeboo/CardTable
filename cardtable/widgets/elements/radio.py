"""Radio input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._choice import _ChoiceElement
from ._input import _InputUI


@dataclass(slots=True)
class Radio(_ChoiceElement):
    """A radio group, vertically arranged unless explicitly horizontal."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _RadioUI(self, emit)

    direction: str = "vertical"

    def __post_init__(self) -> None:
        super(Radio, self).__post_init__()
        if self.direction not in {"vertical", "horizontal"}:
            raise ValueError("direction must be 'vertical' or 'horizontal'")


class _RadioUI(_InputUI):
    __slots__ = ("_variable",)

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        element = self.element
        row = self._row(parent)
        variable = tk.StringVar(master=parent, value=element.initial_value)
        self._variable = variable

        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        options = ctk.CTkFrame(row, fg_color="transparent")
        label.pack(side="left", anchor="n")
        options.pack(side="left", fill="x", expand=True, padx=(12, 0))

        controls = []
        for value in element.values:
            radio_button = ctk.CTkRadioButton(
                options,
                font=element._scaled_font(),
                text=value,
                value=value,
                variable=variable,
                command=lambda current=element: self._emit_variable(current),
            )
            if element.direction == "vertical":
                radio_button.pack(fill="x", pady=2)
            else:
                radio_button.pack(side="left", padx=(0, 12))
            controls.append(radio_button)
        self._label = label
        self._controls = controls

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._variable.set(normalized)


__all__ = ["Radio"]
