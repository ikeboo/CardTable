import gc
import itertools
import unittest
from queue import Queue
from threading import Event, Thread
from unittest.mock import Mock, patch

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.core.dealer import _callback_stop_event
from cardtable.widgets._runtime import CardRuntime, CardRuntimeError
from cardtable.widgets.deck import _DeckSettings
from cardtable.widgets.elements.button import _BtnPressed


class ShowMessageTest(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.runtime = CardRuntime()
        for target, name, kwargs in (
            (CardRuntime, "_instance", {"new": self.runtime}),
            (c.Deck, "_settings", {"new": _DeckSettings()}),
            (c.Deck, "_frozen", {"new": False}),
            (self.runtime, "_ensure_process", {}),
            (self.runtime, "_shutdown_process", {}),
            (self.runtime, "_send", {}),
            (self.runtime, "wait_ready", {}),
            (self.runtime, "poll", {}),
        ):
            patcher = patch.object(target, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(Closure().close_all)

    def popup(self):
        return next(
            card for card in self.runtime.get_cards() if isinstance(card, c.PopupCard)
        )

    def test_public_exports_and_button_results(self):
        from cardtable.widgets import show_message

        self.assertIs(show_message, c.show_message)
        baseline = Closure().objects
        for expected in (True, False, None):

            def choose():
                card = self.popup()
                button = next(
                    b for b in card._buttons_by_id.values() if b.result is expected
                )
                card._receive_input(_BtnPressed(button.id))

            self.runtime.poll.side_effect = choose
            self.assertIs(c.show_message("First\nSecond", false_btn="No"), expected)
            self.assertEqual(self.runtime.get_cards(), [])
            self.assertEqual(self.runtime._deck_disable_count, 0)
            self.assertEqual(Closure().objects, baseline)
        create = next(
            call.args[0]
            for call in self.runtime._send.call_args_list
            if call.args[0]["type"] == "create"
        )
        self.assertEqual(create["name"], "Message")
        self.assertEqual(create["options"]["elements"][0].label, "First\nSecond")

    def test_close_policy_for_all_button_combinations(self):
        for labels in itertools.product((None, "Button"), repeat=3):
            with self.subTest(labels=labels):
                visible = [
                    v
                    for v, label in zip((True, False, None), labels)
                    if label is not None
                ]
                enabled = labels[2] is not None or len(visible) <= 1
                expected = visible[0] if len(visible) == 1 else None

                def close():
                    card = self.popup()
                    card._receive_close_requested()
                    self.assertEqual(card._completed.is_set(), enabled)
                    if not enabled:
                        card._finish(False)

                self.runtime.poll.side_effect = close
                self.assertIs(
                    c.show_message(
                        "Close?",
                        true_btn=labels[0],
                        false_btn=labels[1],
                        none_btn=labels[2],
                    ),
                    expected if enabled else False,
                )

    def test_default_fallback_and_automatic_close(self):
        cases = (
            ({}, None),
            ({"none_btn": None}, True),
            ({"false_btn": "No", "none_btn": None}, False),
            ({"false_btn": "No", "default": True}, True),
            ({"true_btn": None, "false_btn": "No", "default": False}, False),
            ({"true_btn": None, "none_btn": None}, None),
        )
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertIs(
                    c.show_message("Expires", auto_close_sec=0, **kwargs), expected
                )
                self.assertEqual(self.runtime._deck_disable_count, 0)

    def test_validation_happens_before_disabling_or_registering(self):
        baseline = Closure().objects
        for kwargs, error in (
            ({"message": 1}, TypeError),
            ({"title": None}, TypeError),
            ({"true_btn": False}, TypeError),
            ({"false_btn": 1}, TypeError),
            ({"none_btn": []}, TypeError),
            ({"default": 1}, TypeError),
            ({"default": False}, ValueError),
            ({"default": True, "true_btn": None}, ValueError),
            ({"auto_close_sec": True}, TypeError),
            ({"auto_close_sec": 0.5}, TypeError),
            ({"auto_close_sec": -1}, ValueError),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(error):
                c.show_message(**{"message": "Invalid", **kwargs})
        self.assertEqual(self.runtime._deck_disable_count, 0)
        self.assertEqual(Closure().objects, baseline)
        self.runtime._send.assert_not_called()

    def test_ui_failures_restore_preexisting_disable_state(self):
        for phase in ("startup", "waiting", "expiry"):
            with self.subTest(phase=phase):
                baseline = Closure().objects
                c.Deck.disable()
                if phase == "startup":
                    self.runtime.wait_ready.side_effect = CardRuntimeError("UI failed")
                    target = "wait_ready"
                else:
                    self.runtime._errors.clear()
                    self.runtime.poll.side_effect = lambda: self.runtime._errors.update(
                        {self.popup().widget_id: "UI failed"}
                    )
                    target = "poll"
                with self.assertRaisesRegex(CardRuntimeError, "UI failed"):
                    c.show_message(
                        "Failed", auto_close_sec=0 if phase == "expiry" else None
                    )
                getattr(self.runtime, target).side_effect = None
                self.assertEqual(self.runtime._deck_disable_count, 1)
                self.assertEqual(self.runtime.get_cards(), [])
                self.assertEqual(Closure().objects, baseline)
                c.Deck.enable()

    def test_calls_are_fifo_and_keep_deck_disabled_between_windows(self):
        started, queued, release = Event(), Event(), Event()
        shown, results, errors = [], [], []
        disable = self.runtime.disable_deck

        def disabling():
            disable()
            if self.runtime._deck_disable_count == 2:
                queued.set()

        def ready(widget_id, **kwargs):
            card = self.popup()
            if card.name not in shown:
                shown.append(card.name)
                if card.name == "First":
                    started.set()
                else:
                    self.assertGreaterEqual(self.runtime._deck_disable_count, 1)

        def poll():
            card = self.popup()
            if card.name == "First" and not release.is_set():
                return
            card._finish(True)

        def run(title):
            try:
                results.append(c.show_message(title, title=title))
            except Exception as error:
                errors.append(error)

        self.runtime.wait_ready.side_effect = ready
        self.runtime.poll.side_effect = poll
        with patch.object(self.runtime, "disable_deck", side_effect=disabling):
            first = Thread(target=run, args=("First",), daemon=True)
            second = Thread(target=run, args=("Second",), daemon=True)
            try:
                first.start()
                self.assertTrue(started.wait(1))
                second.start()
                self.assertTrue(queued.wait(1))
                self.assertEqual(shown, ["First"])
            finally:
                release.set()
                first.join(2)
                second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(shown, ["First", "Second"])
        self.assertEqual(results, [True, True])
        self.assertEqual(self.runtime._deck_disable_count, 0)

    def test_queued_call_can_be_cancelled_without_waiting_for_active_dialog(self):
        active, queued, release, stop = Event(), Event(), Event(), Event()
        errors = []
        disable = self.runtime.disable_deck

        def disabling():
            disable()
            if self.runtime._deck_disable_count == 2:
                queued.set()

        def poll():
            active.set()
            if release.is_set():
                self.popup()._finish(None)

        def run(cancel=False):
            token = _callback_stop_event.set(stop if cancel else None)
            try:
                c.show_message("Wait")
            except RuntimeError as error:
                errors.append(error)
            finally:
                _callback_stop_event.reset(token)

        self.runtime.poll.side_effect = poll
        with patch.object(self.runtime, "disable_deck", side_effect=disabling):
            first = Thread(target=run, daemon=True)
            second = Thread(target=run, args=(True,), daemon=True)
            try:
                first.start()
                self.assertTrue(active.wait(1))
                second.start()
                self.assertTrue(queued.wait(1))
                stop.set()
                second.join(1)
                self.assertFalse(second.is_alive())
                self.assertEqual(self.runtime._deck_disable_count, 1)
            finally:
                release.set()
                first.join(2)
                second.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIn("Dealer stopped", str(errors[0]))
        self.assertEqual(self.runtime._deck_disable_count, 0)

    def test_reentrant_call_raises_instead_of_deadlocking(self):
        def poll():
            with self.assertRaisesRegex(RuntimeError, "reentrantly"):
                c.show_message("Nested")
            self.popup()._finish(True)

        self.runtime.poll.side_effect = poll
        self.assertIs(c.show_message("Outer"), True)
        self.assertEqual(self.runtime._deck_disable_count, 0)

    def test_flow_stopped_while_displaying_raises_and_cleans_up(self):
        stop = Event()
        token = _callback_stop_event.set(stop)
        self.addCleanup(_callback_stop_event.reset, token)
        self.runtime.poll.side_effect = stop.set
        with self.assertRaisesRegex(RuntimeError, "Dealer stopped"):
            c.show_message("Wait")
        self.assertEqual(self.runtime.get_cards(), [])
        self.assertEqual(self.runtime._deck_disable_count, 0)

    def test_disabled_deck_discards_queued_input_but_delivers_popup_input(self):
        runtime = self.runtime
        main = c.Card(0, 0, 4, 4, "Main")
        with c.PopupCard("Popup") as popup:
            button = c.TrueBtn("Yes")
        main.start()
        received = Mock()
        main._receive_input = received
        runtime._event_queue = Queue()
        for card, payload in ((main, {"value": 1}), (popup, _BtnPressed(button.id))):
            runtime._event_queue.put(
                dict(
                    type="input",
                    widget_id=card.widget_id,
                    payload=payload,
                    attachment_id=runtime._attachments[card.widget_id],
                )
            )
        c.Deck.disable()
        # Call the real poll implementation to exercise transport filtering.
        CardRuntime.poll(runtime)
        received.assert_not_called()
        self.assertIs(popup.wait(), True)
        self.assertTrue(main._started)
        main.stop()
        c.Deck.enable()
