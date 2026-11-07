"""Label state, styling, and controller/UI transport contracts."""

import pickle
import unittest
from unittest.mock import Mock, patch

from test_widgets import FakeRuntime

from cardtable import BoxedLabel, Card, Element, Label
from cardtable.core.closure import Closure


class LabelTest(unittest.TestCase):
    def setUp(self):
        base = Mock()
        base.cget.return_value = 12
        base.actual.side_effect = {"family": "Arial", "weight": "normal"}.__getitem__
        base._tk.call.return_value = 1.0
        for mock in (
            patch("tkinter.font.nametofont", return_value=base),
            patch("customtkinter.CTkFont"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def tearDown(self):
        Closure().close_all()

    def test_partial_updates_and_reset_preserve_initial_configuration(self):
        for cls in (Label, BoxedLabel):
            with self.subTest(element=cls.__name__):
                label = cls("Ready", text_color="white", bg_color="blue")
                self.assertIsInstance(label, Element)
                label.set("Done", "black", "green")
                label.set(bg_color=("orange", "brown"))
                label.set(label="")
                self.assertEqual(label.get(), "")
                self.assertEqual(label.text_color, "black")
                self.assertEqual(label.bg_color, ("orange", "brown"))
                label.value = "Again"
                self.assertEqual(label.get(), "Again")
                self.assertEqual(label.text_color, "black")
                label.reset()
                self.assertEqual(label.get(), "Ready")
                self.assertEqual((label.text_color, label.bg_color), ("white", "blue"))

    def test_card_sends_colors_even_when_only_colors_change(self):
        with Card(0, 0, 4, 3, "Status", runtime=FakeRuntime()) as card:
            plain = Label("Status")
            badge = BoxedLabel("Ready")
        plain.set(text_color=("black", "white"), bg_color="yellow")
        badge.set("Done", "white", "green")
        self.assertEqual(card.values(), ("Status", "Done"))
        payload = pickle.loads(pickle.dumps(card._latest_payload))
        self.assertEqual(
            payload[plain.name],
            {
                "label": "Status",
                "text_color": ("black", "white"),
                "bg_color": "yellow",
                "font": None,
            },
        )
        ui = object.__new__(Card)
        ui._applying_update = False
        ui._ui_elements = {plain.name: plain, badge.name: badge}
        emit = Mock()
        with (
            patch("customtkinter.CTkLabel", side_effect=lambda *a, **kw: Mock()),
            patch("customtkinter.CTkFont"),
        ):
            for element in (plain, badge):
                ui._build_element_ui(Mock(), element, emit)
            ui._update_ui(payload)
            badge._ui.configure.assert_called_with(
                text="Done",
                text_color="white",
                fg_color="green",
                font=badge._ui_font(None),
            )
            emit.assert_not_called()

    def test_build_uses_fill_color_and_boxed_font_is_always_bold(self):
        with patch("customtkinter.CTkLabel") as control:
            label = Label("Text", "e", "red", "blue", ("Arial", 16), 8)
            label.build_ui(Mock(), Mock())
            options = control.call_args.kwargs
            self.assertEqual(options["anchor"], "e")
            self.assertEqual(options["fg_color"], "blue")
            self.assertEqual(options["corner_radius"], 8)
            self.assertEqual(options["font"], ("Arial", 16))
            for font in (("Arial", 16), ("Arial", 16, "normal italic")):
                badge = BoxedLabel("Badge", font=font)
                self.assertIsInstance(badge, Label)
                badge.build_ui(Mock(), Mock())
                options = control.call_args.kwargs
                self.assertEqual(options["anchor"], "center")
                self.assertGreater(options["corner_radius"], 0)
                self.assertIn("bold", options["font"][2].split())
                self.assertNotIn("normal", options["font"][2].split())
            with patch("customtkinter.CTkFont") as font_class:
                BoxedLabel("Default").build_ui(Mock(), Mock())
                font_class.assert_called_once_with(
                    family="Arial", size=12, weight="bold"
                )

    def test_reset_restores_theme_text_color_and_pickle_excludes_ui(self):
        label = Label("Initial")
        with patch("customtkinter.CTkLabel"):
            label.build_ui(Mock(), Mock())
        label.set("Changed", "red", "blue")
        restored = pickle.loads(pickle.dumps(label))
        self.assertFalse(hasattr(restored, "_ui"))
        self.assertEqual(
            restored.display_value(restored.get()), label.display_value(label.get())
        )
        label.reset()
        with patch("customtkinter.CTkFont") as font_class:
            label.update_ui(label.display_value(label.get()))
            font_class.assert_called_once_with(family="Arial", size=12, weight="normal")
        import customtkinter as ctk

        label._ui.configure.assert_called_with(
            text="Initial",
            text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"],
            fg_color="transparent",
            font=font_class.return_value,
        )

    def test_font_update_crosses_process_boundary_and_reset_restores_font(self):
        for cls in (Label, BoxedLabel):
            with self.subTest(element=cls.__name__):
                label = cls("Ready", font=("Arial", 12))
                ui = pickle.loads(pickle.dumps(label))
                with patch("customtkinter.CTkLabel"):
                    ui.build_ui(Mock(), Mock())
                label.set(font=("Arial", 20, "normal italic"))
                self.assertEqual(label.get(), "Ready")
                payload = pickle.loads(pickle.dumps(label.display_value(label.get())))
                ui.update_ui(payload)
                expected = "bold italic" if cls is BoxedLabel else "normal italic"
                self.assertEqual(
                    ui._ui.configure.call_args.kwargs["font"], ("Arial", 20, expected)
                )
                label.set("Done")
                self.assertEqual(label.font, ("Arial", 20, "normal italic"))
                label.reset()
                ui.update_ui(label.display_value(label.get()))
                expected_font = (
                    ("Arial", 12, "bold") if cls is BoxedLabel else ("Arial", 12)
                )
                self.assertEqual(
                    ui._ui.configure.call_args.kwargs["font"], expected_font
                )

    def test_invalid_updates_do_not_partially_change_display(self):
        label = Label("Ready", text_color="black")
        for options in (
            {"label": 42},
            {"label": "Changed", "text_color": 42},
            {"text_color": "red", "bg_color": ("white", 42)},
            {"text_color": "transparent"},
            {"label": "Changed", "text_color": "red", "font": "Arial"},
        ):
            with self.subTest(options=options):
                with self.assertRaises((TypeError, ValueError)):
                    label.set(**options)
                self.assertEqual(label.get(), "Ready")
                self.assertEqual(label.text_color, "black")
        with self.assertRaises(TypeError):
            Label()
        for options in ({"anchor": "left"}, {"corner_radius": -1}, {"font": "Arial"}):
            with self.assertRaises((TypeError, ValueError)):
                Label("Text", **options)


if __name__ == "__main__":
    unittest.main()
