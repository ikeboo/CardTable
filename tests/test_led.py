import pickle
import tkinter as tk
import unittest
from threading import Event, RLock
from unittest.mock import MagicMock, patch

from cardtable.widgets.card.card import Card

from cardtable import LED, InputElement
from cardtable.widgets.elements.led import led_image


class LEDTest(unittest.TestCase):
    def setUp(self):
        font = patch(
            "cardtable.widgets.elements._fonts.ctk_font", return_value=("Arial", 12)
        )
        font.start()
        self.addCleanup(font.stop)

    def test_interactive_controls_clicks_without_changing_appearance(self):
        appearances = []
        for options in ({}, {"interactive": False}, {"interactive": True}):
            with self.subTest(options=options):
                led = LED("red", **options)
                interactive = options.get("interactive", False)
                self.assertIs(led.interactive, interactive)
                emit = MagicMock()
                with (
                    patch("customtkinter.CTkFrame"),
                    patch("customtkinter.CTkLabel") as label_class,
                    patch("customtkinter.CTkImage") as image_class,
                ):
                    label, indicator = MagicMock(), MagicMock()
                    label_class.side_effect = [label, indicator]
                    image_class.side_effect = ["off-image", "on-image"]
                    led.build_ui(MagicMock(), emit)
                appearances.append(
                    [call.kwargs for call in label_class.call_args_list]
                )
                toggle = indicator.bind.call_args.args[1]
                toggle(None)
                self.assertIs(led._ui_value, interactive)
                if interactive:
                    emit.assert_called_once_with(True)
                else:
                    emit.assert_not_called()
                    indicator.configure.assert_not_called()

                led.set(True)
                self.assertIs(led.value, True)
                led.update_ui(led.display_value(led.value))
                self.assertIs(led._ui_value, True)
                led.set(False)
                self.assertIs(led.value, False)
                led.update_ui(led.display_value(led.value))
                self.assertIs(led._ui_value, False)
                self.assertIs(pickle.loads(pickle.dumps(led)).interactive, interactive)
        self.assertEqual(appearances[0], appearances[1])
        self.assertEqual(appearances[0], appearances[2])

    def test_interactive_requires_a_bool(self):
        for value in (0, 1, "true", None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                LED("red", interactive=value)

    def test_set_color_persists_across_updates_flash_reset_and_serialization(self):
        led = LED("red")
        led.set(True, color="#22cc66")
        self.assertEqual(
            led.display_value(led.value), {"value": True, "color": "#22cc66"}
        )
        led.set(False)
        with patch("cardtable.widgets.elements.led.Timer") as timer_class:
            led.flash(100)
            self.assertEqual(
                led.display_value(led.value), {"value": True, "color": "#22cc66"}
            )
            timer_class.call_args.args[1]()
        led.value = True
        led.reset()
        restored = pickle.loads(pickle.dumps(led))
        self.assertEqual(restored.color, "#22cc66")
        self.assertIs(restored.value, False)

    def test_set_validates_before_changing_value_or_color(self):
        led = LED("red")
        for color, error in ((123, TypeError), ("invalid-color", ValueError)):
            with self.assertRaises(error):
                led.set(True, color=color)
            self.assertEqual(led.color, "red")
            self.assertIs(led.value, False)
        with self.assertRaises(TypeError):
            led.set(1, color="blue")
        with self.assertRaises(TypeError):
            led.set(True, "blue")
        self.assertEqual(led.color, "red")

    def test_color_updates_are_published_and_rebuild_images_only_when_changed(self):
        owner = MagicMock()
        owner._started = False
        led = LED("red")
        led._bind(owner)
        with (
            patch("customtkinter.CTkFrame"),
            patch("customtkinter.CTkLabel"),
            patch("customtkinter.CTkImage"),
            patch("cardtable.widgets.elements.led.led_image") as render,
        ):
            led.build_ui(MagicMock(), MagicMock())
            # Change the color while the boolean value remains unchanged.
            led.set(False, color="blue")
            owner._element_changed.assert_called_once_with(led, False)
            payload = led.display_value(owner._element_changed.call_args.args[1])
            self.assertEqual(payload, {"value": False, "color": "blue"})
            led.update_ui(payload)
            self.assertEqual(render.call_count, 4)
            self.assertEqual(render.call_args_list[-2].args, ("blue", False))
            self.assertEqual(render.call_args_list[-1].args, ("blue", True))
            led._ui_indicator.configure.assert_called_once_with(image=led._ui_images[0])
            led.update_ui(payload)
            led.update_ui({"value": True, "color": "blue"})
            self.assertEqual(render.call_count, 4)
            led._ui_indicator.configure.assert_called_with(image=led._ui_images[1])

    def test_flash_turns_on_without_waiting_and_ignores_repeated_calls(self):
        led = LED("red")
        with patch("cardtable.widgets.elements.led.Timer") as timer_class:
            led.flash(250)
            self.assertIs(led.value, True)
            timer_class.assert_called_once()
            self.assertEqual(timer_class.call_args.args[0], 0.25)
            self.assertTrue(timer_class.return_value.daemon)
            timer_class.return_value.start.assert_called_once_with()
            led.flash(1000)
            timer_class.assert_called_once()
            timer_class.call_args.args[1]()
            self.assertIs(led.value, False)

        led.set(True)
        with patch("cardtable.widgets.elements.led.Timer") as timer_class:
            led.flash(250)
            timer_class.assert_not_called()
            self.assertIs(led.value, True)

    def test_old_flash_cannot_turn_off_a_new_value_or_flash(self):
        led = LED("green")
        with patch("cardtable.widgets.elements.led.Timer") as timer_class:
            led.flash(100)
            old_turn_off = timer_class.call_args.args[1]
            led.set(False)
            led.flash(500)
            new_turn_off = timer_class.call_args.args[1]
            old_turn_off()
            self.assertIs(led.value, True)
            restored = pickle.loads(pickle.dumps(led))
            self.assertIs(restored.value, True)
            new_turn_off()
            self.assertIs(led.value, False)

            led.flash(100)
            turn_off = timer_class.call_args.args[1]
            led.set(True)
            turn_off()
            self.assertIs(led.value, True)

    def test_flash_timer_publishes_both_states(self):
        finished = Event()

        class Owner:
            _state_lock = RLock()

            def __init__(self):
                self.values = []

            def _element_changed(self, element, value):
                self.values.append(value)
                if not value:
                    finished.set()

        owner = Owner()
        led = LED("blue")
        led._bind(owner)
        led.flash(20)
        self.assertTrue(finished.wait(1), "flash did not turn off")
        self.assertEqual(owner.values, [True, False])
        self.assertIs(led.value, False)

    def test_flash_validates_duration(self):
        led = LED("red")
        for duration in (True, 1.5, "100", None):
            with self.assertRaises(TypeError):
                led.flash(duration)
        for duration in (0, -1):
            with self.assertRaises(ValueError):
                led.flash(duration)
        self.assertIs(led.value, False)

    def test_boolean_state_and_serialization(self):
        led = LED("#22cc66", "Ready", default=True)
        self.assertIsInstance(led, InputElement)
        self.assertIs(led.get(), True)
        led.set(False)
        self.assertIs(led.value, False)
        led.reset()
        self.assertIs(led.value, True)
        restored = pickle.loads(pickle.dumps(led))
        self.assertEqual((restored.color, restored.label), ("#22cc66", "Ready"))
        self.assertIs(restored.value, True)
        with self.assertRaises(TypeError):
            led.set(1)
        for options in ({"default": 1}, {"label": 1}):
            with self.assertRaises(TypeError):
                LED("red", **options)
        with self.assertRaises(TypeError):
            LED(123)
        with self.assertRaises(ValueError):
            LED("invalid-color")

    def test_images_have_bright_lens_and_halo_only_when_on(self):
        off, on = (led_image("#00ff00", state) for state in (False, True))
        self.assertGreater(on.getpixel((64, 64))[1], off.getpixel((64, 64))[1])
        self.assertEqual(off.getpixel((112, 64))[3], 0)
        self.assertGreater(on.getpixel((112, 64))[3], 0)
        self.assertEqual(off.getpixel((64, 64))[3], 255)

    def test_rapid_updates_reuse_images_and_skip_unchanged_state(self):
        led = LED("red")
        emit = MagicMock()
        with (
            patch("customtkinter.CTkFrame"),
            patch("customtkinter.CTkLabel") as label_class,
            patch("customtkinter.CTkImage") as image_class,
            patch("cardtable.widgets.elements.led.led_image") as render,
        ):
            label, indicator = MagicMock(), MagicMock()
            label_class.side_effect = [label, indicator]
            image_class.side_effect = [MagicMock(), MagicMock()]
            led.build_ui(MagicMock(), emit)
            images = led._ui_images
            for _ in range(500):
                led.update_ui(True)
                led.update_ui(True)
                led.update_ui(False)
                led.update_ui(False)

            self.assertEqual(render.call_count, 2)
            self.assertEqual(image_class.call_count, 2)
            self.assertIs(led._ui_images, images)
            self.assertEqual(indicator.configure.call_count, 1000)
            indicator.configure.assert_called_with(image=images[False])
            emit.assert_not_called()

            # Even a rendered LED can be pickled without its Tk resources.
            restored = pickle.loads(pickle.dumps(led))
            self.assertFalse(any(key.startswith("_ui_") for key in led.__getstate__()))
            self.assertFalse(hasattr(restored, "_ui_images"))
            self.assertEqual((restored.color, restored.size), ("red", 24))
            self.assertIs(restored.value, False)

    def test_render_updates_clicks_and_disabled_state(self):
        ui = object.__new__(Card)
        ui._applying_update = False
        ui._emit = MagicMock()
        led = LED("red", "Ready", interactive=True)
        ui._ui_elements = {led.name: led}
        interpreter = tk.Tcl()
        with (
            patch("cardtable.widgets.card.card.ctk.CTkFrame"),
            patch("cardtable.widgets.card.card.ctk.CTkLabel") as label_class,
            patch("cardtable.widgets.card.card.ctk.CTkImage"),
        ):
            label, indicator = MagicMock(), MagicMock()
            label_class.side_effect = [label, indicator]
            ui._build_element_ui(interpreter, led, ui._emit)

        label.pack.assert_called_once_with(side="left", fill="x", expand=True)
        self.assertEqual(indicator.pack.call_args.kwargs["side"], "right")
        self.assertEqual(label_class.call_args.kwargs["image"], led._ui_images[0])
        ui._update_ui({led.name: True})
        indicator.configure.assert_called_with(image=led._ui_images[1])
        ui._emit.assert_not_called()

        toggle = indicator.bind.call_args.args[1]
        toggle(None)
        ui._emit.assert_called_once_with({led.name: False})
        indicator.configure.assert_called_with(image=led._ui_images[0])
        ui._update_element(led.name, state="disabled", label="Paused")
        label.configure.assert_called_with(text="Paused")
        toggle(None)
        self.assertEqual(ui._emit.call_count, 1)
        ui._update_element(led.name, state="normal", label=None)
        toggle(None)
        ui._emit.assert_called_with({led.name: True})


if __name__ == "__main__":
    unittest.main()
