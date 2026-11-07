"""Buttons that complete a PopupCard without Dealer callback registration."""

from __future__ import annotations

from typing import ClassVar

from .button import Button


class _ResultBtn(Button):
    result: ClassVar[bool | None]

    def __init__(
        self, label: str, *, state: str = "normal", color: str = "blue",
        log_level: str | int = "INFO",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        super().__init__(
            label, state=state, color=color,
            log_level=log_level, log_levels=log_levels, font_scale=font_scale,
        )


class TrueBtn(_ResultBtn):
    """Close the containing PopupCard with True."""

    result = True


class FalseBtn(_ResultBtn):
    """Close the containing PopupCard with False."""

    result = False


class CancelBtn(_ResultBtn):
    """Close the containing PopupCard with None."""

    result = None


__all__ = ["TrueBtn", "FalseBtn", "CancelBtn"]
