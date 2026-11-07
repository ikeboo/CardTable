"""Decorative separators for declarative card layouts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import theme
from .._layout import element_padding
from .base import Element


@dataclass(slots=True)
class Separator(Element[None, Any]):
    """A horizontal separator, optionally followed by a section label."""

    label: str | None = None
    font_scale: float = field(default=1.0, kw_only=True)
    log_level: str | int = field(
        default="DEBUG", kw_only=True, repr=False, compare=False
    )
    log_levels: dict[str, str | int] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _initial_label: str | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")
        self._initial_label = self.label

    @property
    def initial_value(self) -> None:
        return None

    def normalize(self, value: Any) -> None:
        raise TypeError("Separator does not accept values")

    def set(self, value: Any) -> None:
        self.normalize(value)

    def reset(self) -> None:
        """Restore the label supplied at construction."""
        with self._operation():
            self.label = self._initial_label
            self._commit(None)

    def display_value(self, value: None) -> str | None:
        return self.label

    def update_ui(self, value: str | None) -> None:
        self._ui.configure(text=value or "")
        if value is None:
            self._ui.pack_forget()
        else:
            self._ui.pack(fill="x", pady=(4, 0))

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        import customtkinter as ctk

        section = ctk.CTkFrame(parent, fg_color="transparent")
        section.pack(fill="x", **element_padding(parent, pady=6))
        line = ctk.CTkFrame(
            section,
            height=2,
            corner_radius=0,
            border_width=0,
            fg_color=theme.SEPARATOR_COLOR,
        )
        # Keep geometry management from collapsing the separator's requested
        # height. This is especially important at non-default display scaling.
        line.pack_propagate(False)
        line.pack(fill="x")
        self._ui = ctk.CTkLabel(
            section, text=self.label or "", anchor="w", font=self._scaled_font()
        )
        self.update_ui(self.label)


__all__ = ["Separator"]
