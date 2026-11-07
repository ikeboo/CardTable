"""Copy the current Text value through the actual UI control and clipboard."""

import tkinter as tk
import unittest

import customtkinter as ctk

from cardtable import Text


class TextCopyTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("400x200")
        self.renderer = Text(rows=3)._create_renderer(self.root)
        self.root.update()

    def test_copy_button_copies_current_value_including_markdown_source(self):
        for mode, value in (
            ("plain", "日本語のテキスト\nsecond line\n"),
            ("json", '{\n  "name": "日本語"\n}'),
            ("markdown", "# Title\n\n**太字** and `code`\n"),
            ("plain", ""),
        ):
            with self.subTest(mode=mode, value=value):
                self.renderer.update({"text": value, "mode": mode})
                self.root.clipboard_clear()
                self.root.clipboard_append("previous clipboard content")
                self.renderer._copy_button.invoke()
                self.assertEqual(self.root.clipboard_get(), value)
                self.assertEqual(self.renderer._text_widget.cget("state"), "disabled")

    def test_button_stays_inside_top_right_of_text_when_resized_and_scrolled(self):
        self.renderer.update(
            {"text": "long line " * 100 + "\nmore text" * 100, "mode": "plain"}
        )
        for width in (400, 260):
            self.root.geometry(f"{width}x200")
            self.renderer._text_widget.yview_moveto(1)
            self.root.update()
            text = self.renderer._text_widget
            button = self.renderer._copy_button
            right = button.winfo_rootx() + button.winfo_width()
            self.assertLessEqual(right, text.winfo_rootx() + text.winfo_width())
            self.assertGreater(right, text.winfo_rootx() + text.winfo_width() / 2)
            self.assertGreaterEqual(button.winfo_rooty(), text.winfo_rooty())
            self.assertLessEqual(
                button.winfo_rooty() + button.winfo_height(),
                text.winfo_rooty() + text.winfo_height(),
            )
