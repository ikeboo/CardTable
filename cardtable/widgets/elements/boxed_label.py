"""A centered, bold label with a button-like rounded background."""

from __future__ import annotations

from typing import Any

from .label import Color, Font, Label


class BoxedLabel(Label):
    """A display-only badge with rounded corners and bold, centered text."""

    def __init__(
        self,
        label: str,
        text_color: Color | None = "white",
        bg_color: Color = "#1E88E5",
        font: Font | None = None,
        *,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        super().__init__(
            label,
            anchor="center",
            text_color=text_color,
            bg_color=bg_color,
            font=font,
            font_scale=font_scale,
            corner_radius=6,
            log_level=log_level,
            log_levels=log_levels,
        )

    def _ui_font(self, font: Font | None) -> Any:
        return self._scaled_font(font, bold=True)


__all__ = ["BoxedLabel"]
