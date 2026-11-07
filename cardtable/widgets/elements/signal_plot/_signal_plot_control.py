"""UI-only bounded signal renderer and backpressured snapshot requests."""

from __future__ import annotations

import math
import tkinter as tk
from time import monotonic

import numpy as np

from ... import theme
from ..._layout import element_padding
from ..base import DisplayRequest
from ._signal_buffer import clip_segments


class SignalPlotControl:
    def __init__(self, parent, emit, *, label, aspect, max_fps, font_scale=1.0):
        import customtkinter as ctk

        from .._fonts import ctk_font

        font = ctk_font(font_scale)
        self._emit = emit
        self._aspect = aspect
        self._fps = max_fps
        self._packet = None
        self._pending = None
        self._revision = -1
        self._serial = 0
        self._waiting = None
        self._request_width = None
        self._destroyed = False
        self._token = None
        self._last_draw = -math.inf
        self._axis_key = None
        self._frame_key = None
        self._frame_corners = ()
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", **element_padding(parent))
        if label is not None:
            ctk.CTkLabel(frame, font=font, text=label, anchor="w").pack(fill="x")
        self._y_label = ctk.CTkLabel(frame, font=font, text="", anchor="w", height=16)
        self._y_label.pack(fill="x")
        self._canvas = tk.Canvas(
            frame,
            width=320,
            height=max(1, round(320 * aspect[1] / aspect[0])),
            highlightthickness=0,
            borderwidth=0,
            background=theme.color(theme.WINDOW_BG_COLOR),
        )
        self._canvas.pack(fill="x")
        self._x_label = ctk.CTkLabel(frame, font=font, text="", anchor="w", height=16)
        self._x_label.pack(fill="x")
        self._image_item = self._canvas.create_image(0, 0, anchor="nw")
        self._image = self._photo = None
        self._canvas.bind("<Destroy>", self._destroy, add="+")
        self._canvas.bind("<Map>", self._mapped, add="+")
        self._canvas.bind("<Configure>", self._resize, add="+")
        self._schedule(0)

    def _resize(self, event):
        height = max(1, round(event.width * self._aspect[1] / self._aspect[0]))
        if self._canvas.winfo_reqheight() != height:
            self._canvas.configure(height=height)
        # Height changes also need repainting when no new samples arrive.
        if self._pending is None and self._packet is not None:
            self._pending = self._packet
        self._schedule(0)

    def _schedule(self, delay):
        if not self._destroyed and self._token is None:
            self._token = self._canvas.after(delay, self._tick)

    def _mapped(self, _event):
        self._request_width = None
        self._schedule(0)

    def _destroy(self, event):
        if event.widget is not self._canvas:
            return
        self._destroyed = True
        if self._token is not None:
            self._canvas.after_cancel(self._token)
            self._token = None
        self._pending = self._packet = None
        self._photo = self._image = None
        self._frame_corners = ()

    def update(self, packet):
        serial = packet["serial"]
        # Only the response to our sole outstanding request clears backpressure.
        if serial == self._waiting:
            self._waiting = None
        if serial >= 0 and serial != self._serial:
            return
        self._fps = packet["max_fps"]
        if packet.get("unchanged"):
            return
        if packet["revision"] < self._revision:
            return
        if packet["width"] != min(16384, max(1, self._canvas.winfo_width())):
            return
        self._revision = packet["revision"]
        self._pending = packet

    def _tick(self):
        self._token = None
        if self._destroyed or not self._canvas.winfo_ismapped():
            return  # Map restarts the timer; no hidden polling or rendering.
        now = monotonic()
        interval = 1 / self._fps
        if self._pending is not None and self._pending["width"] != min(
            16384, max(1, self._canvas.winfo_width())
        ):
            self._pending = None
        if self._pending is not None and now - self._last_draw >= interval:
            self._packet = self._pending
            self._pending = None
            self._draw(self._packet)
            self._last_draw = now
        width = min(16384, max(1, self._canvas.winfo_width()))
        if self._waiting is None:
            self._serial += 1
            self._waiting = self._serial
            revision = self._revision if width == self._request_width else -1
            self._request_width = width
            self._emit(DisplayRequest(width, revision, self._serial))
        self._schedule(max(1, math.ceil(1000 / self._fps)))

    def _draw(self, packet):
        width = max(1, self._canvas.winfo_width() - 1)
        height = max(1, self._canvas.winfo_height() - 1)
        key = (width, height, packet["x_range"], packet["y_range"])
        if key != self._axis_key:
            self._axis_key = key
            lo, hi = packet["x_range"]
            self._x_label.configure(text=f"X_min: {lo:.6g}, X_max: {hi:.6g}")
            lo, hi = packet["y_range"]
            self._y_label.configure(text=f"Y_min: {lo:.6g}, Y_max: {hi:.6g}")
        from PIL import Image, ImageDraw, ImageTk

        size = (width + 1, height + 1)
        background = theme.color(theme.WINDOW_BG_COLOR)
        color = theme.color(theme.TEXT_LINK_COLOR)
        if self._image is None or self._image.size != size:
            self._image = Image.new("RGB", size, background)
            self._photo = ImageTk.PhotoImage(self._image, master=self._canvas)
            self._canvas.itemconfigure(self._image_item, image=self._photo)
        else:
            self._image.paste(background, (0, 0, *size))
        draw = ImageDraw.Draw(self._image)
        # Draw the grid into the reusable image; Canvas item count is constant.
        for fraction in (0.25, 0.5, 0.75):
            y = round(height * fraction)
            draw.line((0, y, width, y), fill=theme.color(theme.SEPARATOR_COLOR))
        points = packet["points"]
        if len(points) > 1:
            if np.all((points[:, 1] >= 0) & (points[:, 1] <= 1)):
                coords = points * [width, -height] + [0, height]
                draw.line([tuple(p) for p in coords.tolist()], fill=color, width=1)
            else:
                segments = packet.get("segments")
                if segments is None:
                    segments = clip_segments(points)
                else:
                    segments = segments.copy()
                segments *= [width, -height, width, -height]
                segments += [0, height, 0, height]
                for segment in segments.tolist():
                    draw.line(segment, fill=color, width=1)
        elif len(points) == 1 and 0 <= points[0, 1] <= 1:
            x, y = points[0] * [width, -height] + [0, height]
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=color)
        # Mask just the four corners instead of compositing a full-size mask
        # on every frame. The border is painted last so the trace cannot hide it.
        border = theme.color(theme.CARD_BORDER_COLOR)
        outer_background = theme.color(theme.CARD_BG_COLOR)
        radius = min(8, size[0] // 2, size[1] // 2)
        frame_key = (size, background, border, outer_background)
        if frame_key != self._frame_key:
            self._frame_key = frame_key
            tile = Image.new("RGBA", (2 * radius, 2 * radius), outer_background)
            ImageDraw.Draw(tile).rounded_rectangle(
                (0, 0, 2 * radius - 1, 2 * radius - 1),
                radius=radius,
                fill=(0, 0, 0, 0),
                outline=border,
                width=1,
            )
            self._frame_corners = tuple(
                (tile.crop((x, y, x + radius, y + radius)), target)
                for x, y, target in (
                    (0, 0, (0, 0)),
                    (radius, 0, (size[0] - radius, 0)),
                    (0, radius, (0, size[1] - radius)),
                    (radius, radius, (size[0] - radius, size[1] - radius)),
                )
            )
        draw.line((radius, 0, width - radius, 0), fill=border)
        draw.line((radius, height, width - radius, height), fill=border)
        draw.line((0, radius, 0, height - radius), fill=border)
        draw.line((width, radius, width, height - radius), fill=border)
        for corner, position in self._frame_corners:
            self._image.paste(corner, position, corner)
        self._photo.paste(self._image)
