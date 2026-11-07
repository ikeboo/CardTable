import inspect
import pickle
import unittest
from unittest.mock import Mock, patch

from test_widgets import FakeRuntime

from cardtable import Card, Deck
from cardtable.core.closure import Closure
from cardtable.widgets import Deck as WidgetsDeck
from cardtable.widgets import theme
from cardtable.widgets._runtime import CardRuntime
from cardtable.widgets.deck import _DeckSettings


class DeckTest(unittest.TestCase):
    def setUp(self):
        listener = patch("cardtable.widgets._runtime.LogListener")
        listener.start()
        self.addCleanup(listener.stop)
        # Each test represents a fresh application, without a public reset API.
        settings = patch.object(Deck, "_settings", _DeckSettings())
        frozen = patch.object(Deck, "_frozen", False)
        settings.start()
        frozen.start()
        self.addCleanup(settings.stop)
        self.addCleanup(frozen.stop)
        self.addCleanup(Closure().close_all)

    def test_print_replaces_text_flattens_lines_and_clears(self):
        runtime = CardRuntime()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_process_is_alive", return_value=True),
            patch.object(runtime, "_send") as send,
        ):
            Deck.print("Loading", 3)
            send.assert_called_with({"type": "status_text", "text": "Loading 3"})
            Deck.print("Done\r\nNext\nLine", "ok", sep=" / ")
            send.assert_called_with(
                {"type": "status_text", "text": "Done Next Line / ok"}
            )
            Deck.print()
            send.assert_called_with({"type": "status_text", "text": ""})

    def test_disable_enable_nest_without_starting_ui_or_changing_controls(self):
        runtime = CardRuntime()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_send") as send,
            patch.object(runtime, "_process_is_alive", return_value=False) as alive,
        ):
            Deck.disable()
            send.assert_not_called()
            alive.return_value = True
            Deck.disable()
            Deck.enable()
            send.assert_not_called()
            Deck.enable()
            send.assert_called_once_with({"type": "deck_enabled", "enabled": True})
            Deck.enable()
            self.assertEqual(send.call_count, 1)
            Deck.disable()
            send.assert_called_with({"type": "deck_enabled", "enabled": False})

    def test_disabled_state_is_sent_on_ui_start_and_restart(self):
        runtime = CardRuntime()
        context = Mock()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_send") as send,
            patch.object(runtime, "_drain_events", return_value=[]),
            patch("cardtable.widgets._runtime.multiprocessing.get_context",
                  return_value=context),
        ):
            Deck.disable()
            for _ in range(2):
                runtime._ensure_process()
                send.assert_called_with({"type": "deck_enabled", "enabled": False})
                runtime._shutdown_process()
                send.reset_mock()
            Deck.enable()

    def test_print_before_startup_is_retained_across_ui_restarts(self):
        runtime = CardRuntime()
        context = Mock()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_send") as send,
            patch.object(runtime, "_drain_events", return_value=[]),
            patch(
                "cardtable.widgets._runtime.multiprocessing.get_context",
                return_value=context,
            ),
        ):
            Deck.print("Ready")
            send.assert_not_called()
            self.assertIsNone(runtime._process)
            for _ in range(2):
                runtime._ensure_process()
                send.assert_called_with({"type": "status_text", "text": "Ready"})
                runtime._shutdown_process()
                send.reset_mock()

    def test_get_cards_tracks_connections_and_returns_an_independent_list(self):
        runtime = CardRuntime()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_ensure_process") as start_ui,
            patch.object(runtime, "_send"),
            patch.object(runtime, "_shutdown_process"),
        ):
            self.assertEqual(Deck.get_cards(), [])
            start_ui.assert_not_called()
            first = Card(0, 0, 4, 4, "First")
            second = Card(4, 0, 4, 4, "Second")
            self.assertEqual(Deck.get_cards(), [])
            second.start()
            first.start()
            first.start()
            self.assertEqual(Deck.get_cards(), [second, first])
            second.hide()
            self.assertEqual(Deck.get_cards(), [second, first])
            cards = Deck.get_cards()
            cards.clear()
            self.assertEqual(Deck.get_cards(), [second, first])
            second.stop()
            self.assertEqual(Deck.get_cards(), [first])
            second.start()
            self.assertEqual(Deck.get_cards(), [first, second])
            first.stop()
            second.stop()
            self.assertEqual(Deck.get_cards(), [])

    def test_get_cards_excludes_cards_whose_attachment_failed(self):
        runtime = CardRuntime()
        with (
            patch.object(CardRuntime, "_instance", runtime),
            patch.object(runtime, "_ensure_process"),
            patch.object(runtime, "_send", side_effect=RuntimeError("send failed")),
        ):
            card = Card(0, 0, 4, 4, "Card")
            with self.assertRaisesRegex(RuntimeError, "send failed"):
                card.start()
            self.assertEqual(Deck.get_cards(), [])

    def test_defaults_require_no_configuration(self):
        self.assertIs(Deck, WidgetsDeck)
        card = Card(0, 0, 4, 4, "Default", runtime=FakeRuntime())
        self.assertEqual(card.geometry, (0, 0, 4, 4))
        self.assertEqual(card.geometry_unit, "grid")
        self.assertEqual(Deck._snapshot(), _DeckSettings())
        for option in ("geometry_unit", "grid_columns", "grid_aspect", "window_width"):
            self.assertNotIn(option, inspect.signature(Card).parameters)
            self.assertNotIn(option, card._ui_options)

    def test_partial_configuration_is_shared_and_normalized(self):
        Deck.configure(grid_columns=16, grid_aspect=[2, 1])
        Deck.configure(window_width=1600, geometry_unit="GRID")
        first = Card(12, 0, 4, 4, "First", runtime=FakeRuntime())
        second = Card(0, 4, 16, 2, "Second", runtime=FakeRuntime())
        settings = Deck._snapshot()
        self.assertEqual(settings, _DeckSettings("grid", 16, (2.0, 1.0), 1600))
        self.assertIs(first._deck_settings, settings)
        self.assertIs(second._deck_settings, settings)
        self.assertEqual(pickle.loads(pickle.dumps(settings)), settings)
        with self.assertRaisesRegex(ValueError, "fit within 16 columns"):
            first._receive_geometry((13, 0, 4, 4))

    def test_pixel_coordinates_apply_to_all_cards(self):
        Deck.configure(geometry_unit="px")
        first = Card(20, 30, 800, 600, "First", runtime=FakeRuntime())
        second = Card(820, 30, 400, 600, "Second", runtime=FakeRuntime())
        for card in (first, second):
            self.assertEqual(card.geometry_unit, "px")
        first._receive_geometry((30, 40, 900, 700))
        self.assertEqual(first.geometry, (30, 40, 900, 700))

    def test_theme_is_snapshotted_and_serializable(self):
        from copy import deepcopy
        from dataclasses import replace

        colors = deepcopy(theme.DEFAULT_DARK.colors)
        colors["TITLE_BG_COLOR"] = "#123456"
        custom = replace(
            theme.DEFAULT_DARK,
            colors=colors,
            ctk_colors={"CTkEntry": {"fg_color": "#234567"}},
        )
        with patch.dict(theme.THEMES, {"CUSTOM": custom}):
            Deck.configure(theme="CUSTOM")
        colors["TITLE_BG_COLOR"] = "#FFFFFF"
        Deck.configure(window_width=1600)
        settings = pickle.loads(pickle.dumps(Deck._snapshot()))
        self.assertEqual(settings.theme, "CUSTOM")
        self.assertEqual(settings.theme_definition.colors["TITLE_BG_COLOR"], "#123456")
        self.assertEqual(settings.theme_definition.ctk_colors, custom.ctk_colors)
        self.assertEqual(settings.window_width, 1600)

    def test_light_theme_is_retained_on_ui_restart(self):
        Deck.configure(theme="DEFAULT_LIGHT")
        context = Mock()
        runtime = CardRuntime()
        with (
            patch(
                "cardtable.widgets._runtime.multiprocessing.get_context",
                return_value=context,
            ),
            patch.object(runtime, "_drain_events", return_value=[]),
        ):
            for _ in range(2):
                runtime._ensure_process()
                runtime._shutdown_process()
        for call in context.Process.call_args_list:
            settings = call.kwargs["args"][4]
            self.assertEqual(settings.theme, "DEFAULT_LIGHT")
            self.assertEqual(settings.theme_definition.appearance_mode, "Light")

    def test_configuration_remains_frozen_after_card_stop(self):
        Deck.configure(window_width=1000)
        card = Card(0, 0, 4, 4, "First", runtime=FakeRuntime())
        for stop in (False, True):
            if stop:
                card.start()
                Closure().close_all()
            with self.assertRaisesRegex(RuntimeError, "before creating Cards"):
                Deck.configure(window_width=1600)
            self.assertEqual(Deck._snapshot().window_width, 1000)

    def test_invalid_settings_do_not_apply_partial_changes(self):
        for kwargs, error in (
            ({"geometry_unit": "invalid"}, ValueError),
            ({"geometry_unit": 123}, TypeError),
            ({"grid_columns": 0}, ValueError),
            ({"grid_columns": 2.5}, TypeError),
            ({"grid_aspect": (0, 1)}, ValueError),
            ({"grid_aspect": (1,)}, ValueError),
            ({"grid_aspect": ("1", 1)}, TypeError),
            ({"window_width": 0}, ValueError),
            ({"window_width": "1200"}, TypeError),
            ({"theme": "MISSING"}, ValueError),
            ({"theme": 123}, TypeError),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(error):
                    Deck.configure(**{"grid_columns": 16, **kwargs})
                self.assertEqual(Deck._snapshot(), _DeckSettings())
        Deck.configure(window_width=1600)
        self.assertEqual(Deck._snapshot().window_width, 1600)

    def test_invalid_card_geometry_does_not_freeze_configuration(self):
        Deck.configure(grid_columns=8)
        with self.assertRaisesRegex(ValueError, "fit within 8 columns"):
            Card(6, 0, 4, 4, "Invalid", runtime=FakeRuntime())
        Deck.configure(grid_columns=16)
        card = Card(6, 0, 4, 4, "Valid", runtime=FakeRuntime())
        self.assertEqual(card.geometry, (6, 0, 4, 4))

    def test_card_rejects_deck_options(self):
        for name, value in (
            ("geometry_unit", "px"),
            ("grid_columns", 16),
            ("grid_aspect", (1, 1)),
            ("window_width", 1600),
            ("theme", "DEFAULT_LIGHT"),
        ):
            with self.subTest(option=name):
                with self.assertRaisesRegex(TypeError, "Deck.configure"):
                    Card(0, 0, 4, 4, "Invalid", runtime=FakeRuntime(), **{name: value})

    def test_ui_process_receives_settings_on_start_and_restart(self):
        Deck.configure(grid_columns=16, grid_aspect=(2, 1), window_width=1600)
        Card(0, 0, 4, 4, "Card", runtime=FakeRuntime())
        settings = Deck._snapshot()
        context = Mock()
        runtime = CardRuntime()
        with (
            patch(
                "cardtable.widgets._runtime.multiprocessing.get_context",
                return_value=context,
            ),
            patch.object(runtime, "_drain_events", return_value=[]),
        ):
            runtime._ensure_process()
            runtime._shutdown_process()
            runtime._ensure_process()
            runtime._shutdown_process()
        self.assertEqual(context.Process.call_count, 2)
        for call in context.Process.call_args_list:
            self.assertEqual(call.kwargs["args"][4], settings)
