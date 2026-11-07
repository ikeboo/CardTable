"""Text append semantics and atomic controller updates."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from test_widgets import FakeRuntime

from cardtable import Card, Text
from cardtable.core.closure import Closure


class TextAppendTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_append_to_initial_and_existing_text_without_implicit_newlines(self):
        text = Text()
        self.assertIsNone(text.append("Hello"))
        text.append(", world")
        text.append("\nこんにちは")
        text.append("")
        self.assertEqual(text.get(), "Hello, world\nこんにちは")
        self.assertEqual(text.mode, "plain")
        text.reset()
        text.append("again")
        self.assertEqual(text.get(), "again")

    def test_append_preserves_markdown_source_and_publishes_current_mode(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Text", runtime=runtime) as card:
            text = Text()
        text.set("# Heading", mode="markdown")
        text.append("\n\n**Before start**")
        card.start()
        self.assertTrue(runtime.updates[-1][1][text.name]["scroll_to_end"])
        text.append(" and *after start*")
        expected = "# Heading\n\n**Before start** and *after start*"
        self.assertEqual(text.get(), expected)
        self.assertEqual(text.mode, "markdown")
        self.assertEqual(
            runtime.updates[-1],
            (
                card.widget_id,
                {
                    text.name: {
                        "text": expected,
                        "mode": "markdown",
                        "scroll_to_end": True,
                    }
                },
            ),
        )

    def test_set_and_reset_restore_top_scroll_after_append(self):
        text = Text()
        text.append("first")
        self.assertTrue(text.display_value(text.get())["scroll_to_end"])
        text.set("replacement")
        self.assertFalse(text.display_value(text.get()).get("scroll_to_end", False))
        text.append("last")
        self.assertTrue(text.display_value(text.get())["scroll_to_end"])
        text.reset()
        self.assertFalse(text.display_value(text.get()).get("scroll_to_end", False))

    def test_invalid_append_does_not_change_value_mode_or_publish(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Text", runtime=runtime) as card:
            text = Text()
        card.start()
        for mode, value in (("plain", "hello"), ("markdown", "**hello**")):
            text.set(value, mode=mode)
            updates = list(runtime.updates)
            for invalid in (None, 1, b"bytes", ["text"]):
                with self.subTest(mode=mode, invalid=invalid):
                    with self.assertRaisesRegex(TypeError, "must be a string"):
                        text.append(invalid)
                    self.assertEqual(text.get(), value)
                    self.assertEqual(text.mode, mode)
                    self.assertEqual(runtime.updates, updates)
        text.set({"ok": True})
        previous = text.get()
        updates = list(runtime.updates)
        for suffix in ("more", ""):
            with self.assertRaisesRegex(ValueError, "JSON mode"):
                text.append(suffix)
        self.assertEqual(text.get(), previous)
        self.assertEqual(text.mode, "json")
        self.assertEqual(runtime.updates, updates)

    def test_concurrent_appends_preserve_every_chunk_and_publication_order(self):
        for bound in (False, True):
            with self.subTest(bound=bound):
                runtime = FakeRuntime()
                if bound:
                    with Card(0, 0, 4, 4, "Text", runtime=runtime) as card:
                        text = Text()
                    card.start()
                else:
                    text = Text()
                barrier = Barrier(8)

                def append_chunks(index):
                    barrier.wait(3)
                    for _ in range(100):
                        text.append(str(index))

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(append_chunks, range(8)))
                result = text.get()
                self.assertEqual(len(result), 800)
                for index in range(8):
                    self.assertEqual(result.count(str(index)), 100)
                if bound:
                    published = [
                        update[1][text.name]["text"] for update in runtime.updates
                    ]
                    self.assertEqual(
                        [len(value) for value in published], list(range(801))
                    )
                    self.assertTrue(all(result.startswith(value) for value in published))

    def test_append_holds_element_lock_through_validation_and_commit(self):
        for operation in ("append", "set", "reset", "get"):
            with self.subTest(operation=operation):
                entered, release, attempted, finished = (Event() for _ in range(4))

                class BlockingText(Text):
                    def normalize(self, value):
                        if value == "first":
                            entered.set()
                            if not release.wait(3):
                                raise TimeoutError("append validation was not released")
                        return super().normalize(value)

                text = BlockingText()

                def second_call():
                    attempted.set()
                    args = ("second",) if operation in ("append", "set") else ()
                    result = getattr(text, operation)(*args)
                    finished.set()
                    return result

                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(text.append, "first")
                    try:
                        self.assertTrue(entered.wait(1))
                        second = pool.submit(second_call)
                        self.assertTrue(attempted.wait(1))
                        self.assertFalse(finished.wait(0.05))
                    finally:
                        release.set()
                    first.result(timeout=3)
                    result = second.result(timeout=3)
                expected = {
                    "append": "firstsecond",
                    "set": "second",
                    "reset": "",
                    "get": "first",
                }
                self.assertEqual(text.get(), expected[operation])
                if operation == "get":
                    self.assertEqual(result, "first")


if __name__ == "__main__":
    unittest.main()
