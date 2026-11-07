"""Fonts resolved in the UI process from Tk's system default."""

from __future__ import annotations

import math
from numbers import Real


def validate_font_scale(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("font_scale must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("font_scale must be finite and positive")
    return float(value)


def tk_font(scale: float):
    from tkinter import font as tkfont

    font = tkfont.nametofont("TkDefaultFont").copy()
    size = font.cget("size")
    font.configure(size=(1 if size >= 0 else -1) * max(1, round(abs(size) * scale)))
    return font


def ctk_font(scale: float, font=None, *, bold: bool = False):
    from tkinter import font as tkfont

    import customtkinter as ctk

    if font is not None:
        size = font[1]
        result = (font[0], (1 if size >= 0 else -1) * max(1, round(abs(size) * scale)))
        styles = font[2].split() if len(font) == 3 else []
        if bold:
            styles = [s for s in styles if s not in {"normal", "bold"}]
            styles.insert(0, "bold")
        return (*result, " ".join(styles)) if styles else result
    base = tkfont.nametofont("TkDefaultFont")
    # CTkFont sizes are logical pixels; Tk's positive sizes are points.
    size = base.cget("size")
    pixels = abs(size) if size < 0 else size * base._tk.call("tk", "scaling")
    return ctk.CTkFont(
        family=base.actual("family"),
        size=max(1, round(pixels * scale)),
        weight="bold" if bold else base.actual("weight"),
    )
