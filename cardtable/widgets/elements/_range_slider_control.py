"""Tk canvas control for the two handles of a range slider."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from .. import theme


class _RangeSliderControl(ctk.CTkFrame):
    """A single track with independently draggable lower and upper handles."""

    _HANDLE_RADIUS = 8

    def __init__(
        self,
        parent: Any,
        *,
        minimum: float,
        maximum: float,
        step: float,
        value: tuple[float, float],
        command: Callable[[str, float], None],
    ) -> None:
        super().__init__(parent, height=24, fg_color="transparent")
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._value = value
        self._command = command
        self._state = "normal"
        self._active_bound = "lower"
        self._canvas = tk.Canvas(
            self,
            height=24,
            highlightthickness=0,
            bd=0,
            bg=self._background_color(parent),
        )
        self._canvas.pack(fill="x", expand=True)
        self._canvas.bind("<Configure>", self._render_track)
        self._canvas.bind("<Button-1>", self._press)
        self._canvas.bind("<B1-Motion>", self._drag)

    @staticmethod
    def _background_color(widget: Any) -> str:
        current = widget
        while current is not None:
            try:
                color = current.cget("fg_color")
                if color != "transparent":
                    return current._apply_appearance_mode(color)
            except (AttributeError, ValueError, tk.TclError):
                pass
            current = getattr(current, "master", None)
        return theme.color(theme.FALLBACK_BG_COLOR)

    @staticmethod
    def _theme_color(name: str) -> str:
        color = ctk.ThemeManager.theme["CTkSlider"][name]
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]

    def configure(self, require_redraw: bool = False, **kwargs: Any) -> None:
        state = kwargs.pop("state", None)
        if state is not None:
            self._state = state
            self._render_track()
        if kwargs or require_redraw:
            super().configure(require_redraw=require_redraw, **kwargs)

    def set(self, value: tuple[float, float]) -> None:
        self._value = value
        self._render_track()

    def _x_for(self, value: float) -> float:
        usable = max(1, self._canvas.winfo_width() - 2 * self._HANDLE_RADIUS)
        fraction = (value - self._minimum) / (self._maximum - self._minimum)
        return self._HANDLE_RADIUS + fraction * usable

    def _value_for(self, x: float) -> float:
        usable = max(1, self._canvas.winfo_width() - 2 * self._HANDLE_RADIUS)
        fraction = min(1.0, max(0.0, (x - self._HANDLE_RADIUS) / usable))
        raw = self._minimum + fraction * (self._maximum - self._minimum)
        steps = round((raw - self._minimum) / self._step)
        return min(self._maximum, self._minimum + steps * self._step)

    def _render_track(self, _event: Any = None) -> None:
        canvas = self._canvas
        canvas.delete("all")
        lower_x, upper_x = (self._x_for(value) for value in self._value)
        center = 12
        track_color = self._theme_color("fg_color")
        selected_color = self._theme_color("progress_color")
        handle_color = self._theme_color("button_color")
        if self._state == "disabled":
            selected_color = handle_color = track_color
        canvas.create_line(
            self._HANDLE_RADIUS,
            center,
            max(self._HANDLE_RADIUS, canvas.winfo_width() - self._HANDLE_RADIUS),
            center,
            fill=track_color,
            width=6,
            capstyle="round",
        )
        canvas.create_line(
            lower_x,
            center,
            upper_x,
            center,
            fill=selected_color,
            width=6,
            capstyle="round",
        )
        for x in (lower_x, upper_x):
            canvas.create_oval(
                x - self._HANDLE_RADIUS,
                center - self._HANDLE_RADIUS,
                x + self._HANDLE_RADIUS,
                center + self._HANDLE_RADIUS,
                fill=handle_color,
                outline="",
            )

    def _press(self, event: Any) -> None:
        if self._state == "disabled":
            return
        lower_x, upper_x = (self._x_for(value) for value in self._value)
        self._active_bound = (
            "lower" if abs(event.x - lower_x) <= abs(event.x - upper_x) else "upper"
        )
        self._move(event.x)

    def _drag(self, event: Any) -> None:
        if self._state != "disabled":
            self._move(event.x)

    def _move(self, x: float) -> None:
        value = self._value_for(x)
        lower, upper = self._value
        if self._active_bound == "lower":
            lower = min(value, upper)
        else:
            upper = max(value, lower)
        self._value = (lower, upper)
        self._render_track()
        self._command(self._active_bound, value)
