"""Selectable, read-only text for the main window's status bar."""

import tkinter as tk
from typing import Any

import customtkinter as ctk

from . import theme


class StatusText(ctk.CTkEntry):
    """Keep label-like sizing while allowing native selection and copying."""

    def __init__(self, master: Any, *, height: int) -> None:
        self._status_value = tk.StringVar(master=master, value="")
        self._status_font = ctk.CTkFont(size=11)
        super().__init__(
            master,
            textvariable=self._status_value,
            state="readonly",
            width=1,
            height=height,
            corner_radius=0,
            border_width=0,
            fg_color=theme.STATUS_BAR_BG_COLOR,
            text_color=theme.STATUS_BAR_FONT_COLOR,
            font=self._status_font,
        )

    def configure(self, require_redraw: bool = False, **kwargs: Any) -> None:
        if "text" in kwargs:
            text = kwargs.pop("text")
            if text != self._status_value.get():
                self._status_value.set(text)
                # CTkEntry reserves six logical pixels on each side.
                kwargs.setdefault("width", self._status_font.measure(text) + 12)
        super().configure(require_redraw=require_redraw, **kwargs)
