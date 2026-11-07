"""Table validation, transport, fixed headers, and nested scrolling."""

import csv
import io
import pickle
import tkinter as tk
import unittest
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
import numpy as np
from test_widgets import FakeRuntime

from cardtable import Card, Table
from cardtable.core.closure import Closure
from cardtable.widgets import theme


class TableTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_public_exports_and_normalized_widths(self):
        from cardtable.widgets import Table as WidgetsTable
        from cardtable.widgets.elements import Table as ElementsTable

        self.assertIs(Table, WidgetsTable)
        self.assertIs(Table, ElementsTable)
        columns = ["Name", "Value"]
        table = Table(columns, 4, [1, 3])
        columns[0] = "Changed"
        self.assertEqual(table.columns, ["Name", "Value"])
        self.assertEqual(table.colspan, [0.25, 0.75])
        self.assertEqual(Table(columns, 1, [1e308, 1e308]).colspan, [0.5, 0.5])
        self.assertEqual(table.get(), [])

    def test_equal_widths_when_colspan_is_omitted_or_none(self):
        for columns in (["A"], ["A", "B"], ["A", "B", "C"]):
            with self.subTest(columns=columns):
                expected = [1 / len(columns)] * len(columns)
                self.assertEqual(Table(columns, 2).colspan, expected)
                self.assertEqual(Table(columns, 2, None).colspan, expected)
                self.assertEqual(
                    Table(columns=columns, n_rows=2, colspan=None).colspan, expected
                )

    def test_data_types_colors_and_reset(self):
        table = Table(["Name", "Value"], 2, [2, 1])
        for data in ([[1, 2], [3, 4]], ((1, 2), (3, 4)), np.arange(1, 5).reshape(2, 2)):
            with self.subTest(data=type(data)):
                table.set(
                    data,
                    ((None, "red"), ("blue", None)),
                    np.array([["yellow", None], [None, "green"]], dtype=object),
                )
                self.assertEqual(table.get(), [[1, 2], [3, 4]])
                payload = table.display_value(table.get())
                self.assertEqual(payload["data"], [["1", "2"], ["3", "4"]])
                self.assertEqual(payload["text_colors"][0], [None, "red"])
        table.set([[5, 6]])
        self.assertEqual(
            table.display_value(table.get())["text_colors"], [[None, None]]
        )
        table.value = ((7, 8),)
        self.assertEqual(table.get(), [[7, 8]])
        table.reset()
        self.assertEqual(
            table.display_value(table.get()),
            {"data": [], "text_colors": [], "bg_colors": []},
        )

    def test_copies_data_and_color_matrices(self):
        table = Table(["A"], 1, [1])
        data, colors = [[42]], [["red"]]
        table.set(data, colors)
        data[0][0] = 0
        colors[0][0] = "blue"
        table.get()[0][0] = 100
        payload = table.display_value(table.get())
        payload["text_colors"][0][0] = "yellow"
        self.assertEqual(table.get(), [[42]])
        self.assertEqual(table.display_value(table.get())["text_colors"], [["red"]])

    def test_append_and_extend_accept_arrays_and_preserve_existing_colors(self):
        for row, rows in (
            ([3, 4], [[5, 6], [7, 8]]),
            ((3, 4), ((5, 6), (7, 8))),
            (np.array([3, 4]), np.array([[5, 6], [7, 8]])),
        ):
            with self.subTest(row_type=type(row)):
                table = Table(["A", "B"], 2, [1, 1])
                table.set([[1, 2]], [["red", None]], [[None, "blue"]])
                table.append(
                    row,
                    np.array([None, "green"], dtype=object),
                    (("white", "black"), None),
                )
                table.extend(
                    rows,
                    ((None, "yellow"), ("orange", None)),
                    np.array([["blue", None], [None, "red"]], dtype=object),
                )
                self.assertEqual(table.get(), [[1, 2], [3, 4], [5, 6], [7, 8]])
                payload = table.display_value(table.get())
                self.assertEqual(
                    payload["text_colors"],
                    [
                        ["red", None],
                        [None, "green"],
                        [None, "yellow"],
                        ["orange", None],
                    ],
                )
                self.assertEqual(
                    payload["bg_colors"],
                    [
                        [None, "blue"],
                        [("white", "black"), None],
                        ["blue", None],
                        [None, "red"],
                    ],
                )
                table.append([9, 10])
                table.extend([[11, 12]])
                payload = table.display_value(table.get())
                self.assertEqual(payload["text_colors"][-2:], [[None, None]] * 2)
                self.assertEqual(payload["bg_colors"][-2:], [[None, None]] * 2)
                table.reset()
                table.append([13, 14])
                self.assertEqual(table.get(), [[13, 14]])

    def test_invalid_additions_leave_data_and_colors_unchanged(self):
        table = Table(["A", "B"], 2, [1, 1])
        table.append([1, 2], ["red", None])
        initial = table.display_value(table.get())
        for method, data, options in (
            (table.append, [3], {}),
            (table.append, np.zeros((1, 2)), {}),
            (table.append, [3, 4], {"text_colors": [["red", None]]}),
            (table.append, [3, 4], {"bg_colors": np.zeros((1, 2))}),
            (table.append, [3, 4], {"text_colors": [None, 42]}),
            (
                table.append,
                [3, 4],
                {"text_colors": ["blue", None], "bg_colors": [None, "transparent"]},
            ),
            (table.extend, [3, 4], {}),
            (table.extend, [[3, 4], [5]], {}),
            (table.extend, [[3, 4]], {"text_colors": [None, None]}),
            (table.extend, [[3, 4]], {"bg_colors": [[None, None], [None, None]]}),
            (
                table.extend,
                [[3, 4]],
                {"text_colors": [["green", None]], "bg_colors": [[None, 42]]},
            ),
            (table.extend, [], {"text_colors": [[None, None]]}),
        ):
            with self.subTest(method=method.__name__, data=data, options=options):
                with self.assertRaises((TypeError, ValueError)):
                    method(data, **options)
                self.assertEqual(table.display_value(table.get()), initial)
        table.extend([])
        table.extend(np.empty((0, 2)), [], [])
        self.assertEqual(table.display_value(table.get()), initial)

    def test_additions_copy_inputs_and_publish_complete_snapshots(self):
        with Card(0, 0, 4, 3, "Table", runtime=FakeRuntime()) as card:
            table = Table(["A", "B"], 2, [1, 1])
        row, texts = [1, 2], ["red", None]
        table.append(row, texts)
        first = card._latest_payload[table.name]
        row[0], texts[0] = 100, "blue"
        rows, backgrounds = [[3, 4]], [[None, "green"]]
        table.extend(rows, bg_colors=backgrounds)
        rows[0][0], backgrounds[0][1] = 200, "yellow"
        payload = pickle.loads(pickle.dumps(card._latest_payload))[table.name]
        self.assertEqual(payload["data"], [["1", "2"], ["3", "4"]])
        self.assertEqual(payload["text_colors"], [["red", None], [None, None]])
        self.assertEqual(payload["bg_colors"], [[None, None], [None, "green"]])
        self.assertEqual(first["data"], [["1", "2"]])
        self.assertEqual(first["text_colors"], [["red", None]])
        self.assertEqual(table.get(), [[1, 2], [3, 4]])

    def test_scroll_target_crosses_ui_transport_and_resets_on_set(self):
        with Card(0, 0, 4, 3, "Table", runtime=FakeRuntime()) as card:
            table = Table(["A"], 2, [1])
        self.assertNotIn("scroll_to_end", table.display_value(table.get()))
        for add, data in ((table.append, [1]), (table.extend, [[2], [3]])):
            add(data)
            payload = pickle.loads(pickle.dumps(card._latest_payload))[table.name]
            self.assertTrue(payload["scroll_to_end"])
            table.set([[0]])
            self.assertNotIn("scroll_to_end", card._latest_payload[table.name])
        table.append([4])
        table.reset()
        self.assertNotIn("scroll_to_end", card._latest_payload[table.name])

    def test_concurrent_additions_keep_all_rows_and_associated_colors(self):
        table = Table(["ID"], 2, [1])

        def add(index):
            color = "red" if index % 2 else "blue"
            if index % 2:
                table.append([index], [color])
            else:
                table.extend([[index]], [[color]])

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(add, range(80)))
        data = table.get()
        self.assertEqual(sorted(row[0] for row in data), list(range(80)))
        payload = table.display_value(data)
        self.assertEqual(
            payload["text_colors"], [["red" if row[0] % 2 else "blue"] for row in data]
        )

    def test_invalid_updates_are_atomic(self):
        table = Table(["A", "B"], 2, [1, 1])
        table.set([[1, 2]], [["red", None]])
        initial = table.display_value(table.get())
        for data, options in (
            ([1, 2], {}),
            ([[1]], {}),
            ([[1, 2], [3]], {}),
            (np.zeros((1, 2, 1)), {}),
            (np.zeros((0, 3)), {}),
            ("bad", {}),
            ([[3, 4]], {"text_colors": []}),
            ([[3, 4]], {"bg_colors": [[None]]}),
            ([[3, 4]], {"text_colors": [[None, 42]]}),
            ([[3, 4]], {"text_colors": [[None, "transparent"]]}),
        ):
            with self.subTest(data=data, options=options):
                with self.assertRaises((TypeError, ValueError)):
                    table.set(data, **options)
                self.assertEqual(table.display_value(table.get()), initial)
        table.set(np.empty((0, 2)))
        self.assertEqual(table.get(), [])

    def test_invalid_constructor(self):
        for args in (
            ([], 1, []),
            ([1], 1, [1]),
            (["A"], 1, []),
            (["A"], 1, [0]),
            (["A"], 1, [-1]),
            (["A"], 1, [float("inf")]),
            (["A"], 1, [float("nan")]),
            (["A"], 1, [True]),
            (["A"], 1, ["1"]),
            (["A"], 1, "1"),
            (["A"], 0),
            (["A"], True),
        ):
            with self.subTest(args=args):
                with self.assertRaises((TypeError, ValueError)):
                    Table(*args)

    def test_card_publishes_self_contained_picklable_updates(self):
        with Card(0, 0, 4, 3, "Table", runtime=FakeRuntime()) as card:
            table = Table(["A", "B"], 3, [1, 2])
        table.set([[1, "ready"]], bg_colors=[[None, ("white", "black")]])
        payload = pickle.loads(pickle.dumps(card._latest_payload))[table.name]
        table.set([[2, "done"]])
        self.assertEqual(payload["data"], [["1", "ready"]])
        self.assertEqual(payload["bg_colors"], [[None, ("white", "black")]])
        restored = pickle.loads(pickle.dumps(table))
        self.assertEqual(
            restored.display_value([[2, "done"]]), table.display_value(table.get())
        )


class TableRenderingTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("500x320")
        self.element = Table(["Name", "Value"], 3, [1, 3])
        self.ui = Card._create_ui(
            self.root,
            emit=lambda _value: None,
            elements=[self.element],
            element_states={},
        )
        self.renderer = self.element._ui
        self.element.set([[f"Row {i}", i] for i in range(20)])
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()

    def test_large_table_reuses_visible_items_across_scroll_and_update(self):
        self.element.set([[f"Row {i}", i] for i in range(10000)])
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()
        body = self.renderer._body
        original = body.find_all()
        self.assertLess(len(original), 50)
        body.yview_moveto(0.5)
        self.root.update()
        self.assertEqual(body.find_all()[:len(original)], original)
        texts = [body.itemcget(item, "text") for item in original if body.type(item) == "text"]
        self.assertTrue(any("Row 5000" in text for text in texts))
        self.element.append(["Last row", 10000])
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()
        self.assertLess(len(body.find_all()), 50)
        self.assertTrue(any(body.itemcget(item, "text") == "Last row"
                            for item in body.find_all() if body.type(item) == "text"))

    def test_header_widths_visible_rows_and_nested_wheel(self):
        renderer = self.renderer
        height = renderer._row_height
        self.assertEqual(renderer._body.winfo_height(), 3 * height)
        self.assertLess(renderer._body.yview()[1], 1)
        rectangles = renderer._body.find_all()[::2]
        first, second = (renderer._body.coords(item) for item in rectangles[:2])
        self.assertAlmostEqual(first[2] - first[0], (second[2] - second[0]) / 3)
        header = [
            (renderer._header.coords(item), renderer._header.itemcget(item, "text"))
            for item in renderer._header.find_all()
            if renderer._header.type(item) == "text"
        ]
        card_canvas = self.ui._container._parent_canvas
        parent_view = card_canvas.yview()
        renderer._body.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(renderer._body.yview()[0], 0)
        self.assertEqual(card_canvas.yview(), parent_view)
        self.assertEqual(
            header,
            [
                (renderer._header.coords(item), renderer._header.itemcget(item, "text"))
                for item in renderer._header.find_all()
                if renderer._header.type(item) == "text"
            ],
        )
        renderer._body.yview_moveto(1)
        renderer._body.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertEqual(card_canvas.yview(), parent_view)

    def test_set_scrolls_to_top_and_additions_show_last_row(self):
        renderer = self.renderer
        for add, data in (
            (self.element.append, ["Last appended", 20]),
            (self.element.extend, [["Next", 21], ["Last extended", 22]]),
        ):
            with self.subTest(method=add.__name__):
                add(data)
                self.element.update_ui(self.element.display_value(self.element.get()))
                self.root.update()
                self.assertGreater(renderer._body.yview()[0], 0)
                self.assertAlmostEqual(renderer._body.yview()[1], 1.0)
                last_bottom = len(self.element) * renderer._row_height
                viewport_bottom = renderer._body.canvasy(renderer._body.winfo_height())
                self.assertAlmostEqual(viewport_bottom, last_bottom)
                self.element.set([[f"Row {i}", i] for i in range(20)])
                self.element.update_ui(self.element.display_value(self.element.get()))
                self.root.update()
                self.assertEqual(renderer._body.yview()[0], 0.0)
                self.assertLess(renderer._body.yview()[1], 1.0)
        self.element.reset()
        self.element.append(["First", 1])
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()
        self.assertEqual(renderer._body.yview(), (0.0, 1.0))

    def test_copy_button_copies_headers_and_all_untruncated_cells_as_csv(self):
        self.element.columns[:] = ["名前,項目", '値"詳細']
        # The renderer shares the element's column names in this UI process.
        data = [["日本語," * 50, 'quoted "value"'], ["line\nbreak", ""]]
        self.element.set(data)
        for change in (
            lambda: None,
            lambda: self.element.append(["append", 42]),
            lambda: self.element.extend([["extend", 43], ["last", 44]]),
            self.element.reset,
        ):
            change()
            self.element.update_ui(self.element.display_value(self.element.get()))
            self.root.update()
            self.root.clipboard_clear()
            self.root.clipboard_append("previous content")
            self.renderer._copy_button.invoke()
            copied = list(
                csv.reader(io.StringIO(self.root.clipboard_get(), newline=""))
            )
            self.assertEqual(
                copied,
                [self.element.columns]
                + [[str(cell) for cell in row] for row in self.element.get()],
            )

    def test_copy_button_stays_in_header_when_scrolled_and_resized(self):
        renderer = self.renderer
        for width in (500, 300):
            self.root.geometry(f"{width}x320")
            renderer._body.yview_moveto(1)
            self.root.update()
            header, button = renderer._header, renderer._copy_button
            self.assertGreaterEqual(button.winfo_rooty(), header.winfo_rooty())
            self.assertLessEqual(
                button.winfo_rooty() + button.winfo_height(),
                header.winfo_rooty() + header.winfo_height(),
            )
            self.assertLessEqual(
                button.winfo_rootx() + button.winfo_width(),
                header.winfo_rootx() + header.winfo_width(),
            )
            self.assertGreater(
                button.winfo_rootx(), header.winfo_rootx() + header.winfo_width() / 2
            )
            last_text = [
                item for item in header.find_all() if header.type(item) == "text"
            ][-1]
            self.assertLessEqual(
                header.bbox(last_text)[2] + header.winfo_rootx(), button.winfo_rootx()
            )

    def test_colors_defaults_truncation_resize_and_clear(self):
        renderer = self.renderer
        self.element.set(
            [["Long text " * 50, 2], [3, 4]],
            text_colors=[["red", None], [None, None]],
            bg_colors=[[None, "blue"], [None, None]],
        )
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()
        items = renderer._body.find_all()
        self.assertEqual(
            renderer._body.itemcget(items[0], "fill"),
            theme.color(theme.WINDOW_BG_COLOR),
        )
        self.assertEqual(renderer._body.itemcget(items[1], "fill"), "red")
        self.assertTrue(renderer._body.itemcget(items[1], "text").endswith("…"))
        self.assertEqual(renderer._body.itemcget(items[2], "fill"), "blue")
        self.assertEqual(
            renderer._body.itemcget(items[3], "fill"),
            theme.color(theme.TEXT_FONT_COLOR),
        )
        self.assertEqual(
            renderer._body.itemcget(items[4], "fill"), theme.color(theme.CARD_BG_COLOR)
        )
        self.root.geometry("700x320")
        self.root.update()
        self.assertEqual(renderer._body.yview(), (0.0, 1.0))
        self.assertFalse(renderer._scrollbar.winfo_manager())
        self.element.reset()
        self.element.update_ui(self.element.display_value(self.element.get()))
        self.root.update()
        self.assertEqual(renderer._body.find_all(), ())
        self.assertTrue(renderer._header.find_all())


if __name__ == "__main__":
    unittest.main()
