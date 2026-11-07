"""Bound retained Table rows and Text source lines before UI publication."""

import csv
import io
import json
import pickle
import tkinter as tk
import unittest

import customtkinter as ctk
from test_widgets import FakeRuntime

from cardtable import Card, Table, Text
from cardtable.core.closure import Closure


class RowLimitTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_positive_integer_limits(self):
        for create in (lambda **kw: Table(["A"], 2, [1], **kw), Text):
            for invalid in (True, False, None, "2", 2.5, 0, -1):
                with self.subTest(create=create, max_rows=invalid):
                    with self.assertRaises((TypeError, ValueError)):
                        create(max_rows=invalid)
            self.assertEqual(create().max_rows, 10000)

    def test_default_limit_keeps_latest_10000_rows(self):
        table = Table(["A"], 2, [1])
        table.set([[i] for i in range(10001)])
        self.assertEqual(len(table), 10000)
        self.assertEqual(table.get()[0], [1])
        self.assertEqual(table.get()[-1], [10000])
        text = Text()
        text.set("\n".join(str(i) for i in range(10001)))
        self.assertEqual(len(text.get().splitlines()), 10000)
        self.assertEqual(text.get().splitlines()[0], "1")
        text.append("\n10001")
        self.assertEqual(text.get().splitlines()[0], "2")
        self.assertTrue(text.get().endswith("10001"))

    def test_table_limit_keeps_data_and_colors_aligned_in_transport(self):
        with Card(0, 0, 4, 3, "Limits", runtime=FakeRuntime()) as card:
            table = Table(["A"], 2, [1], max_rows=2)
        table.set(
            [[1], [2], [3]], [["red"], [None], ["green"]], [[None], ["blue"], [None]]
        )
        payload = pickle.loads(pickle.dumps(card._latest_payload))[table.name]
        self.assertEqual(payload["data"], [["2"], ["3"]])
        self.assertEqual(payload["text_colors"], [[None], ["green"]])
        self.assertEqual(payload["bg_colors"], [["blue"], [None]])
        self.assertNotIn("scroll_to_end", payload)
        table.append([4], ["yellow"], ["red"])
        self.assertEqual(table.get(), [[3], [4]])
        payload = card._latest_payload[table.name]
        self.assertEqual(payload["text_colors"], [["green"], ["yellow"]])
        self.assertEqual(payload["bg_colors"], [[None], ["red"]])
        self.assertTrue(payload["scroll_to_end"])
        table.extend([[5], [6], [7]], bg_colors=[[None], ["blue"], ["green"]])
        self.assertEqual(table.get(), [[6], [7]])
        payload = card._latest_payload[table.name]
        self.assertEqual(payload["text_colors"], [[None], [None]])
        self.assertEqual(payload["bg_colors"], [["blue"], ["green"]])
        table.reset()
        table.append([8])
        self.assertEqual(table.get(), [[8]])
        table.extend([[9], [10]])
        self.assertEqual(table.get(), [[9], [10]])

    def test_table_validates_even_rows_that_would_be_discarded(self):
        table = Table(["A"], 1, [1], max_rows=1)
        table.append([1], ["red"])
        initial = table.display_value(table.get())
        for method in (table.set, table.extend):
            with self.assertRaises(ValueError):
                method([[2], [3]], text_colors=[["transparent"], [None]])
            with self.assertRaises(ValueError):
                method([[2, 3], [4]])
            self.assertEqual(table.display_value(table.get()), initial)
        table.append([5])
        self.assertEqual(table.get(), [[5]])

    def test_text_limits_plain_and_markdown_preserving_line_endings(self):
        for mode in ("plain", "markdown"):
            text = Text(max_rows=2)
            for original, expected in (
                ("", ""),
                ("a", "a"),
                ("a\nb", "a\nb"),
                ("a\nb\nc", "b\nc"),
                ("a\nb\nc\n", "b\nc\n"),
                ("a\n\n", "a\n\n"),
                ("a\nb\nc\n\n", "c\n\n"),
                ("a\r\nb\r\nc\r\n", "b\r\nc\r\n"),
            ):
                with self.subTest(mode=mode, original=original):
                    text.set(original, mode=mode)
                    self.assertEqual(text.get(), expected)
                    self.assertEqual(text.mode, mode)
            text.set("a\nb", mode=mode)
            text.append(" suffix")
            self.assertEqual(text.get(), "a\nb suffix")
            text.append("\nc\nd\n")
            self.assertEqual(text.get(), "c\nd\n")
            text.append("")
            self.assertEqual(text.get(), "c\nd\n")
            self.assertTrue(text.display_value(text.get())["scroll_to_end"])
            text.reset()
            text.append("1\n2\n3\n")
            self.assertEqual(text.get(), "2\n3\n")

    def test_text_formats_json_before_limiting_and_publishes_retained_text(self):
        with Card(0, 0, 4, 3, "Text", runtime=FakeRuntime()) as card:
            text = Text(max_rows=2)
        data = {"name": "日本語", "value": 1}
        formatted = json.dumps(data, ensure_ascii=False, indent=2)
        for value, options in ((data, {}), (json.dumps(data), {"mode": "json"})):
            text.set(value, **options)
            self.assertEqual(text.get(), "\n".join(formatted.split("\n")[-2:]))
            payload = pickle.loads(pickle.dumps(card._latest_payload))[text.name]
            self.assertEqual(payload, {"text": text.get(), "mode": "json"})
            with self.assertRaises(ValueError):
                text.set("invalid", mode="json")
            self.assertEqual(card._latest_payload[text.name], payload)
        text.set("a\nb\nc")
        self.assertEqual(text.get(), "b\nc")
        text.append("\nd")
        self.assertEqual(card._latest_payload[text.name]["text"], "c\nd")
        text.set("one long line " * 5000)
        self.assertEqual(len(text.get().splitlines()), 1)


class RowLimitRenderingTest(unittest.TestCase):
    def test_trimmed_data_is_displayed_and_copied_with_correct_scroll(self):
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        root.geometry("500x400")
        table = Table(["Value"], 1, [1], max_rows=3)
        text = Text(rows=1, max_rows=3)
        for element in (table, text):
            element.build_ui(root, lambda _value: None)
        root.update()
        for add in (False, True):
            if add:
                table.append([6])
                text.append("\n6")
            else:
                table.set([[i] for i in range(6)])
                text.set("\n".join(str(i) for i in range(6)))
            for element in (table, text):
                element.update_ui(element.display_value(element.get()))
            root.update()
            for widget in (table._ui._body, text._ui._text_widget):
                if add:
                    self.assertAlmostEqual(widget.yview()[1], 1.0)
                else:
                    self.assertEqual(widget.yview()[0], 0.0)
            table._ui._copy_button.invoke()
            copied = list(csv.reader(io.StringIO(root.clipboard_get())))
            self.assertEqual(
                copied, [["Value"]] + [[str(row[0])] for row in table.get()]
            )
            text._ui._copy_button.invoke()
            self.assertEqual(root.clipboard_get(), text.get())
            self.assertEqual(text._ui._text_widget.get("1.0", "end-1c"), text.get())


if __name__ == "__main__":
    unittest.main()
