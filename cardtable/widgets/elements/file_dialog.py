"""Native file/directory selection with a persistent path display."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import theme
from ._file_selection import Selection, _choose_path, _FileSelection
from ._input import _InputUI


@dataclass(slots=True)
class FileDialog(_FileSelection):
    """Select an existing file, or a directory when ``directory=True``.

    ``extensions`` accepts a single extension or a tuple/list, with or without
    a leading dot (or ``*.``). An empty tuple allows all files. Extensions
    are ignored in directory mode. Values are absolute paths, initially None.
    With ``multiple=True``, file paths are stored as a tuple, initially empty.
    Multiple directory selection is not supported by the native dialog.
    """

    extensions: str | tuple[str, ...] | list[str] = ()
    directory: bool = False
    label: str | None = None
    multiple: bool = False

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _FileDialogUI(self, emit)


class _FileDialogUI(_InputUI):
    __slots__ = ("_path", "_selected_path", "_parent")

    def build(self, parent: Any) -> None:
        import customtkinter as ctk

        self._parent = parent
        self._disabled = False
        self._selected_path = self.element.initial_value
        row = self._row(parent)
        self._label = ctk.CTkLabel(
            row,
            font=self.element._scaled_font(),
            text=self.element.display_label,
            anchor="w",
        )
        if self.element.label is not None:
            self._label.pack(side="left", padx=(0, 12))
        button = ctk.CTkButton(
            row,
            font=self.element._scaled_font(),
            text="...",
            width=32,
            fg_color=theme.BUTTON_BG_COLOR,
            hover_color=theme.BUTTON_HOVER_COLOR,
            text_color=theme.BUTTON_FONT_COLOR,
            text_color_disabled=theme.BUTTON_DISABLED_FONT_COLOR,
            command=self._choose,
        )
        button.pack(side="right", padx=(6, 0))
        self._path = ctk.CTkEntry(
            row, font=self.element._scaled_font(), state="readonly"
        )
        self._path.pack(side="left", fill="x", expand=True)
        self._controls = [button]

    def _choose(self) -> None:
        if self._disabled or self._applying_update:
            return
        selected = _choose_path(self.element, self._parent, self._selected_path)
        if selected:
            # Paint the selection before controller-side filesystem validation.
            value = (
                tuple(os.path.abspath(os.path.expanduser(path)) for path in selected)
                if self.element.multiple
                else os.path.abspath(os.path.expanduser(selected))
            )
            self._show_path(value)
            self._emit(value)

    def _show_path(self, value: Selection) -> None:
        self._selected_path = value
        self._path.configure(state="normal")
        self._path.delete(0, "end")
        if value is not None:
            text = "; ".join(value) if isinstance(value, tuple) else value
            self._path.insert(0, text)
        self._path.configure(state="disabled" if self._disabled else "readonly")

    def update(self, value: Any) -> None:
        self._show_path(self.element.normalize(value))

    def update_state(self, state: str, label: str | None) -> None:
        super().update_state(state, label)
        self._path.configure(state="disabled" if self._disabled else "readonly")
        if label is not None and not self._label.winfo_manager():
            self._label.pack(side="left", padx=(0, 12), before=self._path)


__all__ = ["FileDialog"]
