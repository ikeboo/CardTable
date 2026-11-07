"""A small Canvas display with a lazily allocated, shared gradient texture."""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any
from weakref import WeakKeyDictionary

import customtkinter as ctk

# PhotoImages belong to a Tcl interpreter. Weak keys let closed roots go away.
_PALETTES: WeakKeyDictionary[tk.Misc, dict[tuple[str, str], tk.PhotoImage]] = (
    WeakKeyDictionary()
)


def _palette(master: tk.Misc, color_0: str, color_1: str) -> tk.PhotoImage:
    root = master._root()
    palettes = _PALETTES.setdefault(root, {})
    key = (color_0, color_1)
    image = palettes.get(key)
    if image is None:
        # Two periods permit a single contiguous copy at every phase offset.
        colors = []
        rgb_0, rgb_1 = (
            tuple(int(color[i : i + 2], 16) for i in (1, 3, 5)) for color in key
        )
        for x in range(256):
            blend = (1 - math.cos(math.tau * x / 256)) / 2
            channels = (round(a + (b - a) * blend) for a, b in zip(rgb_0, rgb_1))
            colors.append("#" + "".join(f"{c:02x}" for c in channels))
        image = tk.PhotoImage(master=root, width=512, height=1)
        image.put("{" + " ".join(colors * 2) + "}")
        # Blit only the opaque span of each row. Transparent corners stay
        # untouched during animation, independent of the surrounding colors.
        master.tk.call("namespace", "eval", "::cardtable", "")
        master.tk.call(
            "proc",
            "::cardtable::paint_progress",
            "image palette offset zoom width spans",
            """
            foreach {left y} $spans {
                set start [expr {$offset + $left / $zoom}]
                set count [expr {($width - 2 * $left + $zoom - 1) / $zoom}]
                $image copy $palette -from $start 0 [expr {$start + $count}] 1 \
                    -to $left $y [expr {$width - $left}] [expr {$y + 1}] \
                    -zoom $zoom 1 -compositingrule set
            }
            """,
        )
        palettes[key] = image
    return image


