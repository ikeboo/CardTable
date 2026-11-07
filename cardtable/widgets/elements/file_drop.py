"""FileDrop input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._cursor import CLICK_CURSOR
from ._file_selection import Selection, _choose_path, _FileSelection
from ._input import _InputUI


@dataclass(slots=True)
class FileDrop(_FileSelection):
    """Select paths by dropping them or clicking to open a native dialog.

    Restrictions and values follow FileDialog. Invalid selections preserve the
    previous value and show an error below the drop area.
    """

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _FileDropUI(self, emit)

    text: str = "Drop a file or click here to select"
    label: str | None = None
    extensions: str | tuple[str, ...] | list[str] = ()
    directory: bool = False
    multiple: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        _FileSelection.__post_init__(self)


def _file_drop_text(element: FileDrop, value: Selection) -> str:
    if not value:
        return element.text
    paths = value if isinstance(value, tuple) else (value,)
    return "; ".join(Path(path).name for path in paths)


def _ellipsize(text: str, max_width: int, measure: Callable[[str], int]) -> str:
    """Fit text to a pixel width, preserving as much prefix as possible."""
    if max_width <= 0:
        return ""
    if measure(text) <= max_width:
        return text
    suffix = "..."
    if measure(suffix) > max_width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle] + suffix) <= max_width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + suffix


class _FileDropUI(_InputUI):
    __slots__ = (
        "_file_drop_label",
        "_file_drop_value",
        "_file_drop_prompt",
        "_file_drop_text_color",
        "_error",
        "_parent",
        "_drop_targets",
    )

    def build(self, parent: Any) -> None:
        import customtkinter as ctk

        self._parent = parent
        element = self.element
        self._disabled = False
        from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

        root = parent.winfo_toplevel()
        if not getattr(root, "_cardtable_dnd_ready", False):
            TkinterDnD._require(root)
            root._cardtable_dnd_ready = True

        row = self._row(parent)
        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        if element.label is not None:
            label.pack(fill="x", pady=(0, 4))
        self._label = label
        drop_area = ctk.CTkFrame(
            row,
            height=56,
            corner_radius=6,
            border_width=1,
            border_color=("gray60", "gray45"),
            fg_color=("gray92", "gray20"),
        )
        drop_area.pack(fill="x", expand=True)
        drop_area.pack_propagate(False)
        drop_icon = ctk.CTkLabel(
            drop_area,
            text="⇩",
            height=18,
            anchor="center",
            font=element._scaled_font(),
            fg_color="transparent",
        )
        drop_icon.pack(fill="x", padx=6, pady=(4, 0))
        drop_label = ctk.CTkLabel(
            drop_area,
            font=element._scaled_font(),
            text=_file_drop_text(element, element.initial_value),
            height=22,
            anchor="center",
            fg_color="transparent",
        )
        # Tk child widgets are not clipped to their parent's rounded outline;
        # both labels stay inside the curved corners.
        drop_label.pack(fill="x", expand=True, padx=6, pady=(0, 4))
        self._file_drop_label = drop_label
        self._file_drop_value = element.initial_value
        self._file_drop_prompt = element.text
        self._file_drop_text_color = drop_label.cget("text_color")
        self._error = ctk.CTkLabel(
            row,
            font=element._scaled_font(),
            text="",
            anchor="w",
            text_color=("red4", "salmon"),
        )
        self._controls = []
        self._drop_targets = (drop_area, drop_icon, drop_label)
        drop_label.bind(
            "<Configure>",
            lambda event, current=element: self._render_file_drop(current, event.width),
        )

        def receive_drop(event: Any) -> str:
            if self._disabled or self._applying_update:
                return REFUSE_DROP
            paths = drop_label.tk.splitlist(event.data)
            if not paths or (not element.multiple and len(paths) != 1):
                self._show_error(
                    "Drop exactly one path." if paths else "No paths dropped."
                )
                return REFUSE_DROP
            value = tuple(paths) if element.multiple else paths[0]
            return COPY if self._accept_selection(value) else REFUSE_DROP

        for target in self._drop_targets:
            target.configure(cursor=CLICK_CURSOR)
            target.bind("<Button-1>", lambda event: self._choose())
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", receive_drop)

    def _show_error(self, message: str) -> None:
        self._error.configure(text=message)
        self._error.pack(fill="x", pady=(4, 0))

    def _accept_selection(self, value: Any) -> bool:
        try:
            normalized = self.element.normalize(value)
        except (TypeError, ValueError, OSError) as error:
            self._show_error(str(error))
            return False
        self._file_drop_value = normalized
        self._error.pack_forget()
        self._render_file_drop(self.element)
        self._emit(normalized)
        return True

    def _choose(self) -> None:
        if self._disabled or self._applying_update:
            return
        selected = _choose_path(self.element, self._parent, self._file_drop_value)
        if selected:
            self._accept_selection(selected)

    def _render_file_drop(self, element: FileDrop, width: int | None = None) -> None:
        label = self._file_drop_label
        available_width = label.winfo_width() if width is None else width
        value = self._file_drop_value
        text = _file_drop_text(element, value)
        label.configure(text=_ellipsize(text, available_width, label._font.measure))

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._file_drop_value = normalized
        self._error.pack_forget()
        self._render_file_drop(self.element)

    def update_state(self, state: str, label: str | None) -> None:
        self._disabled = state == "disabled"
        for target in self._drop_targets:
            target.configure(cursor="" if self._disabled else CLICK_CURSOR)
        self._file_drop_label.configure(
            text_color=("gray60", "gray45")
            if self._disabled
            else self._file_drop_text_color
        )
        if label is not None:
            heading = self._label
            if not heading.winfo_manager():
                heading.pack(fill="x", pady=(0, 4), before=self._file_drop_label.master)
            heading.configure(text=label)


__all__ = ["FileDrop"]
