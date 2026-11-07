"""RangeSlider input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ._numeric import _NumericElement, _NumericUI


@dataclass(slots=True)
class RangeSlider(_NumericElement[tuple[float, float], Sequence[float]]):
    """A pair of handles for selecting inclusive lower and upper values."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _RangeSliderUI(self, emit)

    def _default_value(self) -> tuple[float, float]:
        return self.min, self.max

    def normalize(self, value: Sequence[float]) -> tuple[float, float]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise TypeError("value must be a two-item numeric sequence")
        values = tuple(value)
        if len(values) != 2:
            raise ValueError("value must contain two values")
        lower, upper = (self._normalize_number(item) for item in values)
        if lower > upper:
            raise ValueError("lower value must not exceed upper value")
        return lower, upper


class _RangeSliderUI(_NumericUI):
    __slots__ = ("_range_variable", "_range_control", "_value_label")

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk

        from ._range_slider_control import _RangeSliderControl

        element = self.element
        row = self._row(parent)
        lower, upper = element.initial_value
        lower_variable = tk.DoubleVar(master=parent, value=lower)
        upper_variable = tk.DoubleVar(master=parent, value=upper)
        self._range_variable = (lower_variable, upper_variable)

        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")
        label = ctk.CTkLabel(
            header, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        label.pack(side="left")
        value_label = ctk.CTkLabel(
            header,
            font=element._scaled_font(),
            text=self._format_range(element.initial_value),
            width=72,
            anchor="e",
        )
        value_label.pack(side="right")
        self._value_label = value_label

        slider = _RangeSliderControl(
            row,
            minimum=element.min,
            maximum=element.max,
            step=element.step,
            value=element.initial_value,
            command=lambda bound, value, current=element: self._range_slider_changed(
                current, bound, value
            ),
        )
        slider.pack(fill="x", pady=(4, 0))
        self._range_control = slider
        self._label = label
        self._controls = [slider]

    def _range_slider_changed(
        self, element: RangeSlider, bound: str, value: float
    ) -> None:
        lower_variable, upper_variable = self._range_variable
        lower = float(lower_variable.get())
        upper = float(upper_variable.get())
        normalized = element._normalize_number(value)
        if bound == "lower":
            lower = min(normalized, upper)
        else:
            upper = max(normalized, lower)
        result = element.normalize((lower, upper))
        lower_variable.set(result[0])
        upper_variable.set(result[1])
        self._range_control.set(result)
        self._value_label.configure(text=self._format_range(result))
        if not self._applying_update:
            self._emit(result)

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        lower, upper = self._range_variable
        lower.set(normalized[0])
        upper.set(normalized[1])
        self._range_control.set(normalized)
        self._value_label.configure(text=self._format_range(normalized))

    @classmethod
    def _format_range(cls, value: tuple[float, float]) -> str:
        return f"{cls._format_number(value[0])} – {cls._format_number(value[1])}"


__all__ = ["RangeSlider"]
