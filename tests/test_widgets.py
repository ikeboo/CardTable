import inspect
import pickle
import tkinter as tk
import unittest
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import Mock, patch

import numpy as np

from cardtable import (
    Btn,
    Button,
    ButtonControl,
    Card,
    Deck,
    Element,
    Entry,
    FileDrop,
    Image,
    InputElement,
    Number,
    Radio,
    RangeSlider,
    Row,
    Separator,
    Slider,
    Text,
    TriggerEvent,
)
from cardtable.core.closure import Closure
from cardtable.widgets._geometry import (
    grid_to_pixels,
    move_grid_geometry,
    resize_grid_geometry,
)
from cardtable.widgets._runtime import CardRuntime
from cardtable.widgets._ui_process import (
    _drag_geometry,
    _move_geometry,
    _next_geometry,
    _resize_geometry,
    _resolve_class,
)
from cardtable.widgets.deck import _DeckSettings
from cardtable.widgets.elements._range_slider_control import _RangeSliderControl
from cardtable.widgets.elements.button import _BtnPressed
from cardtable.widgets.elements.entry import _EntryUI
from cardtable.widgets.elements.file_drop import (
    _ellipsize,
    _file_drop_text,
    _FileDropUI,
)
from cardtable.widgets.elements.image import _fit_size, _ImageRenderer
from cardtable.widgets.elements.number import _NumberUI
from cardtable.widgets.elements.radio import _RadioUI
from cardtable.widgets.elements.range_slider import _RangeSliderUI
from cardtable.widgets.elements.slider import _SliderUI
from cardtable.widgets.elements.text import _background_color, _markdown_segments


class FakeRuntime:
    def __init__(self):
        self.attached = []
        self.updates = []
        self.detached = []
        self.waited = []
        self.visibility = []
        self.button_updates = []
        self.element_updates = []
        self.polled = 0

    def attach(self, widget):
        self.attached.append(widget)

    def update(self, widget_id, payload):
        self.updates.append((widget_id, payload))

    def detach(self, widget_id):
        self.detached.append(widget_id)

    def set_visibility(self, widget_id, *, visible):
        self.visibility.append((widget_id, visible))

    def update_button(self, widget_id, button_id, *, state, label):
        self.button_updates.append((widget_id, button_id, state, label))

    def update_element(self, widget_id, element_id, *, state, label):
        self.element_updates.append((widget_id, element_id, state, label))

    def wait_ready(self, widget_id, *, timeout):
        self.waited.append((widget_id, timeout))

    def poll(self):
        self.polled += 1

    def raise_for_widget(self, widget_id):
        pass


class AliveProcess:
    def is_alive(self):
        return True


class FakeControl:
    def __init__(self, parent, **options):
        self.parent = parent
        self.options = options
        self.pack_options = None
        self.grid_options = None
        self.grid_columns = {}

    def pack(self, **options):
        self.pack_options = options
        return self

    def configure(self, **options):
        self.options.update(options)

    def delete(self, _first, _last=None):
        self.value = ""

    def insert(self, _index, value):
        self.value = str(value)

    def get(self):
        return getattr(self, "value", "")

    def cget(self, name):
        return self.options.get(name)

    def grid(self, **options):
        self.grid_options = options
        return self

    def grid_columnconfigure(self, column, **options):
        self.grid_columns[column] = options

    def winfo_toplevel(self):
        return self

    def winfo_manager(self):
        return "pack" if self.pack_options is not None else ""

    def pack_propagate(self, value):
        self.pack_propagate_value = value

    def bind(self, event, callback):
        pass

    def drop_target_register(self, *types):
        pass

    def dnd_bind(self, event, callback):
        pass


