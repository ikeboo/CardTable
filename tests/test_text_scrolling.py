"""Exercise nested Text scrolling with real Tk widgets and clipped content."""

import json
import tkinter as tk
import unittest

import customtkinter as ctk

from cardtable import Card, Text


class TextScrollingTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("500x500")
        self.panel = ctk.CTkFrame(self.root, width=480, height=180)
        self.panel.place(x=0, y=0)
        self.panel.pack_propagate(False)
        self.element = Text(rows=20, label="Values")
        self.ui = Card._create_ui(
            self.panel,
            emit=lambda _value: None,
            elements=[self.element],
            element_states={},
        )
        lower = ctk.CTkFrame(self.root, width=480, height=300, fg_color="limegreen")
        lower.place(x=0, y=190)
        ctk.CTkLabel(lower, text="Lower card").pack()
        self.renderer = self.element._ui
        self.text = self.renderer._text_widget
        self.canvas = self.ui._container._parent_canvas
        self.update_text()

    def update_text(self, mode="plain"):
        content = (
            json.dumps(
                [{"name": f"Line {i}", "value": None} for i in range(50)], indent=2
            )
            if mode == "json"
            else "\n".join(f"Line {i}" for i in range(200))
        )
        self.renderer.update({"text": content, "mode": mode})
        self.root.update()
        self.assertGreater(self.text.winfo_height(), self.canvas.winfo_height())
        self.assertLess(self.text.yview()[1], 1)
        self.assertLess(self.canvas.yview()[1], 1)

    def test_append_shows_last_line_and_set_returns_to_first_line(self):
        for mode in ("plain", "markdown"):
            with self.subTest(mode=mode):
                content = "\n\n".join(f"Line {i}" for i in range(200))
                self.element.set(content, mode=mode)
                self.element.update_ui(self.element.display_value(self.element.get()))
                self.root.update()
                self.assertEqual(self.text.yview()[0], 0.0)
                self.assertLess(self.text.yview()[1], 1.0)

                self.element.append("\n\nLast line")
                self.element.update_ui(self.element.display_value(self.element.get()))
                self.root.update()
                self.assertGreater(self.text.yview()[0], 0.0)
                self.assertAlmostEqual(self.text.yview()[1], 1.0)
                self.assertIsNotNone(self.text.dlineinfo("end-1c"))
                self.assertEqual(self.text.cget("state"), "disabled")

                self.element.set(content, mode=mode)
                self.element.update_ui(self.element.display_value(self.element.get()))
                self.root.update()
                self.assertEqual(self.text.yview()[0], 0.0)

    def test_plain_append_and_trim_update_existing_text(self):
        self.element.max_rows = 3
        self.element.set("😀 first\nsecond\nthird\n")
        self.element.update_ui(self.element.display_value(self.element.get()))
        # Marks in retained text survive an incremental update.
        self.text.mark_set("retained", "2.2")
        self.element.append("fourth\n")
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.assertEqual(self.text.get("1.0", "end-1c"), "second\nthird\nfourth\n")
        self.assertEqual(self.text.index("retained"), "1.2")
        self.element.append("fifth\n")
        self.element.append("sixth\n")
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.assertEqual(self.text.get("1.0", "end-1c"), self.element.get())

    def test_wheel_scrolls_text_without_moving_card_even_at_text_boundary(self):
        parent_view = self.canvas.yview()
        self.text.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(self.text.yview()[0], 0)
        self.assertEqual(self.canvas.yview(), parent_view)
        self.text.yview_moveto(1)
        self.root.update()
        self.text.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertAlmostEqual(self.text.yview()[1], 1)
        self.assertEqual(self.canvas.yview(), parent_view)

        # Scrolling the card outside Text must continue to work.
        self.canvas.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(self.canvas.yview()[0], parent_view[0])

    def test_aqua_scroll_repaints_all_lines_instead_of_copying_clipped_pixels(self):
        if not self.renderer._aqua:
            self.skipTest("Aqua redraw workaround")
        # Tk's diagnostics report which lines were actually painted. This
        # catches partial pixel-copy redraws without screen capture permissions.
        self.text.tk.call(self.text._w, "debug", True)
        self.addCleanup(self.text.tk.call, self.text._w, "debug", False)
        for mode in ("plain", "json", "markdown"):
            with self.subTest(mode=mode):
                self.update_text(mode)
                for position in (0.1, 0.2, 0.15):
                    self.text.yview_moveto(position)
                    self.root.update()
                    redrawn = self.root.tk.splitlist(
                        self.root.tk.call("set", "tk_textRedraw")
                    )
                    first = int(self.text.index("@0,0").split(".")[0])
                    last = int(self.text.index("@0,10000").split(".")[0])
                    for line in range(first, last + 1):
                        self.assertIn(f"{line}.0", redrawn)

    def test_scrollbar_drag_and_content_replacement_keep_text_readonly(self):
        scrollbar = next(
            child
            for child in self.text.master.winfo_children()
            if isinstance(child, ctk.CTkScrollbar)
        )
        parent_view = self.canvas.yview()
        scrollbar._canvas.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(self.text.yview()[0], 0)
        self.assertEqual(self.canvas.yview(), parent_view)
        command = scrollbar.cget("command")
        command("moveto", "0.5")
        self.root.update()
        self.assertGreater(self.text.yview()[0], 0)
        self.assertEqual(self.text.cget("state"), "disabled")
        self.renderer.update({"text": "Short", "mode": "plain"})
        self.root.update()
        self.assertEqual(self.text.yview(), (0.0, 1.0))
        self.assertFalse(scrollbar.winfo_manager())
        self.update_text()
        self.assertEqual(scrollbar.winfo_manager(), "place")
        self.assertEqual(self.text.cget("state"), "disabled")
