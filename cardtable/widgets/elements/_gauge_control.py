"""Retained Canvas items: static scale, O(1) needle and caption updates."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Any

import customtkinter as ctk
from PIL import ImageColor


def _color(value: str) -> str:
    return "#%02x%02x%02x" % ImageColor.getrgb(value)[:3]


class _GaugeControl(ctk.CTkBaseClass):
    def __init__(self, parent: Any, boundaries: tuple, payload: dict) -> None:
        super().__init__(parent, width=payload["width"], height=payload["height"])
        from ._fonts import ctk_font

        self._label_font = ctk_font(payload["font_scale"])
        self._bounds = boundaries
        self._payload = payload.copy()
        self._render_job: str | None = None
        self._layout_key: int | None = None
        self._style_key: tuple | None = None
        self._last_dynamic: tuple | None = None
        self._last_value_key: tuple | None = None
        self._caption_sizes: dict[str, int] = {}
        self._label = ctk.CTkLabel(
            self,
            font=self._label_font,
            text=payload["label"] or "",
            anchor="w",
            bg_color=self._bg_color,
        )
        if payload["label"]:
            self._label.pack(fill="x")
        self._surface = tk.Canvas(self, width=1, height=1, highlightthickness=0, bd=0)
        self._surface.pack(fill="x")
        self._family = tkfont.nametofont("TkDefaultFont", root=self).actual("family")
        self._caption_font = tkfont.Font(
            root=self, family=self._family, size=-1, weight="bold"
        )
        c = self._surface
        self._arcs = [c.create_arc(0, 0, 1, 1, style="arc") for _ in boundaries[1:]]
        self._gaps = [c.create_line(0, 0, 0, 0) for _ in boundaries[1:-1]]
        self._minimum = c.create_text(0, 0, anchor="w")
        self._maximum = c.create_text(0, 0, anchor="e")
        self._caption = c.create_text(0, 0)
        self._unit = c.create_text(0, 0)
        self._needle = c.create_polygon(0, 0, 0, 0, 0, 0, width=0)
        self._hub = c.create_oval(0, 0, 0, 0, width=0)
        # A transparent retained item expands the dirty region around the
        # needle. Aqua can paint antialiased tips outside a polygon's reported
        # bounds, leaving pixels behind when only those bounds are invalidated.
        self._needle_damage = c.create_rectangle(
            0, 0, 0, 0, fill="", outline="", width=0
        )
        c.bind("<Configure>", self._request_render)
        c.bind("<Map>", self._request_render)
        self._draw()

    def set(self, payload: dict[str, Any]) -> None:
        if payload == self._payload:
            return
        old = self._payload
        self._payload = payload.copy()
        if old["font_scale"] != payload["font_scale"]:
            from ._fonts import ctk_font

            self._label_font = ctk_font(payload["font_scale"])
            self._label.configure(font=self._label_font)
        if any(old[k] != payload[k] for k in payload if k != "value"):
            self._layout_key = None
        if (old["width"], old["height"]) != (payload["width"], payload["height"]):
            self.configure(width=payload["width"], height=payload["height"])
        self._request_render()

    def _draw(self, no_color_updates: bool = False) -> None:
        super()._draw(no_color_updates)
        if hasattr(self, "_surface"):
            # Geometry changes are handled by the Canvas Configure binding.
            # Frame moves/height propagation must not schedule another render.
            if not no_color_updates:
                self._layout_key = None
                self._request_render()

    def _set_scaling(self, *args: Any, **kwargs: Any) -> None:
        super()._set_scaling(*args, **kwargs)
        if hasattr(self, "_surface"):
            self._layout_key = None
            self._request_render()

    def _request_render(self, event: Any = None) -> None:
        if event is not None and event.type == tk.EventType.Configure:
            if event.width == self._layout_key:
                return
        if self._render_job is None:
            self._render_job = self.after_idle(self._render)

    def _fraction(self, value: int | float) -> float:
        lo, hi = self._bounds[0], self._bounds[-1]
        return (min(hi, max(lo, value)) - lo) / (hi - lo)

    def _fit_caption(self, value: int | float) -> str:
        """Keep four significant digits and reuse font sizes across updates."""
        text = format(value, "#.4g").removesuffix(".")
        pattern = "".join("0" if char.isdigit() else char for char in text)
        font = self._caption_font
        size = self._caption_sizes.get(pattern)
        if size is None:
            if font.cget("size") != -self._caption_size:
                font.configure(size=-self._caption_size)
            # Measure the widest digit so the cached size fits every value
            # with this pattern, even with proportional numeral fonts.
            widest = max("0123456789", key=font.measure)
            sample = pattern.replace("0", widest)
            width = font.measure(sample)
            size = self._caption_size
            if width > self._caption_width:
                size = max(1, int(size * self._caption_width / width))
                font.configure(size=-size)
                while size > 1 and font.measure(sample) > self._caption_width:
                    size -= 1
                    font.configure(size=-size)
            self._caption_sizes[pattern] = size
        if font.cget("size") != -size:
            font.configure(size=-size)
        return text

    def _render(self) -> None:
        self._render_job = None
        c = self._surface
        if not c.winfo_ismapped():
            return
        p = self._payload
        # Height follows our own content request. Its Configure notification
        # must not feed back into another full layout of the same width.
        key = c.winfo_width()
        if key != self._layout_key:
            self._layout_key = key
            self._layout(key)
            self._last_dynamic = None
            self._last_value_key = None
        value = p["value"]
        value_key = (type(value), value)
        if value_key == self._last_value_key:
            return
        self._last_value_key = value_key
        fraction = None if value is None else self._fraction(value)
        caption = "" if value is None else self._fit_caption(value)
        dynamic = (fraction, caption)
        if dynamic == self._last_dynamic:
            return
        previous = self._last_dynamic
        self._last_dynamic = dynamic
        if previous is None or caption != previous[1]:
            c.itemconfigure(self._caption, text=caption)
        if previous is not None and fraction == previous[0]:
            return
        state = "hidden" if fraction is None else "normal"
        c.itemconfigure(self._needle, state=state)
        c.itemconfigure(self._hub, state=state)
        if fraction is None:
            c.coords(self._needle_damage, 0, 0, 0, 0)
            return
        cx, cy, radius = self._geometry
        angle = math.pi * (1 - fraction)
        dx, dy = math.cos(angle), -math.sin(angle)
        bx, by = cx + radius * 0.76 * dx, cy + radius * 0.76 * dy
        tx, ty = cx + radius * 1.01 * dx, cy + radius * 1.01 * dy
        half = max(2, radius * 0.022)
        c.coords(
            self._needle,
            tx,
            ty,
            bx - dy * half,
            by + dx * half,
            bx + dy * half,
            by - dx * half,
        )
        c.coords(self._hub, bx - half, by - half, bx + half, by + half)
        # Moving this item invalidates both its old and new padded rectangles.
        # No synchronous update, full-Canvas repaint or scale rebuild is needed.
        padding = max(4, self._apply_widget_scaling(4))
        xs = (tx, bx - dy * half, bx + dy * half, bx - half, bx + half)
        ys = (ty, by + dx * half, by - dx * half, by - half, by + half)
        c.coords(
            self._needle_damage,
            math.floor(min(xs) - padding),
            math.floor(min(ys) - padding),
            math.ceil(max(xs) + padding),
            math.ceil(max(ys) + padding),
        )

    def _layout(self, width: int) -> None:
        c, p = self._surface, self._payload
        bg = (
            _color(p["bg_color"])
            if p["bg_color"]
            else self._apply_appearance_mode(self._bg_color)
        )
        fg = (
            _color(p["font_color"])
            if p["font_color"]
            else self._apply_appearance_mode(
                ctk.ThemeManager.theme["CTkLabel"]["text_color"]
            )
        )
        if not p["enabled"]:
            fg = "#888888"
        style = (bg, fg, p["label"])
        if style != self._style_key:
            self._style_key = style
            c.configure(bg=bg)
            self._label.configure(text=p["label"] or "", text_color=fg, fg_color=bg)
            if p["label"]:
                if not self._label.winfo_manager():
                    self._label.pack(fill="x", before=c)
            else:
                self._label.pack_forget()
        scale = self._apply_widget_scaling(1)
        top = 8 * scale
        # Derive geometry from width and the configured height limit, rather
        # than the Canvas's previous height. This lets geometry propagation
        # shrink-wrap the drawing without a resize feedback loop.
        label_height = self._label.winfo_reqheight() if p["label"] else 0
        unit_ratio = 0.105 * 1.25 if p["unit"] else 0
        available = self._apply_widget_scaling(p["height"]) - label_height
        radius = max(
            1,
            min(
                width / 2 - 8 * scale, (available - top - 2 * scale) / (1 + unit_ratio)
            ),
        )
        cx, cy = width / 2, top + radius
        self._geometry = (cx, cy, radius)
        middle = radius * 0.885
        box = (cx - middle, cy - middle, cx + middle, cy + middle)
        for item, a, b, color in zip(
            self._arcs, self._bounds, self._bounds[1:], p["colors"]
        ):
            c.coords(item, *box)
            c.itemconfigure(
                item,
                start=180 * (1 - self._fraction(b)),
                extent=180 * (self._fraction(b) - self._fraction(a)),
                width=radius * 0.23,
                outline=_color(color),
                state="normal" if p["enabled"] else "disabled",
                disabledoutline="#999999",
            )
        for item, boundary in zip(self._gaps, self._bounds[1:-1]):
            angle = math.pi * (1 - self._fraction(boundary))
            dx, dy = math.cos(angle), -math.sin(angle)
            c.coords(
                item,
                cx + radius * 0.76 * dx,
                cy + radius * 0.76 * dy,
                cx + radius * 1.01 * dx,
                cy + radius * 1.01 * dy,
            )
            c.itemconfigure(item, fill=bg, width=max(1, radius * 0.012))
        size = max(1, round(radius * 0.105 * 1.25))
        for item in (self._minimum, self._maximum, self._unit):
            c.itemconfigure(item, fill=fg, font=(self._family, -size))
        c.coords(self._minimum, cx - radius * 0.71, cy - size / 2)
        c.coords(self._maximum, cx + radius * 0.71, cy - size / 2)
        c.itemconfigure(self._minimum, text=str(self._bounds[0]))
        c.itemconfigure(self._maximum, text=str(self._bounds[-1]))
        c.coords(self._caption, cx, cy - radius * 0.36)
        self._caption_size = max(1, round(size * 2.7))
        self._caption_width = max(1, radius * 1.15 - 4)
        self._caption_font.configure(size=-self._caption_size)
        self._caption_sizes.clear()
        c.itemconfigure(
            self._caption,
            fill=fg,
            font=self._caption_font,
        )
        c.coords(self._unit, cx, cy - size / 2)
        c.itemconfigure(self._unit, text=p["unit"])
        for item in (self._needle, self._hub):
            c.itemconfigure(item, fill=fg)
        bottom = cy + max(2, radius * 0.022) + 1
        for item in (self._minimum, self._maximum, self._unit):
            if bounds := c.bbox(item):
                bottom = max(bottom, bounds[3])
        content_height = math.ceil(bottom)
        if c.winfo_reqheight() != content_height:
            c.configure(height=content_height)

    def destroy(self) -> None:
        if self._render_job is not None:
            self.after_cancel(self._render_job)
            self._render_job = None
        super().destroy()
