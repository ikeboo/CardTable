import subprocess
import sys
import textwrap
import unittest


class LazyImportsTest(unittest.TestCase):
    def run_in_fresh_interpreter(self, source: str) -> None:
        subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_importing_package_does_not_import_public_implementations(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable

            loaded = {
                name for name in sys.modules
                if name == "cardtable" or name.startswith("cardtable.")
            }
            assert loaded == {"cardtable"}, loaded
            """
        )

    def test_webhook_payload_types_load_without_server_or_ui(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.WebhookEventData.__name__ == "WebhookEventData"
            assert c.WebhookImageData.__name__ == "WebhookImageData"
            assert "WebhookEventData" in c.__all__
            assert "WebhookImageData" in c.__all__
            assert "http.server" not in sys.modules
            assert "tkinter" not in sys.modules
            """
        )

    def test_jrpc_trigger_loads_without_ui_or_other_event_sources(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.JRPCTrigger.__name__ == "JRPCTrigger"
            assert "JRPCTrigger" in c.__all__
            for module in ("tkinter", "customtkinter", "watchdog", "croniter"):
                assert module not in sys.modules, module
            """
        )

    def test_webhook_trigger_loads_without_other_sources_or_ui(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.WebhookTrigger.__name__ == "WebhookTrigger"
            assert "WebhookTrigger" in c.__all__
            modules = ("tkinter", "customtkinter", "watchdog", "croniter", "requests")
            for module in modules:
                assert module not in sys.modules, module
            """
        )

    def test_schedule_payload_type_does_not_import_scheduler_or_tk(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.ScheduleEventData.__name__ == "ScheduleEventData"
            assert "ScheduleEventData" in c.__all__
            assert "croniter" not in sys.modules
            assert "tzlocal" not in sys.modules
            assert "tkinter" not in sys.modules
            """
        )

    def test_schedule_trigger_loads_without_ui_or_other_event_sources(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.ScheduleTrigger.__name__ == "ScheduleTrigger"
            assert "ScheduleTrigger" in c.__all__
            assert "tkinter" not in sys.modules
            assert "customtkinter" not in sys.modules
            assert "watchdog" not in sys.modules
            assert "pynput" not in sys.modules
            """
        )

    def test_filesystem_payload_types_do_not_import_watchdog_or_tk(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.FileSystemEventData.__name__ == "FileSystemEventData"
            assert c.FileSystemEventKind is not None
            assert "watchdog" not in sys.modules
            assert "tkinter" not in sys.modules
            assert "FileSystemEventData" in c.__all__
            assert "FileSystemEventKind" in c.__all__
            """
        )

    def test_filesystem_trigger_loads_without_ui_or_other_event_sources(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.FileSystemTrigger.__name__ == "FileSystemTrigger"
            assert "FileSystemTrigger" in c.__all__
            assert "tkinter" not in sys.modules
            assert "customtkinter" not in sys.modules
            assert "pynput" not in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            """
        )

    def test_accessing_deck_does_not_create_or_import_tk(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            c.Deck.configure(window_width=1600)
            assert "customtkinter" not in sys.modules
            assert "tkinter" not in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            assert "cardtable.widgets._runtime" not in sys.modules
            """
        )

    def test_accessing_dealer_does_not_import_unrelated_public_classes(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            dealer = c.Dealer

            assert dealer.__name__ == "Dealer"
            assert "cardtable.core.dealer" in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            assert "cardtable.triggers.keyboard_trigger" not in sys.modules
            assert "cardtable.services.web_image_acquirer" not in sys.modules
            """
        )

    def test_accessing_an_element_does_not_import_card_rendering(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            entry = c.Entry

            assert entry.__name__ == "Entry"
            assert "cardtable.widgets.elements.entry" in sys.modules
            assert "cardtable.widgets.elements._input" in sys.modules
            assert "cardtable.widgets.elements.slider" not in sys.modules
            control = "cardtable.widgets.elements._range_slider_control"
            assert control not in sys.modules
            assert "customtkinter" not in sys.modules
            assert "tkinter" not in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            assert "cardtable.widgets.elements.image" not in sys.modules
            assert "cardtable.widgets.elements.text" not in sys.modules
            assert "cardtable.widgets.elements.led" not in sys.modules
            assert "cardtable.widgets.elements.separator" not in sys.modules
            assert "cardtable.widgets.elements.button" not in sys.modules
            """
        )

    def test_accessing_card_does_not_load_concrete_element_renderers(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.Card.__name__ == "Card"
            for name in (
                "radio", "combo_box", "slider", "range_slider", "number",
                "entry", "file_dialog", "file_drop", "switch", "check_box",
                "_range_slider_control", "image", "text", "led",
            ):
                assert f"cardtable.widgets.elements.{name}" not in sys.modules
            """
        )

    def test_each_input_loads_without_tk_or_unrelated_inputs(self):
        modules = {
            "InputElement": "_input",
            "CheckBox": "check_box",
            "ComboBox": "combo_box",
            "Entry": "entry",
            "FileDialog": "file_dialog",
            "FileDrop": "file_drop",
            "Number": "number",
            "Radio": "radio",
            "RangeSlider": "range_slider",
            "Slider": "slider",
            "Switch": "switch",
        }
        for name, module in modules.items():
            with self.subTest(element=name):
                self.run_in_fresh_interpreter(
                    f"""
                    import sys
                    import cardtable as c

                    cls = getattr(c, {name!r})
                    prefix = "cardtable.widgets.elements."
                    assert cls.__module__ == prefix + {module!r}
                    allowed = {{"_input", {module!r}}}
                    if {name!r} == "Number":
                        allowed.add("slider")
                    for other in {tuple(modules.values())!r}:
                        if other not in allowed:
                            assert prefix + other not in sys.modules, other
                    assert "customtkinter" not in sys.modules
                    assert "tkinter" not in sys.modules
                    assert prefix + "_range_slider_control" not in sys.modules
                    """
                )

    def test_accessing_separator_does_not_import_input_base_or_led(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            import cardtable as c

            assert c.Separator.__module__ == "cardtable.widgets.elements.separator"
            assert "cardtable.widgets.elements._input" not in sys.modules
            assert "cardtable.widgets.elements.led" not in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            """
        )

    def test_labels_load_without_tk(self):
        self.run_in_fresh_interpreter(
            """
            import sys
            from cardtable import Label, BoxedLabel, ProgressBar

            assert issubclass(BoxedLabel, Label)
            Label("Text")
            BoxedLabel("Badge")
            ProgressBar().set(10, "loading")
            assert "customtkinter" not in sys.modules
            assert "tkinter" not in sys.modules
            assert "cardtable.widgets.card.card" not in sys.modules
            """
        )

    def test_element_exports_resolve_to_the_same_classes(self):
        self.run_in_fresh_interpreter(
            """
            import cardtable as c
            from cardtable import widgets
            from cardtable.widgets import elements
            from cardtable.widgets.elements.separator import Separator
            from cardtable.widgets.elements.led import LED

            for cls in (
                Separator, LED, c.Label, c.BoxedLabel, c.ProgressBar,
                c.InputElement, c.Radio, c.ComboBox,
                c.Slider, c.RangeSlider, c.Number, c.Entry, c.FileDrop,
                c.Switch, c.CheckBox,
            ):
                for api in (c, widgets, elements):
                    assert getattr(api, cls.__name__) is cls
            """
        )

    def test_button_and_legacy_alias_share_the_same_class(self):
        self.run_in_fresh_interpreter(
            """
            import pickle
            import sys
            import cardtable as c
            from cardtable import widgets
            from cardtable.widgets import elements
            from cardtable.widgets.elements import button

            assert button.Button.__name__ == "Button"
            for api in (c, widgets, elements, button):
                assert api.Button is button.Button
                assert api.Btn is button.Button
                assert "Button" in api.__all__
                assert "Btn" in api.__all__
            for cls in (c.Button, c.Btn):
                instance = cls("Run")
                restored = pickle.loads(pickle.dumps(instance))
                assert type(restored) is c.Button
                assert restored.label == "Run"
            for cls in (c.TrueBtn, c.FalseBtn, c.CancelBtn):
                assert issubclass(cls, c.Button)
                assert issubclass(cls, c.Btn)
            assert "customtkinter" not in sys.modules
            assert "tkinter" not in sys.modules
            """
        )


if __name__ == "__main__":
    unittest.main()
