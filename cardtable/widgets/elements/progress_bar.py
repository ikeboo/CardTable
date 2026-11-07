"""Numeric progress with a configurable moving two-color gradient."""

from __future__ import annotations

import math
from collections.abc import Callable
from numbers import Real
from typing import Any

from .._layout import element_padding
from .base import Element


def _number(value: int | float, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _hex_color(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a hex color string")
    if (
        len(value) not in (4, 7)
        or not value.startswith("#")
        or any(c not in "0123456789abcdefABCDEF" for c in value[1:])
    ):
        raise ValueError(f"{name} must be #RGB or #RRGGBB")
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    return value.upper()


class ProgressBar(Element[int | float, int | float]):
    """Display progress, status text, and the raw value followed by ``unit``.

    ``max=None`` uses 100 as the full-scale value. Only the fill is clamped
    to 0–100%; ``get()`` and the caption retain the supplied numeric value.
    Omitting ``text`` in ``set`` preserves the current caption. ``reset()``
    restores zero and the constructor's ``label``.
    ``color_0`` and ``color_1`` accept #RGB or #RRGGBB hex colors.
    """

    def __init__(
        self,
        label: str = "",
        unit: str = "%",
        max: int | float | None = None,
        *,
        color_0: str = "#8F4A8F",
        color_1: str = "#FFD0F8",
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not isinstance(unit, str):
            raise TypeError("unit must be a string")
        if max is not None and _number(max, "max") <= 0:
            raise ValueError("max must be positive")
        self.color_0 = _hex_color(color_0, "color_0")
        self.color_1 = _hex_color(color_1, "color_1")
        self.label = label
        self.unit = unit
        self.max = max
        self.text = label

    @property
    def initial_value(self) -> int | float:
        return 0

    def normalize(self, value: int | float) -> int | float:
        return _number(value, "value")

    def set(self, value: int | float, text: str | None = None) -> None:
        with self._operation():
            normalized = self.normalize(value)
            if text is not None and not isinstance(text, str):
                raise TypeError("text must be a string or None")
            if text is not None:
                self.text = text
            self._commit(normalized)

    def reset(self) -> None:
        with self._operation():
            self.text = self.label
            self._commit(self.initial_value)

    def display_value(self, value: int | float) -> dict[str, Any]:
        with self._synchronized():
            maximum = 100 if self.max is None else self.max
            return {
                "fraction": min(1.0, max(0.0, value / maximum)),
                "text": self.text,
                "caption": f"{value}{self.unit}",
            }

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        from ._progress_bar_control import _ProgressBarControl

        self._ui = _ProgressBarControl(
            parent,
            color_0=self.color_0,
            color_1=self.color_1,
            font_scale=self.font_scale,
        )
        self._ui.pack(fill="x", **element_padding(parent))
        self.update_ui(self.display_value(self.get()))

    def update_ui(self, value: Any) -> None:
        self._ui.set(value["fraction"], value["text"], value["caption"])


__all__ = ["ProgressBar"]
