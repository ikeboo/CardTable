"""Image value validation and UI-process rendering."""

from __future__ import annotations

import math
import subprocess
import tkinter as tk
from collections.abc import Callable, Sequence
from numbers import Real
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image as PILImage
from PIL import ImageDraw, ImageTk

from .. import theme
from .._layout import element_padding
from ._clipboard import _copy_icon, copy_image
from ._cursor import CLICK_CURSOR
from .base import Element


class Image(Element[np.ndarray | None, str | Path | np.ndarray | None]):
    """An OpenCV image value with path loading and shape validation."""

    def __init__(
        self,
        label: str | None = None,
        *,
        aspect: Sequence[float] = (4, 3),
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        self.label = label
        if isinstance(aspect, (str, bytes)) or not isinstance(aspect, Sequence):
            raise TypeError("aspect must be a two-item numeric sequence")
        normalized_aspect = tuple(aspect)
        if len(normalized_aspect) != 2 or any(
            isinstance(value, bool) or not isinstance(value, Real)
            for value in normalized_aspect
        ):
            raise TypeError("aspect must be a two-item numeric sequence")
        width, height = (float(value) for value in normalized_aspect)
        if not math.isfinite(width) or not math.isfinite(height):
            raise ValueError("aspect values must be finite")
        if width <= 0 or height <= 0:
            raise ValueError("aspect values must be positive")
        self.aspect = (width, height)

    @property
    def initial_value(self) -> np.ndarray | None:
        return None

    def normalize(self, value: str | Path | np.ndarray | None) -> np.ndarray | None:
        if value is None:
            return None
        elif isinstance(value, (str, Path)):
            image = cv2.imread(str(value), cv2.IMREAD_UNCHANGED)
        elif isinstance(value, np.ndarray):
            image = value
        else:
            raise TypeError(f"value for {self.name!r} must be an image array or path")

        if image is None:
            raise ValueError("The image could not be loaded.")
        if image.ndim not in (2, 3):
            raise ValueError("Image accepts 2D or 3D image arrays.")
        if image.ndim == 3 and image.shape[2] not in (3, 4):
            raise ValueError("Image accepts 3-channel BGR or 4-channel BGRA.")
        return np.ascontiguousarray(image).copy()

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        self._ui = self._create_renderer(parent)

    def update_ui(self, value: Any) -> None:
        self._ui.update(value)

    def _create_renderer(self, parent: Any) -> _ImageRenderer:
        """Create this element's display in the UI process."""
        return _ImageRenderer(
            parent, label=self.label, aspect=self.aspect, font_scale=self.font_scale
        )


def _fit_size(
    image_size: tuple[int, int],
    area_size: tuple[int, int],
    max_size: tuple[int, int],
) -> tuple[int, int]:
    """Fit an image inside an area without cropping or changing its ratio."""
    image_width, image_height = image_size
    area_width = min(area_size[0], max_size[0])
    area_height = min(area_size[1], max_size[1])
    scale = min(area_width / image_width, area_height / image_height)
    return (
        max(1, round(image_width * scale)),
        max(1, round(image_height * scale)),
    )


class _ImageRenderer:
    def __init__(
        self,
        parent: ctk.CTkFrame,
        *,
        font_scale: float = 1.0,
        label: str | None = None,
        aspect: tuple[float, float] = (4, 3),
        max_size: tuple[int, int] = (1280, 900),
    ) -> None:
        from ._fonts import ctk_font

        if label is not None:
            heading = ctk.CTkLabel(
                parent, font=ctk_font(font_scale), text=label, anchor="w"
            )
            heading.pack(
                fill="x",
                padx=element_padding(parent, padx=5)["padx"] + 3,
                pady=(element_padding(parent, pady=2.5)["pady"], 0),
            )
        aspect_width, aspect_height = aspect
        frame = ctk.CTkFrame(
            parent,
            fg_color="transparent",
            height=round(320 * aspect_height / aspect_width),
        )
        frame.pack(fill="x", **element_padding(parent, padx=5, pady=2.5))
        frame.pack_propagate(False)
        frame.bind(
            "<Configure>",
            lambda event: self._resize_frame(frame, event.width, aspect),
        )
        self._max_size = max_size
        self._source_image: PILImage.Image | None = None
        self._image: ImageTk.PhotoImage | None = None
        self._copy_image: ImageTk.PhotoImage | None = None
        self._render_after_id: str | None = None
        self._corner_key: tuple[int, str] | None = None
        self._corner_images: list[ImageTk.PhotoImage] = []
        # Canvas image items support alpha over the image beneath them; a child
        # Tk button's "transparent" color only shows its parent's solid color.
        self._label = tk.Canvas(
            frame,
            background=theme.color(theme.IMAGE_PADDING_COLOR),
            borderwidth=0,
            highlightthickness=0,
        )
        self._label.pack(fill="both", expand=True, padx=3, pady=3)
        self._image_item = self._label.create_image(0, 0, anchor="center")
        self._corner_items = [
            self._label.create_image(0, 0, anchor="nw") for _ in range(4)
        ]
        self._copy_button = self._label.create_image(0, 0, anchor="ne", state="hidden")
        self._label.bind("<Configure>", self._schedule_render)
        self._label.tag_bind(
            self._copy_button, "<Button-1>", lambda _: self._copy_value()
        )
        self._label.tag_bind(
            self._copy_button,
            "<Enter>",
            lambda _: self._label.configure(cursor=CLICK_CURSOR),
        )
        self._label.tag_bind(
            self._copy_button, "<Leave>", lambda _: self._label.configure(cursor="")
        )
        self._copy_icon = _copy_icon()

    def _copy_value(self) -> None:
        if self._source_image is None:
            return
        try:
            copy_image(self._source_image)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            messagebox.showerror(
                "Image copy failed", str(error), parent=self._label.winfo_toplevel()
            )

    @staticmethod
    def _resize_frame(frame: Any, width: int, aspect: tuple[float, float]) -> None:
        aspect_width, aspect_height = aspect
        height = max(1, round(width * aspect_height / aspect_width))
        if frame.winfo_height() != height:
            frame.configure(height=height)

    def update(self, payload: Any) -> None:
        if payload is None:
            self._source_image = None
            self._schedule_render()
            return
        image = np.asarray(payload)
        if image.ndim == 2:
            display_image = image
        elif image.shape[2] == 3:
            display_image = image[:, :, ::-1]
        elif image.shape[2] == 4:
            display_image = image[:, :, [2, 1, 0, 3]]
        else:
            raise ValueError("unsupported image channel count")

        self._source_image = PILImage.fromarray(display_image)
        self._schedule_render()

    def _schedule_render(self, _event: Any = None) -> None:
        if self._render_after_id is not None:
            return
        self._render_after_id = self._label.after(16, self._render)

    def _render(self) -> None:
        self._render_after_id = None
        width, height = self._label.winfo_width(), self._label.winfo_height()
        scale = self._label.master._get_widget_scaling()
        self._render_corners((width, height), scale)
        if self._source_image is None:
            self._label.itemconfigure(self._image_item, image="")
            self._label.itemconfigure(self._copy_button, image="", state="hidden")
            self._label.configure(cursor="")
            self._image = None
            self._copy_image = None
            return

        display_size = _fit_size(
            self._source_image.size,
            (self._label.winfo_width(), self._label.winfo_height()),
            self._max_size,
        )

        self._image = ImageTk.PhotoImage(
            self._source_image.resize(display_size, PILImage.Resampling.LANCZOS),
            master=self._label,
        )
        self._label.coords(self._image_item, width / 2, height / 2)
        self._label.itemconfigure(self._image_item, image=self._image)

        size = round(24 * scale)
        inset = round(4 * scale)
        icon_size = round(16 * scale)
        mode = "dark_image" if ctk.get_appearance_mode() == "Dark" else "light_image"
        icon = self._copy_icon.cget(mode).resize(
            (icon_size, icon_size), PILImage.Resampling.LANCZOS
        )
        overlay = PILImage.new("RGBA", (size, size))
        overlay.paste(icon, (inset, inset))
        self._copy_image = ImageTk.PhotoImage(overlay, master=self._label)
        self._label.coords(self._copy_button, width - round(10 * scale), inset)
        self._label.itemconfigure(
            self._copy_button, image=self._copy_image, state="normal"
        )

    def _render_corners(self, area_size: tuple[int, int], scale: float) -> None:
        """Round the whole viewport, including its black letterbox padding."""
        frame = self._label.master
        background = frame._apply_appearance_mode(frame.cget("bg_color"))
        radius = max(1, min(round(6 * scale), min(area_size) // 2))
        key = (radius, background)
        if key != self._corner_key:
            # Supersample only the small corner mask for smooth edges.
            diameter = radius * 2
            mask = PILImage.new("L", (diameter * 4, diameter * 4), 255)
            ImageDraw.Draw(mask).ellipse(
                (0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=0
            )
            mask = mask.resize((diameter, diameter), PILImage.Resampling.LANCZOS)
            rgb = tuple(value // 257 for value in self._label.winfo_rgb(background))
            corners = PILImage.new("RGBA", (diameter, diameter), (*rgb, 255))
            corners.putalpha(mask)
            self._corner_images = [
                ImageTk.PhotoImage(
                    corners.crop((x, y, x + radius, y + radius)), master=self._label
                )
                for x, y in ((0, 0), (radius, 0), (0, radius), (radius, radius))
            ]
            for item, image in zip(self._corner_items, self._corner_images):
                self._label.itemconfigure(item, image=image)
            self._corner_key = key

        width, height = area_size
        for item, (x, y) in zip(
            self._corner_items,
            (
                (0, 0),
                (width - radius, 0),
                (0, height - radius),
                (width - radius, height - radius),
            ),
        ):
            self._label.coords(item, x, y)


__all__ = ["Image"]