class _ProgressBarControl(ctk.CTkBaseClass):
    """Two native widgets with reusable items and no per-pixel Tcl calls."""

    _PERIOD = 2.0
    _FRAME_MS = 33

    def __init__(
        self,
        parent: Any,
        *,
        color_0: str = "#FF00FF",
        color_1: str = "#87CEEB",
        font_scale: float = 1.0,
    ) -> None:
        super().__init__(parent, width=1, height=42)
        self._colors = (color_0, color_1)
        self._fraction = 0.0
        self._text = self._caption = ""
        self._job: str | None = None
        self._render_job: str | None = None
        self._origin = time.monotonic()
        self._image: tk.PhotoImage | None = None
        self._palette: tk.PhotoImage | None = None
        self._image_size = (0, 0)
        self._spans: tuple[int, ...] = ()
        self._width = 1
        # Reuse Tk's resolved system family. Looking up the theme's SF Display
        # family on macOS can spend ~80 ms in native font fallback on first use.
        from ._fonts import ctk_font

        self._font = ctk_font(font_scale)
        self._surface = tk.Canvas(
            self,
            width=1,
            height=self._apply_widget_scaling(42),
            highlightthickness=0,
            bd=0,
        )
        self._surface.pack(fill="both", expand=True)
        self._track_item = self._surface.create_line(
            0, 0, 0, 0, width=1, capstyle="round"
        )
        self._fill_item = self._surface.create_image(0, 0, anchor="nw")
        self._text_item = self._surface.create_text(0, 0, anchor="w")
        # Mask long status text behind the right-aligned caption.
        self._caption_mask = self._surface.create_rectangle(0, 0, 0, 0, width=0)
        self._caption_item = self._surface.create_text(0, 0, anchor="e")
        self._surface.bind("<Configure>", self._request_render)
        self._surface.bind("<Map>", self._request_render)
        self._surface.bind("<Unmap>", self._unmap)
        self._update_font()
        self._draw()

    def _track_color(self) -> str:
        return self._apply_appearance_mode(
            ctk.ThemeManager.theme["CTkProgressBar"]["fg_color"]
        )

    def _draw(self, no_color_updates: bool = False) -> None:
        super()._draw(no_color_updates)
        if not hasattr(self, "_surface"):
            return
        background = self._apply_appearance_mode(self._bg_color)
        foreground = self._apply_appearance_mode(
            ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        )
        self._surface.configure(bg=background)
        self._surface.itemconfigure(self._caption_mask, fill=background)
        self._surface.itemconfigure(self._track_item, fill=self._track_color())
        for item in (self._text_item, self._caption_item):
            self._surface.itemconfigure(item, fill=foreground)

    def _update_font(self) -> None:
        scaled = self._apply_font_scaling(self._font)
        for item in (self._text_item, self._caption_item):
            self._surface.itemconfigure(item, font=scaled)

    def _set_scaling(self, *args: Any, **kwargs: Any) -> None:
        super()._set_scaling(*args, **kwargs)
        if hasattr(self, "_surface"):
            self._surface.configure(height=self._apply_widget_scaling(42))
            self._update_font()
            self._request_render()

    def set(self, fraction: float, text: str, caption: str) -> None:
        if (fraction, text, caption) == (self._fraction, self._text, self._caption):
            return
        if text != self._text:
            self._surface.itemconfigure(self._text_item, text=text)
        if caption != self._caption:
            self._surface.itemconfigure(self._caption_item, text=caption)
        self._fraction, self._text, self._caption = fraction, text, caption
        if fraction == 0:
            self._stop_animation()
            self._surface.itemconfigure(self._fill_item, state="hidden")
        self._request_render()

    def _request_render(self, _event: Any = None) -> None:
        # Coalesce startup layout, resizes, and bursts of set() into one draw.
        if self._render_job is None:
            self._render_job = self.after_idle(self._render)

    def _render(self) -> None:
        self._render_job = None
        if not self._surface.winfo_ismapped():
            return
        canvas = self._surface
        self._width = width = canvas.winfo_width()
        top = round(self._apply_widget_scaling(28))
        height = max(1, round(self._apply_widget_scaling(10)))
        middle = self._apply_widget_scaling(14)
        canvas.coords(self._text_item, 0, middle)
        canvas.coords(self._caption_item, width, middle)
        caption_box = canvas.bbox(self._caption_item)
        left = caption_box[0] if caption_box else width
        canvas.coords(
            self._caption_mask, left - self._apply_widget_scaling(8), 0, width, top
        )
        radius = min(width, height) / 2
        canvas.coords(
            self._track_item,
            radius,
            top + height / 2,
            width - radius,
            top + height / 2,
        )
        canvas.itemconfigure(self._track_item, width=height)
        canvas.coords(self._fill_item, 0, top)
        filled = round(width * self._fraction)
        if filled <= 0:
            canvas.itemconfigure(self._fill_item, state="hidden")
            self._stop_animation()
            return
        if self._palette is None:
            self._palette = _palette(self, *self._colors)
        if self._image is None:
            self._image = tk.PhotoImage(master=self, width=filled, height=height)
            canvas.itemconfigure(self._fill_item, image=self._image)
        elif self._image_size != (filled, height):
            self._image.configure(width=filled, height=height)
        if self._image_size != (filled, height):
            self._image.blank()
            radius = min(filled, height) / 2
            spans = []
            for y in range(height):
                dy = max(0, radius - min(y + 0.5, height - y - 0.5))
                inset = round(radius - math.sqrt(max(0, radius**2 - dy**2)))
                spans.extend((min(inset, (filled - 1) // 2), y))
            self._spans = tuple(spans)
        self._image_size = (filled, height)
        canvas.itemconfigure(self._fill_item, state="normal")
        self._paint()
        if self._job is None:
            self._job = self.after(self._FRAME_MS, self._animate)

    def _paint(self) -> None:
        filled, _height = self._image_size
        zoom = max(1, (self._width + 255) // 256)
        phase = ((time.monotonic() - self._origin) / self._PERIOD) % 1
        offset = (-int(phase * 256)) % 256
        self.tk.call(
            "::cardtable::paint_progress",
            str(self._image),
            str(self._palette),
            offset,
            zoom,
            filled,
            self._spans,
        )

    def _animate(self) -> None:
        self._job = None
        self._paint()
        self._job = self.after(self._FRAME_MS, self._animate)

    def _stop_animation(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _unmap(self, _event: Any = None) -> None:
        self._stop_animation()

    def destroy(self) -> None:
        self._stop_animation()
        if self._render_job is not None:
            self.after_cancel(self._render_job)
            self._render_job = None
        super().destroy()
