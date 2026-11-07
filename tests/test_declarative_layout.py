"""Exercise the declaration API through transport, rendering and Dealer dispatch."""

import pickle
import unittest
from threading import Barrier, Thread
from unittest.mock import Mock, patch

import numpy as np
from test_widgets import FakeControl, FakeRuntime

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.widgets.elements.button import _BtnPressed


class DeclarativeLayoutTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_pattern_three_dispatches_callbacks_using_original_references(self):
        class App(c.Dealer):
            def setup(self):
                with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as self.card:
                    self.img = c.Image()
                    self.img_keep = c.Image()
                    self.mode = c.Radio(["A", "B", "C"])
                    self.input = c.Entry("Input here")
                    c.Separator()
                    self.val = c.Slider(0, 100, 1)
                    with c.Row():
                        self.btn_cap = c.Btn("Capture", self.capture)
                        self.btn_show = c.Btn("Keep", self.keep)
                self.events = []

            def capture(self, event: c.TriggerEvent):
                self.events.append(event)
                self.img.set(np.full((2, 3, 3), 7, dtype=np.uint8))

            def keep(self, event: c.TriggerEvent):
                self.img_keep.set(self.img.get())

        app = App()
        app.card._receive_input(_BtnPressed(app.btn_cap.id))
        app.wait_for_idle(timeout=1)
        app.card._receive_input(_BtnPressed(app.btn_show.id))
        app.wait_for_idle(timeout=1)
        self.assertEqual(app.card.geometry, (0, 0, 4, 4))
        self.assertEqual(app.mode.get(), "A")
        self.assertEqual(app.input.place_holder, "Input here")
        self.assertIsInstance(app.events[0], c.TriggerEvent)
        np.testing.assert_array_equal(app.img_keep.get(), app.img.get())
        app.close()

    def test_row_renders_mixed_elements_in_separate_equal_width_cells(self):
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            first = c.Entry()
            with c.Row():
                radio = c.Radio(["A", "B"])
                button = c.Btn("Run")
            last = c.Entry()
        ui = object.__new__(c.Card)
        rendered = []
        ui._build_element_ui = lambda parent, element, emit: rendered.append(
            (parent, element)
        )
        ui._update_element = lambda *args, **kwargs: None

        def scrollable_frame(parent, **options):
            frame = FakeControl(parent, **options)
            frame._parent_canvas = FakeControl(frame)
            frame._scrollbar = Mock()
            return frame

        with (
            patch("customtkinter.CTkFrame", side_effect=FakeControl),
            patch("customtkinter.CTkScrollableFrame", side_effect=scrollable_frame),
        ):
            ui._build_ui(object(), emit=lambda event: None, **card._ui_options)
        self.assertEqual(
            [e.name if isinstance(e, c.Element) else e.id for _, e in rendered],
            [first.name, radio.name, button.name, last.name],
        )
        self.assertIs(rendered[0][0], rendered[3][0])
        left_cell, right_cell = rendered[1][0], rendered[2][0]
        self.assertIs(left_cell.parent, right_cell.parent)
        self.assertEqual(left_cell.grid_options["column"], 0)
        self.assertEqual(right_cell.grid_options["column"], 1)
        self.assertEqual(left_cell.parent.grid_columns[0]["weight"], 1)
        self.assertIsNot(left_cell, right_cell)

    def test_nested_cards_restore_the_outer_registration_target(self):
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as outer:
            first = c.Image()
            with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as inner:
                middle = c.Image()
            last = c.Image()
        self.assertEqual(outer.elements, (first, last))
        self.assertEqual(inner.elements, (middle,))
        self.assertIsNone(getattr(c.Image(), "_owner", None))

    def test_concurrent_definitions_do_not_mix_elements(self):
        barrier = Barrier(2)
        results = []
        errors = []

        def define():
            try:
                with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
                    with c.Row():
                        first = c.Image()
                        barrier.wait(timeout=2)
                        second = c.Image()
                results.append((card, first, second))
            except Exception as error:
                errors.append(error)

        threads = [Thread(target=define), Thread(target=define)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        for card, first, second in results:
            self.assertEqual(card.elements, (first, second))
            self.assertEqual(card._ui_options["layout"], ((0, 1),))

    def test_exception_discards_declarations_and_restores_context(self):
        card = c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime())
        with self.assertRaisesRegex(ValueError, "abort"):
            with card:
                c.Image()
                raise ValueError("abort")
        self.assertFalse(card.elements)
        self.assertIsNone(getattr(c.Image(), "_owner", None))
        with card:
            image = c.Image()
        self.assertEqual(card.elements, (image,))

    def test_rows_require_a_card_and_reject_nesting_and_empty_rows(self):
        with self.assertRaisesRegex(RuntimeError, "inside a Card"):
            with c.Row():
                pass
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            local = c.Image()
            with self.assertRaisesRegex(ValueError, "at least one"):
                with c.Row():
                    pass
            with c.Row():
                first = c.Image()
                with self.assertRaisesRegex(RuntimeError, "nested"):
                    with c.Row():
                        pass
                second = c.Image()
            last = c.Image()
        self.assertEqual(card.elements, (local, first, second, last))
        self.assertEqual(card._ui_options["layout"], (0, (1, 2), 3))

    def test_row_exception_discards_its_elements_and_restores_card_context(self):
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            first = c.Image()
            with self.assertRaisesRegex(ValueError, "abort"):
                with c.Row():
                    discarded = c.Image()
                    raise ValueError("abort")
            with c.Row():
                red = c.LED("red", "LED")
                green = c.LED("limegreen", "Cap.")
            last = c.Image()
        self.assertEqual(card.elements, (first, red, green, last))
        self.assertEqual(card._ui_options["layout"], (0, (1, 2), 3))
        self.assertIsNone(discarded._owner)
        self.assertIsNone(c.Image()._owner)

    def test_nested_card_restores_enclosing_row_context(self):
        with c.Card(0, 0, 4, 4, "Outer", runtime=FakeRuntime()) as outer:
            with c.Row():
                first = c.Image()
                with c.Card(0, 0, 4, 4, "Inner", runtime=FakeRuntime()) as inner:
                    with c.Row():
                        middle = c.Image()
                last = c.Image()
            after = c.Image()
        self.assertEqual(outer.elements, (first, last, after))
        self.assertEqual(outer._ui_options["layout"], ((0, 1), 2))
        self.assertEqual(inner.elements, (middle,))
        self.assertEqual(inner._ui_options["layout"], ((0,),))

    def test_initial_values_and_resets_are_published_without_losing_other_values(self):
        runtime = FakeRuntime()
        with c.Card(0, 0, 4, 4, "Card", runtime=runtime) as card:
            image = c.Image()
            image.set(np.ones((2, 2, 3), dtype=np.uint8))
            mode = c.Radio(["A", "B"], default="B")
            text = c.Text()
            text.set({"ok": True})
        card.start()
        np.testing.assert_array_equal(runtime.updates[-1][1][image.name], 1)
        mode.set("A")
        image.reset()
        mode.reset()
        text.reset()
        self.assertIsNone(image.get())
        self.assertEqual(mode.get(), "B")
        self.assertEqual(text.get(), "")
        self.assertEqual(text.mode, "plain")
        self.assertIsNone(runtime.updates[-3][1][image.name])
        self.assertEqual(runtime.updates[-2][1], {mode.name: "B"})
        self.assertEqual(set(runtime.updates[-1][1]), {text.name})
        self.assertIsNone(card._latest_payload[image.name])
        self.assertEqual(card._latest_payload[mode.name], "B")
        pickle.dumps(card._ui_options)

    def test_direct_input_reads_poll_and_explicit_writes_override_queued_edits(self):
        runtime = FakeRuntime()
        with c.Card(0, 0, 4, 4, "Card", runtime=runtime) as card:
            entry = c.Entry()
        card.start()
        pending = ["from UI"]

        def poll():
            if pending:
                card._receive_input({entry.name: pending.pop()})

        runtime.poll = poll
        self.assertEqual(entry.get(), "from UI")
        pending.append("stale UI edit")
        entry.set("explicit override")
        self.assertEqual(entry.get(), "explicit override")

    def test_input_notifications_contain_the_original_element(self):
        changes = []
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            entry = c.Entry(on_input=changes.append)
        card._receive_input({entry.name: "edited"})
        self.assertIsInstance(changes[0], c.InputEvent)
        self.assertIs(changes[0].element, entry)
        self.assertEqual(changes[0].value, "edited")
        entry.set("program")
        entry.reset()
        self.assertEqual(len(changes), 1)

    def test_input_callbacks_publish_the_current_input_with_display_changes(self):
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            entry = c.Entry()
            text = c.Text()
        entry.on_input = lambda change: text.set(change.value)
        card._receive_input({entry.name: "edited"})
        self.assertEqual(card._latest_payload[entry.name], "edited")
        self.assertEqual(card._latest_payload[text.name]["text"], "edited")

    def test_slider_input_callback_stays_in_controller_process(self):
        events = []
        with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            slider = c.Slider(0, 100, 1, on_input=events.append)
            other = c.Entry()
        ui_slider = pickle.loads(pickle.dumps(card._ui_options["elements"][0]))
        self.assertIsNone(ui_slider.on_input)
        card._receive_input({other.name: "unrelated"})
        slider.set(20)
        self.assertEqual(events, [])
        card._receive_input({slider.name: 42})
        self.assertEqual(slider.get(), 42)
        self.assertEqual(card._latest_payload[slider.name], 42)
        self.assertIs(events[0].element, slider)
        self.assertEqual(events[0].value, 42)
        with self.assertRaises(TypeError):
            c.Slider(0, 100, 1, on_input=42)

    def test_button_callback_receives_current_event(self):
        class App(c.Dealer):
            def setup(self):
                with c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as self.card:
                    self.button = c.Btn("Run", callback=self.callback)
                self.called = False

            def callback(self, event: c.TriggerEvent):
                self.called = event is self.current_event

        app = App()
        app.card._receive_input(_BtnPressed(app.button.id))
        app.wait_for_idle(timeout=1)
        self.assertTrue(app.called)
        app.close()

    def test_id_constructor_arguments_and_id_lookup_apis_are_removed(self):
        for construct in (
            lambda: c.Image(name="preview"),
            lambda: c.Text("result"),
            lambda: c.Radio("mode", ["A", "B"]),
            lambda: c.Slider("value", 0, 100, 1),
            lambda: c.Btn("capture", "Capture"),
            lambda: c.Entry(name="prompt"),
            lambda: c.Btn(id="run", label="Run"),
        ):
            with self.assertRaises(TypeError):
                construct()
        card = c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime())
        for name in ("get", "set", "element", "button", "enable", "disable"):
            self.assertFalse(hasattr(card, name))

    def test_layout_cannot_be_changed_or_started_mid_definition(self):
        card = c.Card(0, 0, 4, 4, "Card", runtime=FakeRuntime())
        with card:
            c.Image()
            with self.assertRaisesRegex(RuntimeError, "finish"):
                card.start()
        with self.assertRaisesRegex(RuntimeError, "once"):
            with card:
                pass


if __name__ == "__main__":
    unittest.main()
