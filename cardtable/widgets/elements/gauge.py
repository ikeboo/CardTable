"""A lightweight, read-only semicircular needle gauge."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

from PIL import ImageColor

from .._layout import element_padding
from .base import Element
from .progress_bar import _number


class Gauge(Element[int | float | None, int | float]):
    """Display numeric values on a segmented half ring.

    ``boundaries`` are strictly increasing; each adjacent pair uses one color.
    The needle clamps to the scale, while the caption and ``get()`` retain the
    original number and its type. The initial value defaults to the lower bound.
    The central caption uses four significant digits, including trailing zeros,
    and scientific notation when needed to fit.
    This is a display: ``enabled`` changes its appearance, not mouse interaction.
    ``clear()`` hides the needle and caption and makes ``get()`` return None.
    Colors accept Pillow color names and hex strings. ``configure`` accepts
    label, unit, colors, enabled, width, height, font_scale, bg_color and font_color.
    ``font_scale`` scales only the label; dial text fits the gauge geometry.
    None for either appearance color selects the theme's default.
    """

    def __init__(
        self,
        boundaries: Sequence[int | float] = (0, 50, 70, 80, 100),
        unit: str = "",
        colors: Sequence[str] | None = None,
        label: str | None = None,
        *,
        enabled: bool = True,
        default_value: int | float | None = None,
        width: int = 320,
        height: int = 210,
        font_scale: float = 1.0,
        bg_color: str | None = None,
        font_color: str | None = None,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
    ) -> None:
        self.boundaries = tuple(_number(v, "boundary") for v in boundaries)
        if len(self.boundaries) < 2 or any(
            b <= a for a, b in zip(self.boundaries, self.boundaries[1:])
        ):
            raise ValueError("boundaries must contain at least two increasing numbers")
        if not math.isfinite(self.boundaries[-1] - self.boundaries[0]):
            raise ValueError("boundary span must be finite")
        self._default_value = (
            self.boundaries[0]
            if default_value is None
            else self.normalize(default_value)
        )
        self._options = self._validated(
            {
                "unit": unit,
                "colors": colors
                if colors is not None
                else ["#53D653"] * (len(self.boundaries) - 1),
                "label": label,
                "enabled": enabled,
                "width": width,
                "height": height,
                "font_scale": font_scale,
                "bg_color": bg_color,
                "font_color": font_color,
            }
        )
        self._initial_options = self._options.copy()

    @property
    def initial_value(self) -> int | float:
        return self._default_value

    @property
    def label(self) -> str | None:
        return self._options["label"]

    @property
    def unit(self) -> str:
        return self._options["unit"]

    @property
    def colors(self) -> tuple[str, ...]:
        return self._options["colors"]

    def normalize(self, value: int | float) -> int | float:
        return _number(value, "value")

    def _validated(self, options: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(options, dict):
            raise TypeError("configure must be a dictionary or None")
        result = options.copy()
        allowed = {
            "label",
            "unit",
            "colors",
            "enabled",
            "width",
            "height",
            "font_scale",
            "bg_color",
            "font_color",
        }
        if unknown := result.keys() - allowed:
            raise TypeError(f"unknown Gauge options: {', '.join(sorted(unknown))}")
        for name, value in result.items():
            if name == "label" and value is not None and not isinstance(value, str):
                raise TypeError("label must be a string or None")
            if name == "unit" and not isinstance(value, str):
                raise TypeError("unit must be a string")
            if name == "enabled" and not isinstance(value, bool):
                raise TypeError("enabled must be a bool")
            if name in {"width", "height", "font_scale"}:
                if _number(value, name) <= 0:
                    raise ValueError(f"{name} must be positive")
            if name in {"bg_color", "font_color"} and value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be a color string or None")
                ImageColor.getrgb(value)
            if name == "colors":
                if isinstance(value, str) or not isinstance(value, Sequence):
                    raise TypeError("colors must be a sequence of color strings")
                value = tuple(value)
                if len(value) != len(self.boundaries) - 1:
                    raise ValueError("one color is required for each boundary interval")
                for color in value:
                    if not isinstance(color, str):
                        raise TypeError("colors must contain strings")
                    ImageColor.getrgb(color)
                result[name] = value
        return result

    def set(self, value: int | float, configure: dict[str, Any] | None = None) -> None:
        with self._operation():
            normalized = self.normalize(value)
            options = self._validated({} if configure is None else configure)
            changed = any(self._options[k] != v for k, v in options.items())
            if not changed and type(normalized) is type(self._value):
                if normalized == self._value:
                    return
            self._options.update(options)
            self.font_scale = self._options["font_scale"]
            self._commit(normalized)

    def configure(self, **kwargs: Any) -> None:
        with self._operation():
            options = self._validated(kwargs)
            if any(self._options[k] != v for k, v in options.items()):
                self._options.update(options)
                self.font_scale = self._options["font_scale"]
                self._commit(self._value)

    def reset(self) -> None:
        with self._operation():
            self._options = self._initial_options.copy()
            self.font_scale = self._options["font_scale"]
            self._commit(self.initial_value)

    def clear(self) -> None:
        with self._operation():
            if self._value is not None:
                self._commit(None)

    def enable(self) -> None:
        self.configure(enabled=True)

    def disable(self) -> None:
        self.configure(enabled=False)

    def is_enabled(self) -> bool:
        with self._synchronized():
            return self._options["enabled"]

    def display_value(self, value: int | float | None) -> dict[str, Any]:
        with self._synchronized():
            return {"value": value, **self._options}

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        from ._gauge_control import _GaugeControl

        self._ui = _GaugeControl(
            parent, self.boundaries, self.display_value(self.get())
        )
        self._ui.pack(fill="x", **element_padding(parent))

    def update_ui(self, value: Any) -> None:
        self._ui.set(value)


__all__ = ["Gauge"]
