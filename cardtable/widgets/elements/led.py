"""Boolean LED indicators with non-blocking flash support."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from threading import Timer
from typing import Any

from PIL import Image, ImageColor

from .. import theme
from .._layout import element_padding
from ._boolean import _BooleanElement


@dataclass(slots=True, init=False)
class LED(_BooleanElement):
    """A boolean switch with a glowing round indicator to the right of its label.

    ``color`` accepts Pillow color names and hex strings. Use ``set`` / ``value``
    to change its boolean state. ``interactive=True`` also allows clicking the
    indicator to toggle it, without changing its appearance.
    ``set(value, color=...)`` changes the color for subsequent updates too.
    """

    color: str
    size: int
    interactive: bool
    _flash_generation: int
    _ui_images: tuple[Any, Any]
    _ui_color: str
    _ui_indicator: Any
    _ui_label: Any
    _ui_value: bool
    _ui_disabled: bool

    def __init__(
        self,
        color: str,
        label: str | None = None,
        *,
        default: bool = False,
        size: int = 24,
        interactive: bool = False,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if not isinstance(color, str):
            raise TypeError("color must be a string")
        ImageColor.getrgb(color)
        if isinstance(size, bool) or not isinstance(size, int):
            raise TypeError("size must be an int")
        if size <= 0:
            raise ValueError("size must be positive")
        if not isinstance(interactive, bool):
            raise TypeError("interactive must be a bool")
        self.color = color
        self.size = size
        self.interactive = interactive
        self._flash_generation = 0
        super(LED, self).__init__(
            default=default, label=label, log_level=log_level,
            log_levels=log_levels, font_scale=font_scale,
        )

    def set(self, value: bool, *, color: str | None = None) -> None:
        """Set the boolean state, retaining the current color when omitted."""
        with self._operation():
            normalized = self.normalize(value)
            if color is not None:
                if not isinstance(color, str):
                    raise TypeError("color must be a string")
                ImageColor.getrgb(color)
                self.color = color
            self._commit(normalized)

    def display_value(self, value: bool) -> dict[str, Any]:
        with self._synchronized():
            return {"value": value, "color": self.color}

    def _build_images(self) -> None:
        import customtkinter as ctk

        size = (self.size, self.size)
        self._ui_images = (
            ctk.CTkImage(light_image=led_image(self.color, False), size=size),
            ctk.CTkImage(light_image=led_image(self.color, True), size=size),
        )
        self._ui_color = self.color

    def build_ui(self, parent: Any, emit: Callable[[bool], None]) -> None:
        import customtkinter as ctk

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", **element_padding(parent))
        line = ctk.CTkFrame(
            row,
            height=1,
            corner_radius=0,
            border_width=0,
            fg_color=theme.SEPARATOR_COLOR,
        )
        line.pack_propagate(False)
        line.pack(side="bottom", fill="x")
        self._ui_label = ctk.CTkLabel(
            row, font=self._scaled_font(), text=self.display_label, anchor="w"
        )
        self._ui_label.pack(side="left", fill="x", expand=True)
        # Reuse both images until the color changes; flashing only swaps them.
        self._build_images()
        self._ui_value = self.initial_value
        self._ui_disabled = False
        self._ui_indicator = ctk.CTkLabel(
            row,
            font=self._scaled_font(),
            text="",
            image=self._ui_images[self._ui_value],
            width=self.size,
            height=self.size,
        )
        self._ui_indicator.pack(side="right", padx=(12, 0))

        def toggle(event: Any) -> None:
            if not self.interactive or self._ui_disabled:
                return
            self.update_ui(not self._ui_value)
            emit(self._ui_value)

        self._ui_indicator.bind("<Button-1>", toggle)

    def update_ui(self, value: Any) -> None:
        color = value["color"] if isinstance(value, dict) else self.color
        normalized = self.normalize(
            value["value"] if isinstance(value, dict) else value
        )
        color_changed = color != self._ui_color
        if color_changed:
            self.color = color
            self._build_images()
        if color_changed or normalized != self._ui_value:
            self._ui_indicator.configure(image=self._ui_images[normalized])
            self._ui_value = normalized

    def update_state_ui(self, state: str, label: str | None) -> None:
        self._ui_disabled = state == "disabled"
        if label is not None:
            self._ui_label.configure(text=label)

    def __getstate__(self) -> dict[str, Any]:
        # Tk resources belong to the UI process and must never be transferred.
        return {
            name: value
            for name, value in super(LED, self).__getstate__().items()
            if not name.startswith("_ui_")
        }

    def flash(self, duration_ms: int) -> None:
        """Light for a positive number of milliseconds without waiting.

        Calls while already on are ignored. Explicit value changes cancel the
        pending automatic turn-off, so an old flash cannot interrupt a new one.
        """
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise TypeError("duration_ms must be an int")
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        with self._operation():
            if self._value:
                return
            self._commit(True)
            generation = self._flash_generation

            def turn_off() -> None:
                with self._synchronized():
                    if self._flash_generation == generation:
                        self._commit(False)

            timer = Timer(duration_ms / 1000, turn_off)
            timer.daemon = True
            timer.start()

    def _commit(self, normalized: bool) -> None:
        with self._synchronized():
            self._flash_generation += 1
            super(LED, self)._commit(normalized)

    def _store_normalized(self, value: bool) -> None:
        super(LED, self)._store_normalized(value)
        self._flash_generation += 1


def led_image(color: str, on: bool) -> Image.Image:
    """Render a lens without surface gloss and a soft halo when on."""
    rgb = ImageColor.getrgb(color)[:3]
    size = 128
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            dx, dy = (x + 0.5 - size / 2) / 44, (y + 0.5 - size / 2) / 44
            radius = math.hypot(dx, dy)
            if radius <= 1:
                brightness = (0.95 - 0.35 * radius**2) if on else 0.18
                highlight = 0.0
                if on:
                    # A nearly white core fades into the colored lens.
                    highlight = 0.97 * math.exp(-(radius**2) / 0.24)
                channels = tuple(
                    round(c * brightness * (1 - highlight) + 255 * highlight)
                    for c in rgb
                )
                pixels[x, y] = (*channels, 255)
            elif on:
                alpha = round(95 * math.exp(-8 * (radius - 1)))
                pixels[x, y] = (*rgb, alpha)
    return image


__all__ = ["LED"]
