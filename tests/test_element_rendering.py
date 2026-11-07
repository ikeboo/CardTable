"""Element rendering contracts across the controller/UI boundary."""

import pickle
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from cardtable import (
    Card,
    CheckBox,
    ComboBox,
    Element,
    Entry,
    FileDialog,
    FileDrop,
    Number,
    Radio,
    RangeSlider,
    Slider,
    Switch,
)


class Variable:
    def __init__(self, *, value, **kwargs):
        self.value = value
        self.on_set = lambda: None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.on_set()


def control(*args, **kwargs):
    widget = Mock()
    widget.winfo_width.return_value = 128
    widget._font.measure.side_effect = len
    widget.cget.return_value = "theme-color"
    return widget


class ElementRenderingTest(unittest.TestCase):
    def setUp(self):
        font = patch(
            "cardtable.widgets.elements._fonts.ctk_font", return_value=("Arial", 12)
        )
        font.start()
        self.addCleanup(font.stop)

    def make_ui(self, element, emit):
        ui = object.__new__(Card)
        ui._applying_update = False
        ui._ui_elements = {element.name: element}
        ui._build_element_ui(Mock(), element, emit)
        return ui

    def test_entry_same_value_does_not_replace_text_or_selection(self):
        for rows in (1, 3):
            with self.subTest(rows=rows):
                element = Entry(rows=rows)
                renderer = element._create_renderer(Mock())
                renderer._entry = Mock()
                renderer._entry.get.return_value = "typing"
                element._ui = renderer
                element.update_ui("typing")
                renderer._entry.delete.assert_not_called()
                renderer._entry.insert.assert_not_called()
                element.update_ui("changed")
                renderer._entry.delete.assert_called_once()
                renderer._entry.insert.assert_called_once_with(
                    0 if rows == 1 else "1.0", "changed"
                )

    def test_all_builtin_inputs_own_build_value_and_state_updates(self):
        cases = [
            (Radio(["a", "b"]), "b"),
            (ComboBox(["a", "b"]), "b"),
            (Slider(0, 10, 1), 3),
            (RangeSlider(0, 10, 1), (2, 8)),
            (Number(0, 10, 1), 3),
            (Entry(), "hello"),
            (Entry(rows=3), "hello\nworld"),
            (FileDialog(), None),
            (FileDialog(multiple=True), ()),
            (FileDrop(), None),
            (Switch(), True),
            (CheckBox(), True),
        ]
        with ExitStack() as stack:
            for name in (
                "CTkFrame",
                "CTkLabel",
                "CTkRadioButton",
                "CTkComboBox",
                "CTkSlider",
                "CTkEntry",
                "CTkButton",
                "CTkTextbox",
                "CTkSwitch",
                "CTkCheckBox",
                "CTkFont",
            ):
                stack.enter_context(patch(f"customtkinter.{name}", side_effect=control))
            for name in ("StringVar", "DoubleVar", "BooleanVar"):
                stack.enter_context(patch(f"tkinter.{name}", side_effect=Variable))
            stack.enter_context(
                patch(
                    "cardtable.widgets.elements._range_slider_control._RangeSliderControl",
                    side_effect=control,
                )
            )
            for element, value in cases:
                with self.subTest(element=type(element).__name__, value=value):
                    emitted = Mock()
                    ui = self.make_ui(element, emitted)
                    ui._update_ui({element.name: value})
                    ui._update_element(element.name, state="disabled", label="Locked")
                    self.assertTrue(element._ui._disabled)
                    element._ui._label.configure.assert_called_with(text="Locked")
                    ui._update_element(element.name, state="normal", label=None)
                    self.assertFalse(element._ui._disabled)
                    for widget in element._ui._controls:
                        state = (
                            "readonly" if isinstance(element, ComboBox) else "normal"
                        )
                        widget.configure.assert_called_with(state=state)
                    emitted.assert_not_called()
                    # Built controls contain unpickleable callbacks; none may
                    # leak into a serialized element or its shallow UI copy.
                    restored = pickle.loads(pickle.dumps(element))
                    self.assertFalse(hasattr(restored, "_ui"))
                    self.assertEqual(restored.initial_value, element.initial_value)

    def test_builtin_subclass_hooks_are_used_without_card_type_dispatch(self):
        class CustomRadio(Radio):
            def build_ui(self, parent, emit):
                self.emit = emit
                self.rendered = []

            def update_ui(self, value):
                self.rendered.append(value)
                self.emit(value)

            def update_state_ui(self, state, label):
                self.state = state, label

        element = CustomRadio(["a", "b"])
        emitted = Mock()
        ui = self.make_ui(element, emitted)
        ui._update_ui({element.name: "b"})
        self.assertEqual(element.rendered, ["b"])
        emitted.assert_not_called()
        element.emit("a")
        emitted.assert_called_once_with({element.name: "a"})
        ui._update_element(element.name, state="disabled", label="Locked")
        self.assertEqual(element.state, ("disabled", "Locked"))

    def test_standalone_input_updates_do_not_emit_variable_callbacks(self):
        element = Radio(["a", "b"])
        emitted = Mock()
        with (
            patch("customtkinter.CTkFrame", side_effect=control),
            patch("customtkinter.CTkLabel", side_effect=control),
            patch("customtkinter.CTkRadioButton", side_effect=control),
            patch("tkinter.StringVar", side_effect=Variable),
        ):
            element.build_ui(Mock(), emitted)
        element._ui._variable.on_set = lambda: element._ui._emit_variable(element)
        element.update_ui("b")
        self.assertEqual(element._ui._variable.get(), "b")
        emitted.assert_not_called()
        element._ui._emit_variable(element)
        emitted.assert_called_once_with("b")
        with self.assertRaises(ValueError):
            element.update_ui("invalid")
        self.assertFalse(element._ui._applying_update)

    def test_custom_element_owns_transport_encoding(self):
        class Counter(Element):
            @property
            def initial_value(self):
                return 0

            def normalize(self, value):
                return int(value)

            def display_value(self, value):
                return {"count": value}

            def build_ui(self, parent, emit):
                self.rendered = None

            def update_ui(self, value):
                self.rendered = value

        with Card(0, 0, 4, 4, "Counter", runtime=Mock()) as card:
            element = Counter()
        element.set(42)
        self.assertEqual(card._latest_payload, {element.name: {"count": 42}})
        ui = self.make_ui(element, Mock())
        ui._update_ui(card._latest_payload)
        self.assertEqual(element.rendered, {"count": 42})
