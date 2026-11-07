"""ComboBox input validation and UI rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._choice import _ChoiceElement
from ._input import _InputUI


def _dropdown_index(menu: Any, index: Any) -> int | None:
    """Read Tk 9's empty menu index without Python 3.10's integer conversion."""
    value = menu.tk.call(menu._w, "index", index)
    return None if value in ("", "none") else menu.tk.getint(value)


@dataclass(slots=True)
class ComboBox(_ChoiceElement):
    """A read-only combo box; the first value is selected by default."""

    def _create_renderer(self, emit: Callable[[Any], None]) -> Any:
        return _ComboBoxUI(self, emit)


class _ComboBoxUI(_InputUI):
    __slots__ = ("_variable",)

    normal_state = "readonly"

    def build(self, parent: Any) -> None:
        import tkinter as tk

        import customtkinter as ctk
        from customtkinter.windows.widgets.core_widget_classes import DropdownMenu

        # CTkComboBox constructs an empty DropdownMenu and immediately deletes
        # its entries. Tk 9 returns "" for that menu's index; Python 3.10's
        # Menu.index tries to parse it as an integer. Limit the fix to CTk menus.
        DropdownMenu.index = _dropdown_index

        element = self.element
        row = self._row(parent)
        label = ctk.CTkLabel(
            row, font=element._scaled_font(), text=element.display_label, anchor="w"
        )
        label.pack(side="left")
        variable = tk.StringVar(master=parent, value=element.initial_value)
        self._variable = variable
        combo_box = ctk.CTkComboBox(
            row,
            font=element._scaled_font(),
            dropdown_font=element._scaled_font(),
            values=list(element.values),
            variable=variable,
            state="readonly",
            command=lambda _value, current=element: self._emit_variable(current),
        )
        combo_box.pack(side="right", fill="x", expand=True, padx=(12, 0))
        self._label = label
        self._controls = [combo_box]

    def update(self, value: Any) -> None:
        normalized = self.element.normalize(value)
        self._variable.set(normalized)


__all__ = ["ComboBox"]
