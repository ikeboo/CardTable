"""Simple text labels with independently updateable colors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .._layout import element_padding
from .base import Element

Color = str | tuple[str, str]
Font = tuple[str, int] | tuple[str, int, str]


def _check_color(color: Color | None, name: str) -> None:
    if color is None:
        return
    if isinstance(color, str):
        colors = (color,)
    elif isinstance(color, tuple) and len(color) == 2:
        colors = color
    else:
        raise TypeError(f"{name} must be a string or a pair of strings")
    if any(not isinstance(value, str) for value in colors):
        raise TypeError(f"{name} must be a string or a pair of strings")
    if any(not value for value in colors):
        raise ValueError(f"{name} must not be empty")
    if name == "text_color" and "transparent" in colors:
        raise ValueError("text_color cannot be transparent")


def _check_font(font: Font | None) -> None:
    if font is not None:
        if (
            not isinstance(font, tuple)
            or len(font) not in {2, 3}
            or not isinstance(font[0], str)
            or isinstance(font[1], bool)
            or not isinstance(font[1], int)
            or (len(font) == 3 and not isinstance(font[2], str))
        ):
            raise TypeError("font must be (family, size[, style]) or None")


class Label(Element[str, str]):
    """Display a string; colors accept a name, hex, or light/dark pair.

    ``bg_color`` fills the label's rounded rectangle. ``font`` is a
    ``(family, size)`` or ``(family, size, style)`` tuple, or None for Tk's standard
    font. ``get()`` returns the current text; ``reset()`` restores text, font,
    and colors supplied at construction.
    """

    def __init__(
        self,
        label: str,
        anchor: str = "w",
        text_color: Color | None = None,
        bg_color: Color = "transparent",
        font: Font | None = None,
        corner_radius: int = 0,
        *,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        self.label = self.normalize(label)
        if not isinstance(anchor, str):
            raise TypeError("anchor must be a string")
        if anchor not in {"n", "ne", "e", "se", "s", "sw", "w", "nw", "center"}:
            raise ValueError("anchor must be a compass direction or 'center'")
        _check_color(text_color, "text_color")
        _check_color(bg_color, "bg_color")
        if bg_color is None:
            raise TypeError("bg_color must be a string or a pair of strings")
        _check_font(font)
        if isinstance(corner_radius, bool) or not isinstance(corner_radius, int):
            raise TypeError("corner_radius must be an int")
        if corner_radius < 0:
            raise ValueError("corner_radius must not be negative")
        self.anchor = anchor
        self.text_color = text_color
        self.bg_color = bg_color
        self.font = font
        self.corner_radius = corner_radius
        self._initial_colors = (text_color, bg_color)
        self._initial_font = font

    @property
    def initial_value(self) -> str:
        return self.label

    def normalize(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("label must be a string")
        return value

    def set(
        self,
        label: str | None = None,
        text_color: Color | None = None,
        bg_color: Color | None = None,
        font: Font | None = None,
    ) -> None:
        """Update supplied fields; omitted fields (or None) keep their value."""
        with self._operation():
            if label is not None:
                self.normalize(label)
            _check_color(text_color, "text_color")
            _check_color(bg_color, "bg_color")
            _check_font(font)
            if font is not None:
                self.font = font
            if text_color is not None:
                self.text_color = text_color
            if bg_color is not None:
                self.bg_color = bg_color
            self._commit(self._value if label is None else label)

    def reset(self) -> None:
        with self._operation():
            self.text_color, self.bg_color = self._initial_colors
            self.font = self._initial_font
            self._commit(self.initial_value)

    def display_value(self, value: str) -> dict[str, Any]:
        with self._synchronized():
            return {
                "label": value,
                "text_color": self.text_color,
                "bg_color": self.bg_color,
                "font": self.font,
            }

    def _ui_font(self, font: Font | None) -> Any:
        return self._scaled_font(font)

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        import customtkinter as ctk

        self._ui = ctk.CTkLabel(
            parent,
            text=self.get(),
            anchor=self.anchor,
            text_color=self.text_color,
            fg_color=self.bg_color,
            font=self._ui_font(self.font),
            corner_radius=self.corner_radius,
        )
        self._ui.pack(fill="x", **element_padding(parent))

    def update_ui(self, value: Any) -> None:
        import customtkinter as ctk

        font = self._ui_font(value["font"])
        self._ui.configure(
            text=self.normalize(value["label"]),
            text_color=(
                ctk.ThemeManager.theme["CTkLabel"]["text_color"]
                if value["text_color"] is None
                else value["text_color"]
            ),
            fg_color=value["bg_color"],
            font=font,
        )


__all__ = ["Label"]
