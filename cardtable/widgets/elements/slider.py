"""Slider input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._numeric import _NumericElement, _NumericUI


@dataclass(slots=True)
class Slider(_NumericElement[float, float]):
    """A numeric slider whose values are aligned to ``step``."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _SliderUI(self, emit)

    def _default_value(self) -> float:
        return self.min

    def normalize(self, value: float) -> float:
        return self._normalize_number(value)


class _SliderUI(_NumericUI):
    __slots__ = ("_variable", "_value_label")

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        element = self.element
        row = self._row(parent)
        variable = tk.DoubleVar(master=parent, value=element.initial_value)
        self._variable = variable

        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")
        label = ctk.CTkLabel(
            header, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        label.pack(side="left")
        value_label = ctk.CTkLabel(
            header,
            font=element._scaled_font(),
            text=self._format_number(element.initial_value),
            width=36,
            anchor="e",
        )
        value_label.pack(side="right")
        self._value_label = value_label

        slider = ctk.CTkSlider(
            row,
            from_=element.min,
            to=element.max,
            number_of_steps=element.number_of_steps,
            variable=variable,
            command=lambda value, current=element: self._slider_changed(current, value),
        )
        slider.pack(fill="x", pady=(4, 0))
        self._label = label
        self._controls = [slider]

    def _slider_changed(self, element: Slider, value: float) -> None:
        normalized = element.normalize(value)
        self._variable.set(normalized)
        self._value_label.configure(text=self._format_number(normalized))
        if not self._applying_update:
            self._emit(normalized)

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._variable.set(normalized)
        self._value_label.configure(text=self._format_number(normalized))


__all__ = ["Slider"]