class WidgetProxyTest(unittest.TestCase):
    def setUp(self):
        font = patch(
            "cardtable.widgets.elements._fonts.ctk_font", return_value=("Arial", 12)
        )
        font.start()
        self.addCleanup(font.stop)

    def tearDown(self):
        Closure().close_all()

    def test_button_disables_immediately_and_preserves_manual_state(self):
        def callback(event: TriggerEvent):
            pass

        definition = Button("Save", callback)._ui_copy()
        emitted = []
        with patch("customtkinter.CTkButton", FakeControl):
            control = definition.build_ui(Mock(), emitted.append)
        press = control.options["command"]
        press()
        press()
        self.assertEqual(emitted, [_BtnPressed(definition.id)])
        self.assertEqual(control.options["state"], "disabled")

        definition.update_state_ui(control, "normal", "Saving")
        self.assertEqual(control.options["state"], "disabled")
        ui = object.__new__(Card)
        ui._buttons = {definition.id: control}
        ui._button_definitions = {definition.id: definition}
        ui._finish_button_ui(definition.id)
        self.assertEqual(control.options["state"], "normal")
        press()
        self.assertEqual(len(emitted), 2)
        definition.update_state_ui(control, "disabled", "Stopped")
        ui._finish_button_ui(definition.id)
        self.assertEqual(control.options["state"], "disabled")
        self.assertEqual(control.options["text"], "Stopped")

    def test_button_without_callback_does_not_wait_for_completion(self):
        definition = Button("Select")._ui_copy()
        emitted = []
        with patch("customtkinter.CTkButton", FakeControl):
            control = definition.build_ui(Mock(), emitted.append)
        control.options["command"]()
        control.options["command"]()
        self.assertEqual(len(emitted), 2)
        self.assertEqual(control.options["state"], "normal")

    def test_image_view_keeps_latest_value_until_started(self):
        runtime = FakeRuntime()
        source = np.zeros((2, 3, 3), dtype=np.uint8)
        with Card(0, 0, 4, 4, "Preview", runtime=runtime) as viewer:
            image_element = Image()

        image_element.set(source)
        source[:] = 255
        self.assertEqual(runtime.updates, [])

        viewer.start()

        self.assertEqual(runtime.attached, [viewer])
        self.assertEqual(len(runtime.updates), 1)
        np.testing.assert_array_equal(runtime.updates[0][1][image_element.name], 0)

    def test_widget_class_is_also_used_for_its_ui(self):
        self.assertEqual(Card._class_path, "cardtable.widgets.card.card:Card")
        self.assertIs(_resolve_class(Card._class_path), Card)

    def test_text_view_stores_and_publishes_plain_text(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Result", runtime=runtime) as card:
            viewer = Text()

        viewer.set("hello")
        self.assertEqual(viewer.get(), "hello")
        card.start()

        self.assertEqual(
            runtime.updates,
            [(card.widget_id, {viewer.name: {"text": "hello", "mode": "plain"}})],
        )

    def test_text_view_formats_mappings_as_highlighted_json(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Result", runtime=runtime) as card:
            viewer = Text()
        card.start()

        viewer.set({"message": "こんにちは", "count": 2})

        self.assertEqual(
            viewer.get(),
            '{\n  "message": "こんにちは",\n  "count": 2\n}',
        )
        self.assertEqual(runtime.updates[-1][1][viewer.name]["mode"], "json")

    def test_text_view_validates_explicit_modes(self):
        viewer = Text()

        with self.assertRaisesRegex(ValueError, "plain.*json.*markdown"):
            viewer.set("text", mode="html")
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            viewer.set("not-json", mode="json")
        with self.assertRaisesRegex(TypeError, "must be a string"):
            viewer.set(["not", "markdown"], mode="markdown")

    def test_markdown_renderer_removes_markup_and_preserves_styles(self):
        segments = _markdown_segments("# Heading\n\nA **bold** value with `code`.")
        rendered = "".join(value for value, _tags in segments)

        self.assertNotIn("#", rendered)
        self.assertNotIn("**", rendered)
        self.assertIn("Heading", rendered)
        self.assertTrue(
            any(value == "bold" and "md_bold" in tags for value, tags in segments)
        )
        self.assertTrue(
            any(value == "code" and "md_code" in tags for value, tags in segments)
        )

    def test_markdown_renderer_does_not_add_a_leading_blank_line(self):
        for source in ("# Heading", "- item", "> quote", "```\ncode\n```"):
            rendered = "".join(value for value, _tags in _markdown_segments(source))
            self.assertFalse(rendered.startswith("\n"), source)

    def test_image_view_updates_after_start_and_detaches(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Preview", runtime=runtime) as viewer:
            image_element = Image()
        image = np.zeros((2, 2), dtype=np.uint8)

        viewer.start()
        viewer.wait_ready()
        image_element.set(image)
        viewer.stop()

        self.assertEqual(runtime.waited, [(viewer.widget_id, 10.0)])
        self.assertEqual(runtime.updates[0][0], viewer.widget_id)
        self.assertEqual(runtime.detached, [viewer.widget_id])

    def test_image_view_rejects_unsupported_shape(self):
        image_element = Image()

        with self.assertRaisesRegex(ValueError, "2D or 3D"):
            image_element.set(np.zeros((1, 2, 3, 4), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "3-channel BGR"):
            image_element.set(np.zeros((2, 2, 2), dtype=np.uint8))

    def test_image_view_publishes_none_for_empty_image(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Preview", runtime=runtime) as viewer:
            image_element = Image()
        viewer.start()
        self.assertIsNone(runtime.updates[-1][1][image_element.name])

        image_element.set(None)

        self.assertIsNone(runtime.updates[-1][1][image_element.name])
        self.assertIsNone(image_element.get())

    def test_image_view_fits_the_whole_image_without_cropping(self):
        self.assertEqual(_fit_size((1600, 900), (800, 600), (2000, 2000)), (800, 450))
        self.assertEqual(_fit_size((600, 900), (800, 600), (2000, 2000)), (400, 600))
        self.assertEqual(_fit_size((100, 50), (800, 600), (2000, 2000)), (800, 400))

    def test_image_view_fit_honors_max_size(self):
        self.assertEqual(_fit_size((1600, 900), (1600, 1200), (800, 600)), (800, 450))

    def test_image_ui_converts_arrays_with_pillow_image(self):
        ui = object.__new__(_ImageRenderer)
        scheduled = []
        ui._schedule_render = lambda: scheduled.append(True)

        ui.update(np.zeros((3, 4, 3), dtype=np.uint8))

        self.assertEqual(ui._source_image.size, (4, 3))
        self.assertEqual(scheduled, [True])

    def test_element_renderers_preserve_layout_and_apply_card_updates(self):
        with Card(0, 0, 4, 4, "Preview", runtime=FakeRuntime()) as card:
            image = Image(aspect=(16, 9))
            text = Text(rows=3, label="Result")
        ui = object.__new__(Card)
        ui._ui_elements = {e.name: e for e in card._ui_options["elements"]}
        frames = []

        def make_frame(parent, **options):
            frame = Mock()
            frame.cget.return_value = "transparent"
            frame.master = None
            frames.append((frame, options))
            return frame

        font = Mock()
        font.cget.side_effect = {"size": 12, "family": "Arial"}.__getitem__
        with (
            patch("customtkinter.CTkFrame", side_effect=make_frame),
            patch("customtkinter.CTkLabel"),
            patch("customtkinter.CTkScrollbar"),
            patch("customtkinter.CTkButton"),
            patch("tkinter.Canvas"),
            patch("tkinter.Text") as text_class,
            patch("cardtable.widgets.elements._fonts.tk_font", return_value=font),
            patch("tkinter.font.nametofont", return_value=font),
        ):
            text_class.return_value.bindtags.return_value = (
                ".text",
                "Text",
                ".",
                "all",
            )
            for element in ui._ui_elements.values():
                ui._build_element_ui(object(), element, lambda event: None)
            image.set(np.array([[[1, 2, 3]]], dtype=np.uint8))
            text.set("**Result**", mode="markdown")
            ui._update_ui(card._latest_payload)

        self.assertEqual(frames[0][1]["height"], 180)
        self.assertEqual(frames[1][1]["height"], 124)
        image_frame = frames[0][0]
        resize = image_frame.bind.call_args.args[1]
        resize(Mock(width=640))
        image_frame.configure.assert_called_with(height=360)
        renderer = ui._ui_elements[image.name]._ui
        self.assertEqual(renderer._source_image.getpixel((0, 0)), (3, 2, 1))
        text_widget = text_class.return_value
        text_widget.insert.assert_called_with("end", "Result", ("md_bold",))
        text_widget.configure.assert_called_with(state="disabled")
        # UI creation must leave controller definitions serializable.
        pickle.dumps(card._ui_options)

    def test_image_view_runtime_keeps_only_latest_pending_frame(self):
        runtime = CardRuntime()
        runtime._process = AliveProcess()
        runtime._command_queue = Queue()
        runtime._event_queue = Queue()
        viewer = Card(0, 0, 4, 4, "Card", runtime=runtime)
        runtime.attach(viewer)
        create = runtime._command_queue.get_nowait()

        first = np.full((1, 1), 1, dtype=np.uint8)
        stale = np.full((1, 1), 2, dtype=np.uint8)
        latest = np.full((1, 1), 3, dtype=np.uint8)
        runtime.update(viewer.widget_id, first)
        runtime.update(viewer.widget_id, stale)
        runtime.update(viewer.widget_id, latest)

        first_command = runtime._command_queue.get_nowait()
        np.testing.assert_array_equal(first_command["payload"], first)
        with self.assertRaises(Empty):
            runtime._command_queue.get_nowait()

        runtime._event_queue.put(
            {
                "type": "update_done",
                "widget_id": viewer.widget_id,
                "attachment_id": create["attachment_id"],
            }
        )
        runtime.poll()

        latest_command = runtime._command_queue.get_nowait()
        np.testing.assert_array_equal(latest_command["payload"], latest)
        self.assertTrue(latest_command["ack"])
        with self.assertRaises(Empty):
            runtime._command_queue.get_nowait()

    def test_input_elements_are_accessible_through_retained_references(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as widget:
            prompt = Entry("Input here")
        prompt.value = "hello"
        self.assertEqual(prompt.value, "hello")
        self.assertEqual(widget.elements, (prompt,))
        self.assertFalse(hasattr(widget, "get"))
        self.assertFalse(hasattr(widget, "element"))

    def test_widget_controller_state_is_safe_for_concurrent_callbacks(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as form:
            first = Entry()
            second = Entry()

        def update(element, prefix):
            for index in range(100):
                element.set(f"{prefix}-{index}")

        threads = [
            Thread(target=update, args=(first, "a")),
            Thread(target=update, args=(second, "b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(form.values(), ("a-99", "b-99"))
        self.assertEqual(
            form._latest_payload, {first.name: "a-99", second.name: "b-99"}
        )

    def test_input_card_ui_options_remain_pickleable_after_locking(self):
        def callback(event: TriggerEvent):
            pass

        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as form:
            prompt = Entry("Input here")
            value = Slider(0, 10, 1)
            button = Btn("Run", callback)
        options = pickle.loads(pickle.dumps(form._ui_options))
        self.assertEqual(
            [e.name for e in options["elements"][:2]], [prompt.name, value.name]
        )
        self.assertEqual(options["elements"][2].id, button.id)
        self.assertIsNone(options["elements"][2].callback)
        self.assertIsNone(options["elements"][2]._control)

    def test_entry_rows_must_be_a_positive_integer(self):
        self.assertEqual(Entry("prompt", rows=3).rows, 3)
        with self.assertRaisesRegex(TypeError, "rows must be an int"):
            Entry("prompt", rows=2.5)
        with self.assertRaisesRegex(TypeError, "rows must be an int"):
            Entry("prompt", rows=True)
        with self.assertRaisesRegex(ValueError, "rows must be at least 1"):
            Entry("prompt", rows=0)

    def test_text_defaults_to_two_rows_and_validates_rows(self):
        self.assertEqual(Text().rows, 2)
        self.assertEqual(Text(rows=4).rows, 4)
        with self.assertRaisesRegex(TypeError, "rows must be an int"):
            Text(rows=2.5)
        with self.assertRaisesRegex(TypeError, "rows must be an int"):
            Text(rows=True)
        with self.assertRaisesRegex(ValueError, "rows must be at least 1"):
            Text(rows=0)

    def test_image_defaults_to_four_by_three_and_validates_aspect(self):
        self.assertEqual(Image().aspect, (4.0, 3.0))
        self.assertEqual(Image(aspect=(16, 9)).aspect, (16.0, 9.0))
        with self.assertRaisesRegex(TypeError, "two-item numeric sequence"):
            Image(aspect=(4,))
        with self.assertRaisesRegex(TypeError, "two-item numeric sequence"):
            Image(aspect=(4, "3"))
        with self.assertRaisesRegex(ValueError, "aspect values must be positive"):
            Image(aspect=(4, 0))

    def test_entry_with_multiple_rows_builds_a_textbox_at_requested_height(self):
        entries = []

        def make_entry(parent, **options):
            entry = FakeControl(parent, **options)
            entries.append(entry)
            return entry

        element = Entry("prompt", rows=3)
        ui = object.__new__(_EntryUI)

        with (
            patch(
                "customtkinter.CTkFrame",
                side_effect=FakeControl,
            ),
            patch(
                "customtkinter.CTkLabel",
                side_effect=FakeControl,
            ),
            patch(
                "customtkinter.CTkTextbox",
                side_effect=make_entry,
            ),
        ):
            ui.element = element
            ui.build(object())

        self.assertEqual(entries[0].options["height"], 84)
        self.assertEqual(ui._entry, entries[0])

    def test_input_card_values_returns_an_independent_ordered_snapshot(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as widget:
            first = Entry()
            second = Slider(0, 10, 1)
            Separator("Actions")
            Btn("Run")
        first.set("hello")
        second.set(4)
        values = widget.values()
        first.set("changed")
        self.assertEqual(values, ("hello", 4.0, None, None))
        self.assertEqual(widget.values(), ("changed", 4.0, None, None))

    def test_number_uses_slider_numeric_rules_and_default(self):
        number = Number(0, 10, 2, default=4)

        self.assertEqual(number.initial_value, 4.0)
        self.assertEqual(number.normalize(8), 8.0)
        with self.assertRaisesRegex(ValueError, "aligned to step"):
            number.normalize(3)

    def test_range_slider_normalizes_both_bounds(self):
        slider = RangeSlider(0, 10, 2, default=(2, 8))

        self.assertEqual(slider.initial_value, (2.0, 8.0))
        self.assertEqual(slider.normalize([4, 10]), (4.0, 10.0))
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            slider.normalize((8, 2))
        with self.assertRaisesRegex(ValueError, "aligned to step"):
            slider.normalize((3, 8))

    def test_range_slider_defaults_to_the_full_range_and_round_trips(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()):
            window = RangeSlider(-5, 5, 1)
        self.assertEqual(window.get(), (-5.0, 5.0))
        window.set((-2, 3))
        self.assertEqual(window.get(), (-2.0, 3.0))

    def test_range_slider_uses_one_track_for_both_handles(self):
        controls = []

        def make_control(parent, **options):
            control = FakeControl(parent, **options)
            controls.append(control)
            return control

        element = RangeSlider(0, 10, 1, default=(2, 8))
        ui = object.__new__(_RangeSliderUI)

        with (
            patch(
                "tkinter.DoubleVar",
                side_effect=lambda **options: FakeControl(None, **options),
            ),
            patch(
                "customtkinter.CTkFrame",
                side_effect=FakeControl,
            ),
            patch(
                "customtkinter.CTkLabel",
                side_effect=FakeControl,
            ),
            patch(
                "cardtable.widgets.elements._range_slider_control._RangeSliderControl",
                side_effect=make_control,
            ),
        ):
            ui.element = element
            ui.build(object())

        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0].options["value"], (2.0, 8.0))
        self.assertEqual(ui._controls, controls)

    def test_range_slider_does_not_override_customtkinter_draw_hook(self):
        self.assertNotIn("_draw", _RangeSliderControl.__dict__)

    def test_range_slider_background_skips_plain_tk_widgets(self):
        class PlainTkWidget:
            master = None

            def cget(self, _name):
                raise tk.TclError("unknown option -fg_color")

        color = _RangeSliderControl._background_color(PlainTkWidget())

        self.assertIsInstance(color, str)
        self.assertTrue(color)

    def test_text_background_resolves_transparent_parent(self):
        class Widget:
            def __init__(self, color, master=None):
                self.color = color
                self.master = master

            def cget(self, _name):
                return self.color

            def _apply_appearance_mode(self, color):
                return color

        solid_parent = Widget("#123456")
        transparent_child = Widget("transparent", solid_parent)

        self.assertEqual(_background_color(transparent_child), "#123456")

    def test_number_buttons_change_value_by_step_and_clamp_to_range(self):
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        number = Number(0, 10, 2)
        ui = object.__new__(_NumberUI)
        variable = Variable(8.0)
        value_label = FakeControl(object())
        emitted = []
        ui._variable = variable
        ui._number_entry = value_label
        ui._applying_update = False
        ui._emit = emitted.append

        ui._number_changed(number, 1)
        ui._number_changed(number, 1)
        ui._number_changed(number, -1)

        self.assertEqual(variable.get(), 8.0)
        self.assertEqual(value_label.get(), "8")
        self.assertEqual(emitted, [10.0, 10.0, 8.0])

    def test_number_direct_input_clamps_and_aligns_to_step(self):
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        number = Number(0, 10, 2)
        ui = object.__new__(_NumberUI)
        variable = Variable(4.0)
        entry = FakeControl(object())
        entry.insert(0, "99")
        emitted = []
        ui._variable = variable
        ui._number_entry = entry
        ui._applying_update = False
        ui._emit = emitted.append

        ui._commit_number(number)
        self.assertEqual(variable.get(), 10.0)
        self.assertEqual(entry.get(), "10")

        entry.delete(0, "end")
        entry.insert(0, "5.1")
        ui._commit_number(number)
        self.assertEqual(variable.get(), 6.0)
        self.assertEqual(entry.get(), "6")
        self.assertEqual(emitted, [10.0, 6.0])

    def test_input_card_disables_buttons_and_elements_through_one_api(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Card", runtime=runtime) as widget:
            prompt = Entry(label="Prompt")
            strength = Slider(0, 10, 1, label="Strength")
            run = Btn("Run")
        prompt.disable(label="Unavailable")
        self.assertEqual(
            widget._ui_options["element_states"][prompt.name],
            {"state": "disabled", "label": "Unavailable"},
        )
        widget.start()
        strength.disable(label="Locked")
        run.disable(label="Disabled")
        prompt.enable(label="Prompt")
        self.assertEqual(
            runtime.element_updates,
            [
                (widget.widget_id, strength.name, "disabled", "Locked"),
                (widget.widget_id, prompt.name, "normal", "Prompt"),
            ],
        )
        self.assertEqual(
            runtime.button_updates, [(widget.widget_id, run.id, "disabled", "Disabled")]
        )

    def test_input_element_ui_state_updates_control_and_label(self):
        ui = object.__new__(_EntryUI)
        control = FakeControl(object())
        label = FakeControl(object(), text="Prompt")
        ui._controls = [control]
        ui._label = label

        ui.update_state("disabled", "Unavailable")

        self.assertEqual(control.options["state"], "disabled")
        self.assertEqual(label.options["text"], "Unavailable")
        self.assertTrue(ui._disabled)

    def test_radio_places_its_label_left_of_vertical_options(self):
        frames = []
        labels = []
        radio_buttons = []

        def make_control(collection):
            def factory(parent, **options):
                control = FakeControl(parent, **options)
                collection.append(control)
                return control

            return factory

        ui = object.__new__(_RadioUI)
        variable = object()

        with (
            patch(
                "tkinter.StringVar",
                return_value=variable,
            ),
            patch(
                "customtkinter.CTkFrame",
                side_effect=make_control(frames),
            ),
            patch(
                "customtkinter.CTkLabel",
                side_effect=make_control(labels),
            ),
            patch(
                "customtkinter.CTkRadioButton",
                side_effect=make_control(radio_buttons),
            ),
        ):
            ui.element = Radio(["A", "B"], label="Mode")
            ui.build(object())

        self.assertEqual(labels[0].pack_options["side"], "left")
        self.assertEqual(labels[0].pack_options["anchor"], "n")
        self.assertEqual(frames[1].pack_options["side"], "left")
        self.assertTrue(frames[1].pack_options["expand"])
        self.assertEqual(
            [button.pack_options for button in radio_buttons],
            [{"fill": "x", "pady": 2}, {"fill": "x", "pady": 2}],
        )

    def test_slider_keeps_its_value_visible_in_a_narrow_card(self):
        frames = []
        labels = []
        sliders = []

        def make_control(collection):
            def factory(parent, **options):
                control = FakeControl(parent, **options)
                collection.append(control)
                return control

            return factory

        ui = object.__new__(_SliderUI)

        with (
            patch(
                "tkinter.DoubleVar",
                return_value=object(),
            ),
            patch(
                "customtkinter.CTkFrame",
                side_effect=make_control(frames),
            ),
            patch(
                "customtkinter.CTkLabel",
                side_effect=make_control(labels),
            ),
            patch(
                "customtkinter.CTkSlider",
                side_effect=make_control(sliders),
            ),
        ):
            ui.element = Slider(0, 100, 1)
            ui.build(object())

        header = frames[1]
        self.assertEqual(header.pack_options, {"fill": "x"})
        self.assertIs(labels[0].parent, header)
        self.assertEqual(labels[0].pack_options["side"], "left")
        self.assertIs(labels[1].parent, header)
        self.assertEqual(labels[1].pack_options["side"], "right")
        self.assertEqual(labels[1].options["width"], 36)
        self.assertEqual(sliders[0].pack_options, {"fill": "x", "pady": (4, 0)})

    def test_public_bases_and_builtin_elements_follow_the_new_structure(self):
        self.assertTrue(issubclass(InputElement, Element))
        self.assertEqual(Image.__module__, "cardtable.widgets.elements.image")
        self.assertEqual(Card.__module__, "cardtable.widgets.card.card")

    def test_custom_element_and_card_only_delegate_get_and_set(self):
        class Number(Element):
            @property
            def initial_value(self):
                return 0

            def normalize(self, value):
                if not isinstance(value, int):
                    raise TypeError("number must be an int")
                return value

        class NumberCard(Card):
            def __init__(self, **kwargs):
                self.number = Number()
                super().__init__(0, 0, 4, 4, "Number", **kwargs)
                self.add_element(self.number)

            def get(self):
                return self.number.get()

            def set(self, value):
                self.number.set(value)

            def _build_ui(self, parent, *, emit, **options):
                pass

        runtime = FakeRuntime()
        card = NumberCard(runtime=runtime)
        card.set(7)
        card.start()

        self.assertEqual(card.get(), 7)
        self.assertEqual(card.elements, (card.number,))
        self.assertEqual(runtime.updates[-1], (card.widget_id, {card.number.name: 7}))

    def test_generic_card_owns_input_image_and_text_elements(self):
        runtime = FakeRuntime()
        with Card(0, 0, 2, 2, "Card", runtime=runtime) as card:
            entry = Entry()
            cap = Image()
            result = Text()
        image = np.zeros((2, 3, 3), dtype=np.uint8)
        entry.set("test")
        cap.set(image)
        result.set("done")
        self.assertEqual(entry.get(), "test")
        np.testing.assert_array_equal(cap.get(), image)
        self.assertEqual(result.get(), "done")
        self.assertEqual(card.elements, (entry, cap, result))
        card.start()
        payload = runtime.updates[-1][1]
        self.assertEqual(payload[entry.name], "test")
        np.testing.assert_array_equal(payload[cap.name], image)
        self.assertEqual(payload[result.name], {"text": "done", "mode": "plain"})

    def test_custom_input_element_is_owned_directly_by_input_card(self):
        class CustomInput(InputElement[str, int]):
            @property
            def initial_value(self):
                return "initial"

            def normalize(self, value):
                return str(value)

            def build_ui(self, parent, emit):
                pass

            def update_ui(self, value):
                pass

        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            element = CustomInput()
        element.set(42)
        self.assertEqual(card.elements, (element,))
        self.assertEqual(element.get(), "42")

    def test_file_drop_keeps_absolute_path_and_displays_filename(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, "sample.image.png")
            path.touch()
            with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()):
                element = FileDrop(text="Drop an image", label="Source")
            element.value = path
            self.assertEqual(element.value, str(path.resolve()))
            self.assertEqual(
                _file_drop_text(element, element.value), "sample.image.png"
            )
            self.assertEqual(_file_drop_text(element, None), "Drop an image")

    def test_file_drop_validates_text_and_optional_label(self):
        self.assertIsNone(FileDrop().label)
        self.assertEqual(FileDrop("Drop an image").text, "Drop an image")
        with self.assertRaisesRegex(TypeError, "text must be a string"):
            FileDrop(text=None)
        with self.assertRaisesRegex(TypeError, "label must be a string or None"):
            FileDrop(label=42)

    def test_file_drop_without_label_does_not_reserve_label_space(self):
        frames = []
        labels = []

        def make_control(collection):
            def factory(parent, **options):
                control = FakeControl(parent, **options)
                collection.append(control)
                return control

            return factory

        ui = object.__new__(_FileDropUI)

        with (
            patch(
                "customtkinter.CTkFrame",
                side_effect=make_control(frames),
            ),
            patch(
                "customtkinter.CTkLabel",
                side_effect=make_control(labels),
            ),
            patch(
                "customtkinter.CTkFont",
                return_value=object(),
            ),
            patch("tkinterdnd2.TkinterDnD._require"),
        ):
            element = FileDrop()
            ui.element = element
            ui.build(FakeControl(None))

        self.assertEqual(len(labels), 4)
        self.assertIsNone(labels[0].pack_options)
        self.assertIsNone(labels[3].pack_options)
        self.assertIs(labels[1].parent, frames[1])
        self.assertIs(labels[2].parent, frames[1])
        self.assertEqual(
            labels[2].options["text"], "Drop a file or click here to select"
        )
        self.assertEqual(frames[1].pack_options, {"fill": "x", "expand": True})

        # A later label update adds a heading above the drop area.
        labels[2].master = frames[1]
        ui.update_state("normal", "Source")
        self.assertEqual(labels[0].pack_options["before"], frames[1])
        self.assertEqual(labels[0].options["text"], "Source")
        self.assertEqual(
            labels[2].options["text"], "Drop a file or click here to select"
        )
        self.assertEqual(ui._file_drop_prompt, "Drop a file or click here to select")

    def test_file_drop_places_label_above_drop_area(self):
        ui = object.__new__(_FileDropUI)
        element = FileDrop(text="Drop an image", label="Source")
        with (
            patch("customtkinter.CTkFrame", FakeControl),
            patch("customtkinter.CTkLabel", FakeControl),
            patch(
                "customtkinter.CTkFont",
                return_value=object(),
            ),
            patch("tkinterdnd2.TkinterDnD._require"),
        ):
            ui.element = element
            ui.build(FakeControl(None))

        heading = ui._label
        prompt = ui._file_drop_label
        self.assertEqual(heading.options["text"], "Source")
        self.assertEqual(heading.pack_options, {"fill": "x", "pady": (0, 4)})
        self.assertIs(prompt.parent.parent, heading.parent)
        self.assertEqual(prompt.options["text"], "Drop an image")

        ui._file_drop_value = "/tmp/selected.png"
        prompt.configure(text="selected.png")
        ui.update_state("disabled", "Unavailable")
        self.assertEqual(heading.options["text"], "Unavailable")
        self.assertEqual(prompt.options["text"], "selected.png")
        self.assertEqual(ui._file_drop_prompt, "Drop an image")

    def test_disabled_file_drop_uses_gray_text_and_restores_its_color(self):
        ui = object.__new__(_FileDropUI)
        element = FileDrop()
        drop_label = FakeControl(object(), text_color="theme-color")
        ui._controls = []
        ui._drop_targets = (drop_label,)
        ui._label = drop_label
        ui._file_drop_label = drop_label
        ui._file_drop_prompt = element.text
        ui._file_drop_text_color = "theme-color"

        ui.update_state("disabled", None)
        self.assertEqual(drop_label.options["text_color"], ("gray60", "gray45"))

        ui.update_state("normal", None)
        self.assertEqual(drop_label.options["text_color"], "theme-color")

    def test_file_drop_rejects_directories_and_missing_files(self):
        element = FileDrop()
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "existing file"):
                element.normalize(directory)
            with self.assertRaisesRegex(ValueError, "existing file"):
                element.normalize(Path(directory, "missing.txt"))

    def test_long_file_drop_name_is_ellipsized_to_available_width(self):
        measure = len

        self.assertEqual(_ellipsize("long-filename.png", 12, measure), "long-file...")
        self.assertEqual(_ellipsize("short.png", 12, measure), "short.png")

    def test_button_trigger_can_enable_and_disable_its_button(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Card", runtime=runtime) as widget:
            button = Button("Save")
        widget.start()
        button.disable(label="Saving...")
        self.assertEqual(button.label, "Saving...")
        button.enable(label="Save")
        self.assertEqual(
            runtime.button_updates,
            [
                (widget.widget_id, button.id, "disabled", "Saving..."),
                (widget.widget_id, button.id, "normal", "Save"),
            ],
        )
        self.assertFalse(hasattr(widget, "button"))

    def test_input_view_button_exposes_and_fires_a_trigger(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as view:
            button = Btn("Press")
        view._receive_input(_BtnPressed(button.id))
        self.assertIsInstance(button._control, ButtonControl)
        self.assertTrue(button._control.message_event.is_set())
        self.assertEqual(
            button._control.message_event.get_message().data,
            {"button_id": button.id},
        )

    def test_input_card_accepts_an_inline_button_between_elements(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as view:
            Entry()
            button = Btn("Capture")
            Separator("Options")
            Entry()
        self.assertEqual(
            [e.id for e in view._ui_options["elements"] if isinstance(e, Btn)],
            [button.id],
        )
        view._receive_input(_BtnPressed(button.id))
        self.assertTrue(button._control.message_event.is_set())

    def test_input_view_disable_updates_button_state_and_label(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Card", runtime=runtime) as view:
            with Row():
                cap = Btn("Capture")
                show = Btn("Show")
        cap.disable(label="Disabled btn")
        self.assertEqual((cap.state, cap.label), ("disabled", "Disabled btn"))
        self.assertEqual(runtime.button_updates, [])
        self.assertEqual(view._ui_options["elements"][0].state, "disabled")
        view.start()
        show.disable()
        self.assertEqual(
            runtime.button_updates, [(view.widget_id, show.id, "disabled", "Show")]
        )

    def test_button_configure_validates_state_and_arguments(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()):
            cap = Btn("Capture")
        with self.assertRaisesRegex(TypeError, "label"):
            cap.disable(label=1)
        with self.assertRaisesRegex(TypeError, "state or label"):
            cap.configure()
        with self.assertRaisesRegex(ValueError, "normal.*disabled"):
            cap.configure(state="inactive")
        with self.assertRaisesRegex(RuntimeError, "not attached"):
            Btn("Unattached").disable()

    def test_button_is_an_element_without_a_settable_value(self):
        button = Btn("Run")
        self.assertIsInstance(button, Element)
        self.assertIsNone(button.get())
        for value in (None, True, "Run"):
            with self.assertRaisesRegex(TypeError, "configure"):
                button.set(value)
        with self.assertRaises(TypeError):
            button.value = "Changed"
        self.assertIsNone(button.value)

    def test_get_elements_includes_buttons_in_declaration_order(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            with Row():
                entry = Entry()
                button = Btn("Inline")
            border = Separator()
        self.assertEqual(card.get_elements(), [entry, button, border])
        self.assertEqual(card.values(), ("", None, None))
        elements = card.get_elements()
        self.assertIs(elements[1], button)
        self.assertIs(elements[-1], border)
        elements.clear()
        self.assertEqual(len(card.get_elements()), 3)

    def test_separator_is_an_element_without_a_settable_value(self):
        border = Separator("Options")
        self.assertIsInstance(border, Element)
        self.assertIsNone(border.get())
        for value in (None, True, "Changed"):
            with self.assertRaisesRegex(TypeError, "does not accept values"):
                border.set(value)
        with self.assertRaises(TypeError):
            border.value = "Changed"
        border.label = "Changed"
        border.reset()
        self.assertEqual(border.label, "Options")
        self.assertIsNone(border.get())

    def test_separator_reset_restores_label_through_ui_transport(self):
        for initial_label in (None, "", "Options"):
            with self.subTest(label=initial_label):
                runtime = FakeRuntime()
                with Card(0, 0, 4, 4, "Card", runtime=runtime) as card:
                    border = Separator(initial_label)
                self.assertEqual(card.get_elements(), [border])
                self.assertEqual(card.values(), (None,))
                ui_border = pickle.loads(pickle.dumps(card._ui_options))["elements"][0]
                with (
                    patch("customtkinter.CTkFrame"),
                    patch("customtkinter.CTkLabel") as label_class,
                ):
                    ui_border.build_ui(Mock(), lambda event: None)
                control = label_class.return_value
                for started in (False, True):
                    if started:
                        card.start()
                    border.label = "Changed"
                    border.reset()
                    self.assertIsNone(border.get())
                    self.assertEqual(border.label, initial_label)
                    payload = card._latest_payload
                    if started:
                        self.assertEqual(runtime.updates[-1][1], payload)
                    ui = object.__new__(Card)
                    ui._ui_elements = {border.name: ui_border}
                    ui._update_ui(payload)
                    control.configure.assert_called_with(text=initial_label or "")
                    if initial_label is None:
                        control.pack_forget.assert_called()
                    else:
                        control.pack.assert_called_with(fill="x", pady=(4, 0))

    def test_button_reset_restores_initial_state_before_and_after_start(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Card", runtime=runtime) as card:
            disabled = Btn("Disabled", state="disabled")
            inline = Btn("Inline")
            text = Text()
        for started in (False, True):
            if started:
                card.start()
            for button in (disabled, inline):
                button.configure(state="normal", label="Changed")
                button.reset()
                self.assertEqual(button.label, button._initial_label)
                self.assertEqual(button.state, button._initial_state)
                self.assertIsNone(button.get())
            options = card._ui_options
            self.assertEqual(options["elements"][0].label, "Disabled")
            self.assertEqual(options["elements"][0].state, "disabled")
            self.assertEqual(options["elements"][1].label, "Inline")
            pickle.dumps(options)
        self.assertEqual(
            runtime.button_updates[-1],
            (card.widget_id, inline.id, "normal", "Inline"),
        )
        text.set("Updated")
        self.assertEqual(
            runtime.updates[-1][1], {text.name: text.display_value("Updated")}
        )

    def test_unattached_button_reset_restores_initial_state(self):
        button = Btn("Initial", state="disabled")
        button.state = "normal"
        button.label = "Changed"
        button.reset()
        self.assertEqual((button.state, button.label), ("disabled", "Initial"))

    def test_btn_accepts_an_initial_state(self):
        self.assertEqual(Btn(label="Run").label, "Run")
        self.assertEqual(Btn("run", state="disabled").state, "disabled")
        with self.assertRaisesRegex(ValueError, "normal.*disabled"):
            Btn("run", state="inactive")

    def test_btn_validates_callback(self):
        def callback(event: TriggerEvent):
            pass

        self.assertIs(Btn("run", callback=callback).callback, callback)
        with self.assertRaisesRegex(TypeError, "callback"):
            Btn("run", callback="not callable")

    def test_btn_has_five_material_color_palettes(self):
        expected = {
            "blue": ("#1E88E5", "#1976D2", "#90CAF9"),
            "gray": ("#546E7A", "#455A64", "#B0BEC5"),
            "orange": ("#FB8C00", "#F57C00", "#FFCC80"),
            "red": ("#E53935", "#D32F2F", "#EF9A9A"),
            "green": ("#43A047", "#388E3C", "#A5D6A7"),
        }
        self.assertEqual(Btn("run").color, "blue")
        for color, palette in expected.items():
            button = Btn("run", color=color)
            self.assertEqual(
                (button.active_color, button.hover_color, button.disabled_color),
                palette,
            )

        with self.assertRaisesRegex(ValueError, "blue.*gray.*orange.*red.*green"):
            Btn("run", color="purple")

    def test_identical_button_labels_do_not_collide(self):
        with Card(0, 0, 4, 4, "Card", runtime=FakeRuntime()) as card:
            with Row():
                first = Btn("Run")
                second = Btn("Run")
            Btn("get")
        self.assertNotEqual(first.id, second.id)
        first.disable()
        self.assertEqual(first.state, "disabled")
        self.assertEqual(second.state, "normal")
        self.assertEqual(len(card._button_triggers), 3)

    def test_visibility_can_be_changed_before_and_after_start(self):
        runtime = FakeRuntime()
        viewer = Card(0, 0, 4, 4, "Card", runtime=runtime)

        viewer.show()
        self.assertTrue(viewer._ui_options["show_on_create"])
        viewer.start()
        viewer.hide()

        self.assertEqual(runtime.visibility, [(viewer.widget_id, False)])

    def test_widget_forwards_window_close_request(self):
        viewer = Card(0, 0, 4, 4, "Card", runtime=FakeRuntime())
        requested = []
        viewer._set_close_handler(lambda: requested.append(True))

        viewer._receive_close_requested()

        self.assertEqual(requested, [True])

    def test_card_requires_geometry_and_title_arguments(self):
        runtime = FakeRuntime()
        card = Card(2, 3, 4, 5, "Positioned", runtime=runtime)
        self.assertEqual(card.geometry, (2, 3, 4, 5))
        self.assertEqual(card._ui_options["geometry"], (2, 3, 4, 5))
        self.assertEqual(card.name, "Positioned")
        title_parameter = inspect.signature(Card).parameters["title"]
        self.assertEqual(title_parameter.kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        self.assertIs(title_parameter.default, inspect.Parameter.empty)
        self.assertNotIn("name", inspect.signature(Card).parameters)
        for args, kwargs in (
            ((), {"x": 2, "y": 3, "w": 4, "h": 5, "title": "Positioned"}),
            ((2, 3, 4, 5), {"title": "Positioned"}),
        ):
            with self.subTest(args=args, kwargs=kwargs):
                card = Card(*args, runtime=runtime, **kwargs)
                self.assertEqual(card.geometry, (2, 3, 4, 5))
                self.assertEqual(card.name, "Positioned")
        with self.assertRaisesRegex(TypeError, "title"):
            Card(0, 0, 4, 4, runtime=runtime)

        for args, kwargs in (
            ((), {}),
            ((0,), {}),
            ((0, 0), {}),
            ((0, 0, 4), {}),
            (((0, 0, 4, 4),), {}),
            ((), {"geometry": (0, 0, 4, 4)}),
            ((), {"x": 0, "y": 0, "w": 4, "h": 4}),
            ((0, 0, 4, 4, "Title", "Extra"), {}),
        ):
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(TypeError):
                    Card(*args, runtime=runtime, **kwargs)

    def test_geometry_is_normalized_and_validated(self):
        viewer = Card(2, 3, 8, 6, "Card", runtime=FakeRuntime())

        self.assertEqual(viewer.geometry, (2, 3, 8, 6))
        self.assertEqual(viewer.geometry_unit, "grid")
        self.assertEqual(viewer._ui_options["geometry"], (2, 3, 8, 6))

        with self.assertRaisesRegex(ValueError, "must be positive"):
            Card(0, 0, 0, 4, "Card", runtime=FakeRuntime())
        with self.assertRaisesRegex(ValueError, "non-negative"):
            Card(-1, 0, 4, 4, "Card", runtime=FakeRuntime())
        with self.assertRaisesRegex(ValueError, "fit within 12 columns"):
            Card(8, 0, 5, 4, "Card", runtime=FakeRuntime())

    def test_pixel_geometry_remains_available_as_an_option(self):
        with (
            patch.object(Deck, "_settings", _DeckSettings(geometry_unit="px")),
            patch.object(Deck, "_frozen", False),
        ):
            viewer = Card(10, 20, 800, 600, "Card", runtime=FakeRuntime())

        self.assertEqual(viewer.geometry, (10, 20, 800, 600))
        self.assertEqual(viewer.geometry_unit, "px")
        self.assertNotIn("geometry_unit", viewer._ui_options)

    def test_geometry_tracks_latest_ui_state(self):
        runtime = FakeRuntime()
        viewer = Card(1, 2, 8, 6, "Card", runtime=runtime)

        viewer.start()
        viewer._receive_geometry((2, 3, 7, 5))

        self.assertEqual(viewer.geometry, (2, 3, 7, 5))
        self.assertEqual(runtime.polled, 1)

    def test_default_grid_converts_to_responsive_pixels(self):
        geometry = (2, 1, 6, 4)

        self.assertEqual(grid_to_pixels(geometry, 1200), (200, 75, 600, 300))
        self.assertEqual(grid_to_pixels(geometry, 600), (100, 38, 300, 150))

    def test_grid_drag_is_clamped_and_snapped_to_cells(self):
        geometry = (2, 1, 6, 4)

        self.assertEqual(
            move_grid_geometry(
                geometry,
                149,
                40,
                cell_width=100,
                cell_height=75,
                grid_columns=12,
            ),
            (3, 2, 6, 4),
        )
        self.assertEqual(
            move_grid_geometry(
                geometry,
                1000,
                -1000,
                cell_width=100,
                cell_height=75,
                grid_columns=12,
            ),
            (6, 0, 6, 4),
        )

    def test_grid_resize_is_clamped_and_snapped_to_cells(self):
        geometry = (2, 1, 6, 4)

        self.assertEqual(
            resize_grid_geometry(
                geometry,
                149,
                -115,
                cell_width=100,
                cell_height=75,
                grid_columns=12,
            ),
            (2, 1, 8, 2),
        )
        self.assertEqual(
            resize_grid_geometry(
                geometry,
                1000,
                -1000,
                cell_width=100,
                cell_height=75,
                grid_columns=12,
            ),
            (2, 1, 10, 1),
        )

        self.assertEqual(
            resize_grid_geometry(
                geometry,
                -1000,
                0,
                cell_width=100,
                cell_height=75,
                grid_columns=12,
                min_width=2,
            ),
            (2, 1, 2, 4),
        )

    def test_grid_resize_reacts_at_one_tenth_of_a_cell_in_both_directions(self):
        geometry = (2, 1, 6, 4)
        for dx, dy, expected in (
            (9, 9, geometry),
            (-9, -9, geometry),
            (10, 10, (2, 1, 7, 5)),
            (-10, -10, (2, 1, 5, 3)),
            (109, -109, (2, 1, 7, 3)),
            (110, -110, (2, 1, 8, 2)),
            (0, 0, geometry),
        ):
            with self.subTest(dx=dx, dy=dy):
                self.assertEqual(
                    resize_grid_geometry(
                        geometry,
                        dx,
                        dy,
                        cell_width=100,
                        cell_height=100,
                        grid_columns=12,
                    ),
                    expected,
                )

    def test_missing_geometry_is_stacked_below_existing_panels(self):
        modules = {
            "first": {"geometry": (0, 0, 800, 600)},
            "second": {"geometry": (800, 0, 400, 300)},
        }

        self.assertEqual(_next_geometry(modules), (0, 608, 480, 320))

    def test_missing_grid_geometry_is_stacked_by_grid_rows(self):
        modules = {
            "first": {"geometry": (0, 0, 8, 6), "geometry_unit": "grid"},
            "second": {"geometry": (8, 0, 4, 2), "geometry_unit": "grid"},
        }

        self.assertEqual(_next_geometry(modules, "grid"), (0, 6, 4, 4))

    def test_panel_geometry_can_be_moved_without_becoming_negative(self):
        geometry = (20, 30, 400, 300)

        self.assertEqual(_move_geometry(geometry, 15, 25), (35, 55, 400, 300))
        self.assertEqual(_move_geometry(geometry, -100, -100), (0, 0, 400, 300))

    def test_grid_title_drag_moves_without_resize_only_arguments(self):
        module = {}
        drag = {
            "mode": "move",
            "geometry": (2, 1, 4, 3),
            "cell_size": (100, 75),
        }

        self.assertEqual(_drag_geometry(module, drag, 110, 80), (3, 2, 4, 3))

    def test_panel_geometry_can_be_resized_from_bottom_right(self):
        geometry = (100, 100, 400, 300)

        self.assertEqual(_resize_geometry(geometry, 20, 30), (100, 100, 420, 330))

    def test_panel_resize_honors_bounds_and_minimum_size(self):
        geometry = (10, 10, 400, 300)

        self.assertEqual(_resize_geometry(geometry, -1000, -1000), (10, 10, 120, 80))


if __name__ == "__main__":
    unittest.main()
