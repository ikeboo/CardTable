"""Entry input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._input import InputElement, _InputUI


@dataclass(slots=True)
class Entry(InputElement[str, str]):
    """A text entry, optionally displayed with multiple lines."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _EntryUI(self, emit)

    place_holder: str = ""
    label: str | None = None
    rows: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.place_holder, str):
            raise TypeError("place_holder must be a string")
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")
        if isinstance(self.rows, bool) or not isinstance(self.rows, int):
            raise TypeError("rows must be an int")
        if self.rows < 1:
            raise ValueError("rows must be at least 1")

    @property
    def initial_value(self) -> str:
        return ""

    def normalize(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        return value


class _EntryUI(_InputUI):
    __slots__ = ("_entry",)

    def build(self, parent: Any) -> None:
        import customtkinter as ctk

        element = self.element
        row = self._row(parent)
        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        if element.display_label:
            label.pack(side="left", anchor="n")
        if element.rows == 1:
            entry = ctk.CTkEntry(
                row,
                font=element._scaled_font(),
                placeholder_text=element.place_holder,
            )
        else:
            entry = ctk.CTkTextbox(
                row,
                font=element._scaled_font(),
                height=element.rows * 28 * element.font_scale,
            )
        entry.pack(
            side="right", fill="x", expand=True,
            padx=(12, 0) if element.display_label else 0,
        )
        self._entry = entry
        self._label = label
        self._controls = [entry]
        entry.bind(
            "<KeyRelease>",
            lambda _event, current=element: self._emit_entry(current),
        )
        # Paste and cut may be initiated from a context menu without a key event.
        for event_name in ("<<Paste>>", "<<Cut>>"):
            entry.bind(
                event_name,
                lambda _event, current=element: entry.after_idle(
                    self._emit_entry, current
                ),
            )

    def update_state(self, state: str, label: str | None) -> None:
        super().update_state(state, label)
        if label is not None:
            entry = self._controls[0]
            if label:
                self._label.pack(side="left", anchor="n", before=entry)
            else:
                self._label.pack_forget()
            entry.pack(padx=(12, 0) if label else 0)

    def _emit_entry(self, element: Entry) -> None:
        if not self._applying_update:
            entry = self._entry
            value = entry.get() if element.rows == 1 else entry.get("1.0", "end-1c")
            self._emit(value)

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        entry = self._entry
        current = entry.get() if self.element.rows == 1 else entry.get("1.0", "end-1c")
        if current == normalized:
            return
        first = 0 if self.element.rows == 1 else "1.0"
        entry.delete(first, "end")
        if normalized:
            entry.insert(first, normalized)


__all__ = ["Entry"]
