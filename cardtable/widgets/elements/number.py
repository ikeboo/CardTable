"""Number input validation and UI rendering."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import theme
from ._numeric import _NumericUI
from .slider import Slider


@dataclass(slots=True)
class Number(Slider):
    """A numeric spinbox whose values are aligned to ``step``."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _NumberUI(self, emit)


class _NumberUI(_NumericUI):
    __slots__ = ("_variable", "_number_entry")

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        element = self.element
        row = self._row(parent)
        variable = tk.DoubleVar(master=parent, value=element.initial_value)
        self._variable = variable

        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        label.pack(side="left")
        spinbox = ctk.CTkFrame(row, fg_color="transparent")
        spinbox.pack(side="right", padx=(6, 0))
        value_entry = ctk.CTkEntry(
            spinbox,
            font=element._scaled_font(),
            width=48,
            height=30,
            corner_radius=4,
            justify="right",
        )
        value_entry.insert(0, self._format_number(element.initial_value))
        value_entry.grid(row=0, column=0, rowspan=2, padx=(0, 2))
        value_entry.bind(
            "<Return>",
            lambda _event, current=element: self._commit_number(current),
        )
        value_entry.bind(
            "<FocusOut>",
            lambda _event, current=element: self._commit_number(current),
        )
        increment = ctk.CTkButton(
            spinbox,
            text="▲",
            fg_color=theme.BUTTON_BG_COLOR,
            hover_color=theme.BUTTON_HOVER_COLOR,
            text_color=theme.BUTTON_FONT_COLOR,
            text_color_disabled=theme.BUTTON_DISABLED_FONT_COLOR,
            width=22,
            height=14,
            corner_radius=3,
            font=element._scaled_font(),
            command=lambda current=element: self._number_changed(current, 1),
        )
        increment.grid(row=0, column=1, pady=(0, 1))
        decrement = ctk.CTkButton(
            spinbox,
            text="▼",
            fg_color=theme.BUTTON_BG_COLOR,
            hover_color=theme.BUTTON_HOVER_COLOR,
            text_color=theme.BUTTON_FONT_COLOR,
            text_color_disabled=theme.BUTTON_DISABLED_FONT_COLOR,
            width=22,
            height=14,
            corner_radius=3,
            font=element._scaled_font(),
            command=lambda current=element: self._number_changed(current, -1),
        )
        decrement.grid(row=1, column=1, pady=(1, 0))
        self._number_entry = value_entry
        self._label = label
        self._controls = [value_entry, decrement, increment]

    def _number_changed(self, element: Number, direction: int) -> None:
        current = float(self._variable.get())
        value = min(element.max, max(element.min, current + direction * element.step))
        normalized = element.normalize(value)
        self._set_number_value(element, normalized)
        if not self._applying_update:
            self._emit(normalized)

    def _commit_number(self, element: Number) -> None:
        entry = self._number_entry
        try:
            value = float(entry.get())
        except (TypeError, ValueError):
            self._set_number_value(element, self._variable.get())
            return
        if not math.isfinite(value):
            self._set_number_value(element, self._variable.get())
            return

        clamped = min(element.max, max(element.min, value))
        step_number = math.floor((clamped - element.min) / element.step + 0.5)
        stepped = element.min + step_number * element.step
        normalized = element.normalize(min(element.max, max(element.min, stepped)))
        self._set_number_value(element, normalized)
        if not self._applying_update:
            self._emit(normalized)

    def _set_number_value(self, element: Number, value: float) -> None:
        normalized = element.normalize(value)
        self._variable.set(normalized)
        entry = self._number_entry
        entry.delete(0, "end")
        entry.insert(0, self._format_number(normalized))

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._set_number_value(self.element, normalized)


__all__ = ["Number"]
