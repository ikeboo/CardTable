"""Text value validation and UI-process rendering."""

from __future__ import annotations

import json
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import font as tkfont
from typing import Any

import customtkinter as ctk
from markdown_it import MarkdownIt
from markdown_it.token import Token as MarkdownToken
from pygments import lex
from pygments.lexers import JsonLexer, TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .. import theme
from .._layout import element_padding
from .._scrolling import update_scrollbar
from ._clipboard import _copy_icon
from .base import Element

_MODES = frozenset({"plain", "json", "markdown"})


class Text(Element[str, Any]):
    """Plain, JSON, or Markdown text, retaining the latest ``max_rows`` lines.

    The limit applies to source lines after formatting, including JSON. Trimming
    JSON or Markdown can leave a fragment of the original document.
    """

    def __init__(
        self, rows: int = 2, label: str | None = None, max_rows: int = 10000,
        *, log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if isinstance(rows, bool) or not isinstance(rows, int):
            raise TypeError("rows must be an int")
        if rows < 1:
            raise ValueError("rows must be at least 1")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if isinstance(max_rows, bool) or not isinstance(max_rows, int):
            raise TypeError("max_rows must be an int")
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self.rows = rows
        self.label = label
        self.max_rows = max_rows
        self._mode = "plain"
        self._scroll_to_end = False

    @property
    def initial_value(self) -> str:
        return ""

    @property
    def mode(self) -> str:
        with self._synchronized():
            return self._mode

    def normalize(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("text must be a string")
        return value

    def _limit_rows(self, text: str) -> str:
        # A final newline terminates the last line rather than consuming a row.
        lines = text.splitlines(keepends=True)
        return "".join(lines[-self.max_rows :])

    def reset(self) -> None:
        with self._operation():
            self._mode = "plain"
            self._scroll_to_end = False
            self._commit(self.initial_value)

    def set(self, value: Any, *, mode: str | None = None) -> None:
        with self._operation():
            normalized_mode = (
                "json"
                if mode is None and isinstance(value, Mapping)
                else (
                    "plain"
                    if mode is None
                    else mode.lower()
                    if isinstance(mode, str)
                    else mode
                )
            )
            if normalized_mode not in _MODES:
                raise ValueError("mode must be 'plain', 'json', or 'markdown'")
            if normalized_mode == "json":
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            "text in JSON mode must contain valid JSON"
                        ) from error
                try:
                    text = json.dumps(value, ensure_ascii=False, indent=2)
                except (TypeError, ValueError) as error:
                    raise TypeError(
                        "data in JSON mode must be JSON serializable"
                    ) from error
            else:
                if not isinstance(value, str):
                    raise TypeError(
                        f"data in {normalized_mode!r} mode must be a string"
                    )
                text = value
            self._mode = normalized_mode
            self._scroll_to_end = False
            self._commit(self._limit_rows(text))

    def append(self, text: str) -> None:
        """Atomically append text and scroll to the end, preserving the mode.

        No newline is added automatically.
        JSON mode does not support appending. Use ``set`` to replace JSON data.
        """
        with self._operation():
            text = self.normalize(text)
            if self._mode == "json":
                raise ValueError("cannot append text in JSON mode; use set instead")
            self._scroll_to_end = True
            self._commit(self._limit_rows(self._value + text))

    def display_value(self, value: Any) -> Any:
        with self._synchronized():
            payload = {"text": value, "mode": self._mode}
            if self._scroll_to_end:
                payload["scroll_to_end"] = True
            return payload

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        self._ui = self._create_renderer(parent)

    def update_ui(self, value: Any) -> None:
        self._ui.update(value)

    def _create_renderer(self, parent: Any) -> _TextRenderer:
        """Create this element's display in the UI process."""
        return _TextRenderer(
            parent, rows=self.rows, label=self.label, font_scale=self.font_scale
        )


Segment = tuple[str, tuple[str, ...]]


def _background_color(widget: Any) -> str:
    """Resolve a concrete Tk color through transparent CTk ancestors."""
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


def _normalize_mode(mode: str) -> str:
    if not isinstance(mode, str):
        raise TypeError("mode must be 'plain', 'json', or 'markdown'")
    normalized = mode.lower()
    if normalized not in _MODES:
        raise ValueError("mode must be 'plain', 'json', or 'markdown'")
    return normalized


def _syntax_tag(token_type: Any) -> str:
    """Map Pygments' token hierarchy to a small, stable UI palette."""
    path = str(token_type)
    if "Error" in path:
        return "syntax_error"
    if "Name.Tag" in path or "Name.Attribute" in path:
        return "syntax_key"
    if "String" in path:
        return "syntax_string"
    if "Number" in path:
        return "syntax_number"
    if "Keyword" in path or "Name.Builtin" in path:
        return "syntax_keyword"
    if "Comment" in path:
        return "syntax_comment"
    if "Operator" in path or "Punctuation" in path:
        return "syntax_punctuation"
    return "syntax_text"


def _highlighted_segments(
    text: str,
    lexer: Any,
    *base_tags: str,
) -> list[Segment]:
    return [
        (value, (*base_tags, _syntax_tag(token_type)))
        for token_type, value in lex(text, lexer)
        if value
    ]


def _markdown_segments(text: str) -> list[Segment]:
    """Render CommonMark tokens to styled plain-text segments for ``tk.Text``."""
    segments: list[Segment] = []
    block_tags: list[str] = []
    list_stack: list[dict[str, Any]] = []
    quote_depth = 0

    def append(value: str, *tags: str) -> None:
        if not value:
            return
        combined = tuple(dict.fromkeys((*block_tags, *tags)))
        if segments and segments[-1][1] == combined:
            previous, _ = segments[-1]
            segments[-1] = (previous + value, combined)
        else:
            segments.append((value, combined))

    def endswith_newline(count: int = 1) -> bool:
        return bool(segments) and segments[-1][0].endswith("\n" * count)

    def newline(count: int = 1) -> None:
        if not segments:
            return
        existing = 0
        existing = len(segments[-1][0]) - len(segments[-1][0].rstrip("\n"))
        if existing < count:
            append("\n" * (count - existing))

    def render_inline(children: list[MarkdownToken]) -> None:
        inline_tags: list[str] = []
        tag_by_type = {
            "strong_open": "md_bold",
            "em_open": "md_italic",
            "s_open": "md_strike",
            "link_open": "md_link",
        }
        for child in children:
            if child.type in tag_by_type:
                inline_tags.append(tag_by_type[child.type])
            elif child.type.endswith("_close"):
                open_type = child.type.removesuffix("_close") + "_open"
                tag = tag_by_type.get(open_type)
                if tag in inline_tags:
                    inline_tags.remove(tag)
            elif child.type == "text":
                append(child.content, *inline_tags)
            elif child.type in {"softbreak", "hardbreak"}:
                append("\n", *inline_tags)
            elif child.type == "code_inline":
                append(child.content, *inline_tags, "md_code")
            elif child.type == "image":
                append(child.content or child.attrGet("alt") or "image", *inline_tags)
            elif child.type == "html_inline":
                append(child.content, *inline_tags)

    tokens = MarkdownIt("commonmark", {"linkify": False}).parse(text)
    for token in tokens:
        if token.type == "heading_open":
            newline(1)
            block_tags.append(f"md_{token.tag}")
        elif token.type == "heading_close":
            newline(2)
            if block_tags:
                block_tags.pop()
        elif token.type == "blockquote_open":
            quote_depth += 1
            block_tags.append("md_quote")
        elif token.type == "blockquote_close":
            newline(2)
            quote_depth -= 1
            if block_tags:
                block_tags.pop()
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            if list_stack and not endswith_newline():
                newline()
            start = int(token.attrGet("start") or 1)
            list_stack.append(
                {"ordered": token.type == "ordered_list_open", "next": start}
            )
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            if list_stack:
                list_stack.pop()
            if not list_stack:
                newline(2)
        elif token.type == "list_item_open":
            newline()
            current = list_stack[-1]
            marker = f"{current['next']}. " if current["ordered"] else "• "
            current["next"] += 1
            append("  " * (len(list_stack) - 1) + marker, "md_list_marker")
        elif token.type == "list_item_close":
            newline()
        elif token.type == "paragraph_open":
            if quote_depth:
                newline()
                append("│ " * quote_depth, "md_quote_marker")
        elif token.type == "paragraph_close":
            if not list_stack:
                newline(2)
        elif token.type == "inline":
            render_inline(token.children or [])
        elif token.type in {"fence", "code_block"}:
            newline()
            language = token.info.strip().split(maxsplit=1)[0] if token.info else ""
            try:
                lexer = (
                    get_lexer_by_name(language, stripnl=False, ensurenl=False)
                    if language
                    else TextLexer(stripnl=False, ensurenl=False)
                )
            except ClassNotFound:
                lexer = TextLexer(stripnl=False, ensurenl=False)
            segments.extend(
                _highlighted_segments(token.content, lexer, "md_code_block")
            )
            newline(2)
        elif token.type == "hr":
            newline()
            append("─" * 36, "md_rule")
            newline(2)
        elif token.type == "html_block":
            append(token.content)
            newline(2)

    # Markdown's final block spacing is presentation detail rather than content.
    while segments and segments[-1][0].endswith("\n"):
        value, tags = segments[-1]
        value = value.rstrip("\n")
        if value:
            segments[-1] = (value, tags)
            break
        segments.pop()
    return segments


class _TextRenderer:
    def __init__(
        self,
        parent: ctk.CTkFrame,
        *,
        rows: int = 2,
        font_scale: float = 1.0,
        label: str | None = None,
    ) -> None:
        from ._fonts import ctk_font, tk_font

        self._font_scale = font_scale
        self._font = tk_font(font_scale)
        self._value = ""
        self._rendered_mode = "plain"
        frame = ctk.CTkFrame(
            parent,
            fg_color="transparent",
            height=rows * 28 * font_scale
            + 12
            + (28 * font_scale if label is not None else 0),
        )
        frame.pack(fill="x", **element_padding(parent))
        frame.pack_propagate(False)

        if label is not None:
            heading = ctk.CTkLabel(
                frame,
                font=ctk_font(font_scale),
                text=label,
                anchor="w",
                height=28 * font_scale,
            )
            heading.pack(fill="x")

        entry_theme = ctk.ThemeManager.theme["CTkEntry"]
        border_width = entry_theme["border_width"]
        corner_radius = entry_theme["corner_radius"]
        container = ctk.CTkFrame(
            frame,
            fg_color="transparent",
            corner_radius=corner_radius,
            border_width=border_width,
            border_color=entry_theme["border_color"],
        )
        container.pack(fill="both", expand=True, pady=6)

        background = _background_color(frame)
        foreground = theme.color(theme.TEXT_FONT_COLOR)
        self._text_widget = tk.Text(
            container,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            background=background,
            foreground=foreground,
            insertbackground=foreground,
            selectbackground=theme.color(theme.TEXT_SELECTION_COLOR),
            selectforeground=theme.color(theme.TEXT_SELECTION_FONT_COLOR),
            cursor="xterm",
            font=self._font,
            state="disabled",
            undo=False,
        )
        # Keep Tk's native Text wheel behavior, then stop the event before
        # CTkScrollableFrame's bind_all handler also scrolls the containing card.
        scroll_tag = "CardTableTextScroll"
        tags = self._text_widget.bindtags()
        text_class = tags.index("Text")
        self._text_widget.bindtags(
            (*tags[: text_class + 1], scroll_tag, *tags[text_class + 1 :])
        )
        for sequence in (
            "<MouseWheel>",
            "<Shift-MouseWheel>",
            "<Button-4>",
            "<Button-5>",
        ):
            self._text_widget.tk.call("bind", scroll_tag, sequence, "break")
        self._aqua = self._text_widget.tk.call("tk", "windowingsystem") == "aqua"
        scrollbar = ctk.CTkScrollbar(
            container,
            width=6,
            border_spacing=1,
            command=self._text_widget.yview,
            fg_color="transparent",
            bg_color=background,
        )
        # CTkScrollbar handles the wheel on its internal canvas before this
        # additional binding; prevent the same event reaching the card as well.
        scrollbar.bind("<MouseWheel>", lambda _event: "break")
        self._text_widget.configure(
            yscrollcommand=lambda first, last: self._on_scroll(scrollbar, first, last)
        )
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        self._text_widget.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=max(border_width, corner_radius),
            pady=border_width,
        )
        self._configure_tags()
        self._copy_button = ctk.CTkButton(
            container,
            text="",
            image=_copy_icon(compact=True),
            width=14,
            height=14,
            corner_radius=2,
            border_spacing=0,
            fg_color=background,
            hover_color=theme.COPY_BUTTON_HOVER_COLOR,
            command=self._copy_value,
        )
        self._copy_button.place(in_=self._text_widget, relx=1, anchor="ne")
        self._copy_button.lift()

    def _copy_value(self) -> None:
        self._text_widget.clipboard_clear()
        self._text_widget.clipboard_append(self._value)

    def _on_scroll(self, scrollbar: Any, first: str, last: str) -> None:
        if self._aqua:
            # A Text can be taller than its card's canvas viewport. On Aqua,
            # scrolling can copy pixels from the clipped part of that window
            # (including another card) into view. Invalidate every display line
            # so Tk paints text rather than reusing those pixels. Do this before
            # CTkScrollbar.set(), which can process pending redraws itself.
            self._text_widget.event_generate(
                "<Expose>",
                x=0,
                y=0,
                width=self._text_widget.winfo_width(),
                height=self._text_widget.winfo_height(),
            )
        update_scrollbar(scrollbar, first, last, target=self._text_widget)

    def _configure_tags(self) -> None:
        base = tkfont.nametofont(self._text_widget.cget("font"))
        base_size = abs(int(base.cget("size"))) or 12
        family = str(base.cget("family"))
        mono_family = str(tkfont.nametofont("TkFixedFont").cget("family"))

        self._text_widget.tag_configure(
            "md_h1",
            font=(family, base_size + round(9 * self._font_scale), "bold"),
            spacing1=8,
            spacing3=5,
        )
        self._text_widget.tag_configure(
            "md_h2",
            font=(family, base_size + round(6 * self._font_scale), "bold"),
            spacing1=7,
            spacing3=4,
        )
        self._text_widget.tag_configure(
            "md_h3",
            font=(family, base_size + round(3 * self._font_scale), "bold"),
            spacing1=6,
            spacing3=3,
        )
        for level in range(4, 7):
            self._text_widget.tag_configure(
                f"md_h{level}",
                font=(family, base_size + round(1 * self._font_scale), "bold"),
                spacing1=5,
            )
        self._text_widget.tag_configure("md_bold", font=(family, base_size, "bold"))
        self._text_widget.tag_configure("md_italic", font=(family, base_size, "italic"))
        self._text_widget.tag_configure("md_strike", overstrike=True)
        self._text_widget.tag_configure(
            "md_link", foreground=theme.color(theme.TEXT_LINK_COLOR), underline=True
        )
        self._text_widget.tag_configure(
            "md_code",
            font=(mono_family, base_size),
            background=theme.color(theme.TEXT_CODE_BG_COLOR),
        )
        self._text_widget.tag_configure(
            "md_code_block",
            font=(mono_family, base_size),
            background=theme.color(theme.TEXT_CODE_BLOCK_BG_COLOR),
            lmargin1=8,
            lmargin2=8,
            spacing1=5,
            spacing3=5,
        )
        self._text_widget.tag_configure(
            "md_quote",
            foreground=theme.color(theme.TEXT_QUOTE_COLOR),
            lmargin1=10,
            lmargin2=10,
        )
        self._text_widget.tag_configure(
            "md_quote_marker", foreground=theme.color(theme.TEXT_QUOTE_MARKER_COLOR)
        )
        self._text_widget.tag_configure(
            "md_list_marker", foreground=theme.color(theme.TEXT_LINK_COLOR)
        )
        self._text_widget.tag_configure(
            "md_rule", foreground=theme.color(theme.TEXT_RULE_COLOR)
        )

        for tag, color in theme.TEXT_SYNTAX_COLORS.items():
            self._text_widget.tag_configure(tag, foreground=theme.color(color))

    def update(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise TypeError("Text renderer update payload must be a dictionary")
        text = payload.get("text")
        mode = _normalize_mode(payload.get("mode"))
        if not isinstance(text, str):
            raise TypeError("Text renderer update text must be a string")

        # Plain text can be updated in place. The renderer receives full
        # snapshots, so this also works when intermediate updates were coalesced.
        overlap = None
        old = self._value
        if mode == self._rendered_mode == "plain" and payload.get("scroll_to_end"):
            if text.startswith(old):
                overlap = (0, len(old))
            elif old and text:
                # Row limiting discards complete source lines from the front.
                first_line = text.split("\n", 1)[0]
                position = old.find(first_line)
                while position >= 0:
                    if (
                        (position == 0 or old[position - 1] == "\n")
                        and text.startswith(old[position:])
                    ):
                        overlap = (position, len(old) - position)
                        break
                    position = old.find(first_line, position + 1)

        self._text_widget.configure(state="normal")
        if overlap is not None:
            removed, retained = overlap
            if removed:
                removed_lines = old[:removed].count("\n")
                self._text_widget.delete("1.0", f"1.0 + {removed_lines} lines")
            if text[retained:]:
                self._text_widget.insert("end", text[retained:])
        else:
            if mode == "json":
                segments = _highlighted_segments(
                    text, JsonLexer(stripnl=False, ensurenl=False)
                )
            elif mode == "markdown":
                segments = _markdown_segments(text)
            else:
                segments = [(text, ())]
            self._text_widget.delete("1.0", "end")
            for value, tags in segments:
                self._text_widget.insert("end", value, tags)
        self._text_widget.configure(state="disabled")
        self._text_widget.yview_moveto(1.0 if payload.get("scroll_to_end") else 0.0)
        self._value = text
        self._rendered_mode = mode


__all__ = ["Text"]
