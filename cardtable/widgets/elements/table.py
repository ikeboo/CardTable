"""Read-only tables with fixed headers and per-cell colors."""

from __future__ import annotations

import math
from collections.abc import Callable
from numbers import Real
from typing import Any

from .._layout import element_padding
from .base import Element
from .label import _check_color


class Table(Element[list[list[Any]], Any]):
    """Display rectangular data; ``n_rows`` excludes the fixed header.

    ``colspan`` contains positive relative widths, normalized to sum to one.
    Omit it or pass None to give all columns equal widths.
    Each ``set`` replaces the data and colors. Omitted colors and None cells
    use the theme defaults. ``get`` returns rows as lists; reset clears the table.
    ``append`` takes one-dimensional row/color arrays; ``extend`` takes matrices.
    Keep only the latest ``max_rows`` data rows (default 10000).
    """

    def __init__(
        self,
        columns: list[str],
        n_rows: int,
        colspan: list[float] | None = None,
        max_rows: int = 10000,
        *,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if not isinstance(columns, list) or not all(
            isinstance(column, str) for column in columns
        ):
            raise TypeError("columns must be a list of strings")
        if not columns:
            raise ValueError("columns must not be empty")
        if colspan is None:
            colspan = [1.0] * len(columns)
        if not isinstance(colspan, list):
            raise TypeError("colspan must be a list of numbers")
        if len(colspan) != len(columns):
            raise ValueError("colspan must have one width per column")
        if any(isinstance(v, bool) or not isinstance(v, Real) for v in colspan):
            raise TypeError("colspan must contain numbers")
        if any(not math.isfinite(v) or v <= 0 for v in colspan):
            raise ValueError("colspan widths must be finite and positive")
        if isinstance(n_rows, bool) or not isinstance(n_rows, int):
            raise TypeError("n_rows must be an int")
        if n_rows < 1:
            raise ValueError("n_rows must be at least 1")
        if isinstance(max_rows, bool) or not isinstance(max_rows, int):
            raise TypeError("max_rows must be an int")
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self.columns = columns.copy()
        # Scale first so even large finite widths cannot overflow the sum.
        largest = max(colspan)
        widths = [v / largest for v in colspan]
        total = sum(widths)
        self.colspan = [v / total for v in widths]
        self.n_rows = n_rows
        self.max_rows = max_rows
        self._text_colors: list[list[Any]] = []
        self._bg_colors: list[list[Any]] = []
        self._scroll_to_end = False

    @property
    def initial_value(self) -> list[list[Any]]:
        return []

    def _matrix(self, value: Any, name: str) -> list[list[Any]]:
        if not isinstance(value, (list, tuple)):
            import numpy as np

            if not isinstance(value, np.ndarray):
                raise TypeError(f"{name} must be a list, tuple, or ndarray")
            if value.ndim != 2:
                raise ValueError(f"{name} must be two-dimensional")
            if value.shape[1] != len(self.columns):
                raise ValueError(f"{name} must have {len(self.columns)} columns")
            value = value.tolist()
        rows = []
        for row in value:
            if not isinstance(row, (list, tuple)):
                raise TypeError(f"{name} must contain rows of lists or tuples")
            if len(row) != len(self.columns):
                raise ValueError(f"{name} must have {len(self.columns)} columns")
            rows.append(list(row))
        return rows

    def normalize(self, value: Any) -> list[list[Any]]:
        return self._matrix(value, "data")

    def _colors(self, value: Any, rows: int, name: str) -> list[list[Any]]:
        if value is None:
            return [[None] * len(self.columns) for _ in range(rows)]
        colors = self._matrix(value, name)
        if len(colors) != rows:
            raise ValueError(f"{name} must have the same shape as data")
        for row in colors:
            for color in row:
                _check_color(color, "text_color" if name == "text_colors" else name)
                if color == "transparent" or (
                    isinstance(color, tuple) and "transparent" in color
                ):
                    raise ValueError(f"{name} cannot be transparent")
        return colors

    def set(self, value: Any, text_colors: Any = None, bg_colors: Any = None) -> None:
        with self._operation():
            data = self.normalize(value)
            texts = self._colors(text_colors, len(data), "text_colors")
            backgrounds = self._colors(bg_colors, len(data), "bg_colors")
            self._text_colors = texts[-self.max_rows :]
            self._bg_colors = backgrounds[-self.max_rows :]
            self._scroll_to_end = False
            self._commit(data[-self.max_rows :])

    def _row(self, value: Any, name: str) -> list[Any]:
        if not isinstance(value, (list, tuple)):
            import numpy as np

            if not isinstance(value, np.ndarray):
                raise TypeError(f"{name} must be a list, tuple, or ndarray")
            if value.ndim != 1:
                raise ValueError(f"{name} must be one-dimensional")
            value = value.tolist()
        return self._matrix([value], name)[0]

    def append(self, row: Any, text_colors: Any = None, bg_colors: Any = None) -> None:
        """Add one row with optional per-cell colors as one-dimensional arrays.

        Existing data and colors are preserved. Omitted colors and None cells
        use the defaults for the new row. Scroll to the last row after adding.
        """
        data = self._row(row, "row")
        texts = None if text_colors is None else [self._row(text_colors, "text_colors")]
        backgrounds = None if bg_colors is None else [self._row(bg_colors, "bg_colors")]
        self.extend([data], texts, backgrounds)

    def extend(self, rows: Any, text_colors: Any = None, bg_colors: Any = None) -> None:
        """Add rows and optional color matrices, preserving existing rows/colors.

        Color matrices describe only the added rows and must match their shape.
        Scroll to the last row after adding.
        An empty batch has no effect. Validation completes before any change.
        """
        with self._operation():
            data = self.normalize(rows)
            texts = self._colors(text_colors, len(data), "text_colors")
            backgrounds = self._colors(bg_colors, len(data), "bg_colors")
            if not data:
                return
            self._text_colors = (self._text_colors + texts)[-self.max_rows :]
            self._bg_colors = (self._bg_colors + backgrounds)[-self.max_rows :]
            self._scroll_to_end = True
            self._commit((self._value + data)[-self.max_rows :])

    def get(self) -> list[list[Any]]:
        with self._operation():
            return [row.copy() for row in self._value]

    def __len__(self) -> int:
        """Return the data row count, excluding the header."""
        with self._operation():
            return len(self._value)

    def reset(self) -> None:
        self.set([])

    def display_value(self, value: list[list[Any]]) -> dict[str, Any]:
        with self._synchronized():
            payload = {
                "data": [[str(cell) for cell in row] for row in value],
                "text_colors": [row.copy() for row in self._text_colors],
                "bg_colors": [row.copy() for row in self._bg_colors],
            }
            if self._scroll_to_end:
                payload["scroll_to_end"] = True
            return payload

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        self._ui = _TableRenderer(
            parent,
            self.columns,
            self.colspan,
            self.n_rows,
            font_scale=self.font_scale,
        )

    def update_ui(self, value: Any) -> None:
        self._ui.update(value)


class _TableRenderer:
    def __init__(
        self,
        parent: Any,
        columns: list[str],
        widths: list[float],
        rows: int,
        *,
        font_scale: float = 1.0,
    ):
        import tkinter as tk

        import customtkinter as ctk

        from .. import theme
        from ._clipboard import _copy_icon
        from ._fonts import tk_font

        self._columns, self._widths = columns, widths
        self._body_items = []
        self._draw_after = None
        self._payload: dict[str, Any] = {"data": [], "text_colors": [], "bg_colors": []}
        corner_radius = 6
        frame = ctk.CTkFrame(
            parent,
            height=(rows + 1) * 28 * font_scale + 2 * corner_radius,
            corner_radius=corner_radius,
            fg_color=theme.WINDOW_BG_COLOR,
        )
        frame.pack(fill="x", **element_padding(parent))
        frame.pack_propagate(False)
        self._row_height = max(1, round(frame._apply_widget_scaling(28 * font_scale)))
        self._copy_gutter = round(frame._apply_widget_scaling(32))
        inset = max(1, round(frame._apply_widget_scaling(corner_radius)))
        self._font = tk_font(font_scale)
        self._foreground = theme.color(theme.TEXT_FONT_COLOR)
        self._backgrounds = [
            theme.color(theme.WINDOW_BG_COLOR),
            theme.color(theme.CARD_BG_COLOR),
        ]
        options = dict(
            highlightthickness=0, borderwidth=0, background=self._backgrounds[0]
        )
        self._header = tk.Canvas(frame, height=self._row_height, **options)
        # Native canvases are rectangular; keep them inside the rounded frame.
        self._header.pack(fill="x", padx=inset, pady=(inset, 0))
        self._body = tk.Canvas(frame, yscrollincrement=self._row_height, **options)
        self._body.pack(fill="both", expand=True, padx=inset, pady=(0, inset))
        self._scrollbar = ctk.CTkScrollbar(
            frame,
            width=6,
            border_spacing=1,
            command=self._body.yview,
            fg_color="transparent",
        )
        self._body.configure(
            yscrollcommand=self._on_scroll
        )
        self._body.bind("<Configure>", lambda _event: self._draw())
        self._aqua = self._body.tk.call("tk", "windowingsystem") == "aqua"
        for widget in (self._body, self._header):
            widget.bind("<MouseWheel>", self._wheel)
            widget.bind("<Button-4>", self._wheel)
            widget.bind("<Button-5>", self._wheel)
        self._scrollbar.bind("<MouseWheel>", lambda _event: "break")
        self._copy_button = ctk.CTkButton(
            frame,
            text="",
            image=_copy_icon(),
            width=24,
            height=24,
            corner_radius=4,
            border_spacing=0,
            fg_color=self._backgrounds[1],
            hover_color=theme.COPY_BUTTON_HOVER_COLOR,
            command=self._copy_value,
        )
        self._copy_button.place(in_=self._header, relx=1, rely=0.5, x=-10, anchor="e")
        self._copy_button.lift()

    def _on_scroll(self, first: str, last: str) -> None:
        from .._scrolling import update_scrollbar

        update_scrollbar(self._scrollbar, first, last, target=self._body)
        self._schedule_draw()

    def _schedule_draw(self) -> None:
        if self._draw_after is None:
            self._draw_after = self._body.after_idle(self._draw_visible)

    def _draw_visible(self) -> None:
        self._draw_after = None
        from .. import theme

        width = max(1, self._body.winfo_width() - 10)
        edges = [0.0]
        for fraction in self._widths:
            edges.append(edges[-1] + width * fraction)
        data = self._payload["data"]
        first = max(0, int(self._body.canvasy(0) // self._row_height) - 1)
        last = min(
            len(data),
            int(self._body.canvasy(self._body.winfo_height()) // self._row_height) + 2,
        )
        needed = max(0, last - first) * len(self._columns)
        while len(self._body_items) < needed:
            rect = self._body.create_rectangle(0, 0, 0, 0, width=0)
            text = self._body.create_text(0, 0, anchor="w", font=self._font)
            self._body_items.append((rect, text))
        if not data:
            while self._body_items:
                for item in self._body_items.pop():
                    self._body.delete(item)
        else:
            for rect, text in self._body_items[needed:]:
                self._body.itemconfigure(rect, state="hidden")
                self._body.itemconfigure(text, state="hidden")
        for row in range(first, last):
            for column, value in enumerate(data[row]):
                index = (row - first) * len(self._columns) + column
                rect, text = self._body_items[index]
                left, right = edges[column : column + 2]
                y = row * self._row_height
                background = self._payload["bg_colors"][row][column]
                foreground = self._payload["text_colors"][row][column]
                self._body.coords(rect, left, y, right, y + self._row_height)
                self._body.itemconfigure(
                    rect, state="normal",
                    fill=theme.color(
                        background if background is not None else self._backgrounds[row % 2]
                    ),
                )
                self._body.coords(text, left + 6, y + self._row_height / 2)
                self._body.itemconfigure(
                    text, state="normal",
                    text=self._fit(value, max(0, right - left - 12)),
                    fill=theme.color(foreground if foreground is not None else self._foreground),
                )

    def _copy_value(self) -> None:
        import csv
        import io

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(self._columns)
        writer.writerows(self._payload["data"])
        self._header.clipboard_clear()
        self._header.clipboard_append(buffer.getvalue())

    def _wheel(self, event: Any) -> str:
        if event.num in (4, 5):
            steps = -1 if event.num == 4 else 1
        else:
            delta = event.delta
            steps = -int(delta) if self._aqua else -int(delta / 120)
            if not steps and delta:
                steps = -1 if delta > 0 else 1
        self._body.yview_scroll(steps, "units")
        return "break"

    def _fit(self, text: str, width: float) -> str:
        text = text.replace("\n", " ").replace("\r", " ")
        if self._font.measure(text) <= width:
            return text
        if self._font.measure("…") > width:
            return ""
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self._font.measure(text[:mid] + "…") <= width:
                low = mid
            else:
                high = mid - 1
        return text[:low] + "…"

    def _draw(self) -> None:
        from .. import theme

        self._header.delete("all")
        width = max(1, self._body.winfo_width() - 10)
        edges = [0.0]
        for fraction in self._widths:
            edges.append(edges[-1] + width * fraction)

        def draw(canvas, row, values, texts, backgrounds):
            y = row * self._row_height
            for column, text in enumerate(values):
                left, right = edges[column : column + 2]
                gutter = (
                    self._copy_gutter
                    if canvas is self._header and column == len(values) - 1
                    else 0
                )
                canvas.create_rectangle(
                    left,
                    y,
                    right,
                    y + self._row_height,
                    width=0,
                    fill=theme.color(backgrounds[column]),
                )
                canvas.create_text(
                    left + 6,
                    y + self._row_height / 2,
                    anchor="w",
                    text=self._fit(text, max(0, right - left - 12 - gutter)),
                    fill=theme.color(texts[column]),
                    font=self._font,
                )

        draw(
            self._header,
            0,
            self._columns,
            [self._foreground] * len(self._columns),
            [self._backgrounds[1]] * len(self._columns),
        )
        self._body.configure(
            scrollregion=(0, 0, width, len(self._payload["data"]) * self._row_height)
        )
        self._schedule_draw()

    def update(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self._draw()
        self._body.yview_moveto(1.0 if payload.get("scroll_to_end") else 0.0)


__all__ = ["Table"]
