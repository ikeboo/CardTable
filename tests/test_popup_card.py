import gc
import pickle
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


class PopupCardTest(unittest.TestCase):
    def setUp(self):
        # Earlier rendering tests use Tcl interpreters. Collect their cycles on
        # the owning thread before starting callback or auto-close threads.
        gc.collect()
        self.runtime = Mock(spec=CardRuntime)
        self.settings = patch.object(c.Deck, "_settings", _DeckSettings())
        self.frozen = patch.object(c.Deck, "_frozen", False)
        self.settings.start()
        self.frozen.start()

    def tearDown(self):
        Closure().close_all()
        self.settings.stop()
        self.frozen.stop()

    def popup(self):
        with c.PopupCard("Warning", runtime=self.runtime) as card:
            text = c.Text()
            with c.Row():
                yes = c.TrueBtn("Yes")
                no = c.FalseBtn("No")
                cancel = c.CancelBtn("Cancel")
        text.set("Continue?")
        return card, (yes, no, cancel)

    def test_results_and_cleanup_without_flow_callback_registration(self):
        for index, expected in enumerate((True, False, None)):
            with self.subTest(result=expected):
                baseline = Closure().objects
                card, buttons = self.popup()
                self.assertEqual(Closure().objects, (*baseline, card))
                self.runtime.poll.side_effect = lambda: card._receive_input(
                    _BtnPressed(buttons[index].id)
                )
                self.assertIs(card.wait(), expected)
                self.runtime.attach.assert_called_with(card)
                self.runtime.detach.assert_called_with(card.widget_id)
                self.assertEqual(Closure().objects, baseline)
                self.assertIs(card.wait(), expected)
                with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
                    card.start()

    def test_row_layout_and_result_buttons_survive_ui_copy_and_pickle(self):
        card, buttons = self.popup()
        self.assertEqual(card._ui_options["layout"], (0, (1, 2, 3)))
        elements = pickle.loads(pickle.dumps(card._ui_options["elements"]))
        for button, copied, expected in zip(buttons, elements[1:], (True, False, None)):
            self.assertIs(type(copied), type(button))
            self.assertIs(copied.result, expected)
            self.assertIsNone(copied._control)

    def test_default_and_custom_dimensions(self):
        card = c.PopupCard("Default", runtime=self.runtime)
        self.assertEqual(card.geometry, (0, 0, 6, 3))
        self.assertTrue(card._ui_options["popup"])
        self.assertTrue(card._ui_options["popup_auto_height"])
        c.Deck._settings = _DeckSettings(geometry_unit="px")
        pixels = c.PopupCard("Pixels", runtime=self.runtime)
        self.assertEqual(pixels.geometry, (0, 0, 480, 240))
        custom = c.PopupCard("Custom", w=600, h=200, runtime=self.runtime)
        self.assertEqual(custom.geometry, (0, 0, 600, 200))
        self.assertFalse(custom._ui_options["popup_auto_height"])

    def test_close_request_returns_none_without_closing_flow(self):
        card, _ = self.popup()
        handler = Mock()
        card._set_close_handler(handler)
        self.runtime.poll.side_effect = card._receive_close_requested
        self.assertIsNone(card.wait())
        handler.assert_not_called()

    def test_disabled_button_and_late_selection_do_not_replace_result(self):
        card, buttons = self.popup()
        buttons[0].disable()
        card._receive_input(_BtnPressed(buttons[0].id))
        self.assertFalse(card._completed.is_set())
        card._receive_input(_BtnPressed(buttons[1].id))
        card._receive_input(_BtnPressed(buttons[0].id))
        self.assertIs(card.wait(), False)

    def test_stop_unblocks_wait_from_another_thread(self):
        card, _ = self.popup()
        polling = Event()
        self.runtime.poll.side_effect = polling.set
        results = []

        def wait():
            try:
                card.wait()
            except RuntimeError as error:
                results.append(error)

        thread = Thread(target=wait, daemon=True)
        thread.start()
        self.assertTrue(polling.wait(1))
        card.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIn("stopped", str(results[0]))
        self.runtime.detach.assert_called_once()
        self.assertNotIn(card, Closure().objects)

    def test_close_unblocks_wait_from_another_thread(self):
        card, _ = self.popup()
        polling = Event()
        self.runtime.poll.side_effect = polling.set
        results = []
        thread = Thread(target=lambda: results.append(card.wait()), daemon=True)
        thread.start()
        self.assertTrue(polling.wait(1))
        card.close()
        card.close()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.runtime.detach.assert_called_once_with(card.widget_id)
        self.assertNotIn(card, Closure().objects)

    def test_close_before_start_disposes_without_opening_window(self):
        card = c.PopupCard("Unstarted", runtime=self.runtime)
        card.close()
        self.assertIsNone(card.wait())
        self.runtime.attach.assert_not_called()
        self.assertNotIn(card, Closure().objects)

    def test_auto_close_checks_ui_health_and_disposes_without_wait(self):
        with c.PopupCard("Notice", auto_close_sec=1, runtime=self.runtime) as card:
            c.Text()
        self.assertTrue(card._completed.wait(2))
        self.assertIsNone(card.wait())
        self.runtime.detach.assert_called_once_with(card.widget_id)
        self.runtime.poll.assert_called_once()
        self.assertNotIn(card, Closure().objects)

    def test_zero_duration_unblocks_wait(self):
        card = c.PopupCard("Immediate", auto_close_sec=0, runtime=self.runtime)
        self.assertIsNone(card.wait())
        self.runtime.detach.assert_called_once_with(card.widget_id)
        self.assertNotIn(card, Closure().objects)

    def test_selection_cancels_timer_and_close_preserves_result(self):
        with c.PopupCard("Choose", auto_close_sec=60, runtime=self.runtime) as card:
            button = c.TrueBtn("Yes")
        card.start()
        timer = card._auto_close_timer
        self.assertIsNotNone(timer)
        card.start()
        self.assertIs(card._auto_close_timer, timer)
        self.runtime.poll.side_effect = lambda: card._receive_input(
            _BtnPressed(button.id)
        )
        self.assertIs(card.wait(), True)
        timer.join(1)
        self.assertFalse(timer.is_alive())
        card.close()
        self.assertIs(card.wait(), True)
        self.runtime.attach.assert_called_once_with(card)

    def test_invalid_duration_does_not_register_popup(self):
        baseline = Closure().objects
        for duration in (True, False, 1.5, "3"):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(TypeError, "auto_close_sec"):
                    c.PopupCard(
                        "Invalid", auto_close_sec=duration, runtime=self.runtime
                    )
        with self.assertRaisesRegex(ValueError, "non-negative"):
            c.PopupCard("Invalid", auto_close_sec=-1, runtime=self.runtime)
        self.assertEqual(Closure().objects, baseline)

    def test_flow_shutdown_cancels_dynamic_popup_in_callback(self):
        class App(c.Dealer):
            def setup(app):
                app.trigger = c.TimerTrigger(1, callback=app.callback)

            def callback(app, event: c.TriggerEvent):
                try:
                    card.wait()
                except RuntimeError as error:
                    app.error = error

        card, _ = self.popup()
        app = App()
        self.addCleanup(app.close)
        # Closing the Dealer on a separate thread must not leave its callback
        # worker waiting forever for a popup selection.
        polling = Event()
        self.runtime.poll.side_effect = polling.set
        app.trigger._set_event(c.TriggerMessage(0, None))
        app._dispatch_messages()
        self.assertTrue(polling.wait(1))
        closing = Thread(target=app.close, daemon=True)
        closing.start()
        closing.join(1)
        self.assertFalse(closing.is_alive())
        self.assertIn("stopped", str(app.error))
        self.assertNotIn(card, Closure().objects)
        self.assertIsNone(_callback_stop_event.get())

    def test_concurrent_wait_is_rejected(self):
        card, _ = self.popup()

        def poll():
            with self.assertRaisesRegex(RuntimeError, "already active"):
                card.wait()
            card.close()

        self.runtime.poll.side_effect = poll
        self.assertIsNone(card.wait())

    def test_errors_and_failed_declarations_release_registrations(self):
        baseline = Closure().objects
        with self.assertRaisesRegex(ValueError, "layout failed"):
            with c.PopupCard("Error", runtime=self.runtime):
                c.TrueBtn("Yes")
                raise ValueError("layout failed")
        self.assertEqual(Closure().objects, baseline)
        card, _ = self.popup()
        self.runtime.wait_ready.side_effect = CardRuntimeError("UI failed")
        with self.assertRaisesRegex(CardRuntimeError, "UI failed"):
            card.wait()
        self.assertEqual(Closure().objects, baseline)
        self.runtime.detach.assert_called_once_with(card.widget_id)

    def test_wait_inside_declaration_context_is_rejected(self):
        with c.PopupCard("Test", runtime=self.runtime) as card:
            with self.assertRaisesRegex(RuntimeError, "finish the PopupCard context"):
                card.wait()
            self.runtime.attach.assert_not_called()
        self.runtime.attach.assert_called_once_with(card)

    def test_context_exit_starts_and_waits_before_progress_updates(self):
        with c.PopupCard("Progress", runtime=self.runtime) as card:
            bar = c.ProgressBar("Ready")
            self.runtime.attach.assert_not_called()
            self.runtime.wait_ready.assert_not_called()
        self.assertTrue(card._started)
        self.assertEqual(
            [call[0] for call in self.runtime.method_calls],
            ["attach", "update", "wait_ready"],
        )
        self.runtime.wait_ready.assert_called_once_with(card.widget_id, timeout=10.0)
        bar.set(50, "Waiting")
        self.assertEqual(
            self.runtime.update.call_args.args,
            (
                card.widget_id,
                {
                    bar.name: {"fraction": 0.5, "text": "Waiting", "caption": "50%"},
                },
            ),
        )
        self.runtime.poll.side_effect = card.close
        self.assertIsNone(card.wait())
        self.runtime.attach.assert_called_once_with(card)

    def test_context_startup_failure_cleans_up_and_propagates(self):
        for method in ("attach", "wait_ready"):
            with self.subTest(method=method):
                self.runtime.reset_mock(side_effect=True)
                baseline = Closure().objects
                getattr(self.runtime, method).side_effect = CardRuntimeError(
                    "UI failed"
                )
                with self.assertRaisesRegex(CardRuntimeError, "UI failed"):
                    with c.PopupCard("Error", runtime=self.runtime) as card:
                        c.TrueBtn("Yes")
                self.assertTrue(card._disposed)
                self.assertEqual(Closure().objects, baseline)
                if method == "wait_ready":
                    self.runtime.detach.assert_called_once_with(card.widget_id)
                else:
                    self.runtime.wait_ready.assert_not_called()

    def test_targeted_close_event_only_cancels_matching_popup(self):
        runtime = CardRuntime()
        runtime._event_queue = Queue()
        first = c.PopupCard("First", runtime=self.runtime)
        second = c.PopupCard("Second", runtime=self.runtime)
        for card in (first, second):
            runtime._widgets[card.widget_id] = card
            runtime._attachments[card.widget_id] = card.widget_id
            card._started = True
            self.runtime.is_attached.side_effect = lambda wid, attachment: (
                wid == attachment
            )
        runtime._event_queue.put(
            dict(
                type="close_requested",
                widget_id=second.widget_id,
                attachment_id="stale",
            )
        )
        runtime.poll()
        self.assertFalse(second._completed.is_set())
        runtime._event_queue.put(
            dict(
                type="close_requested",
                widget_id=second.widget_id,
                attachment_id=second.widget_id,
            )
        )
        runtime.poll()
        self.assertFalse(first._completed.is_set())
        self.assertTrue(second._completed.is_set())


class NativePopupTest(unittest.TestCase):
    def test_native_popup_renders_and_emits_selection_and_close(self):
        import subprocess
        import sys
        from pathlib import Path

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, unittest; sys.path.insert(0, 'tests'); "
                "from test_popup_card import NativePopupTest; "
                "result = unittest.TextTestRunner().run(unittest.TestSuite(["
                "NativePopupTest('check_native_popup')])); "
                "sys.exit(not result.wasSuccessful())",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if "skipped=1" in result.stderr:
            self.skipTest("Tk display unavailable in UI host process")

    def check_native_popup(self):
        import tkinter as tk

        import customtkinter as ctk

        from cardtable.widgets._ui_process import run_ui_process

        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        commands, events = Queue(), Queue()
        failures = []
        with c.PopupCard("Warning", default=False, runtime=Mock()) as card:
            c.Text()
            with c.Row():
                yes = c.TrueBtn("Yes")
                no = c.FalseBtn("No")
                c.CancelBtn("Cancel")
        commands.put(
            dict(
                type="create",
                widget_id=card.widget_id,
                attachment_id="popup-attachment",
                widget_class=card._class_path,
                name=card.name,
                options=pickle.loads(pickle.dumps(card._ui_options)),
            )
        )

        def check():
            try:
                root.update_idletasks()
                self.assertEqual([e for e in events.queue if "error" in e["type"]], [])
                window = next(
                    w for w in root.winfo_children() if isinstance(w, ctk.CTkToplevel)
                )
                self.assertEqual(window.title(), "Warning")
                self.assertTrue(window.winfo_viewable())
                self.assertFalse(root.winfo_viewable())
                self.assertGreater(window.winfo_width(), window.winfo_height())
                self.assertAlmostEqual(
                    window.winfo_rootx() + window.winfo_width() / 2,
                    window.winfo_screenwidth() / 2,
                    delta=30,
                )

                def descendants(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from descendants(child)

                buttons = [
                    w
                    for w in descendants(window)
                    if isinstance(w, ctk.CTkButton)
                    and w.cget("text") in {"Yes", "No", "Cancel"}
                ]
                self.assertEqual(
                    [b.cget("text") for b in buttons], ["Yes", "No", "Cancel"]
                )
                scrollable = next(
                    w for w in descendants(window)
                    if isinstance(w, ctk.CTkScrollableFrame)
                )
                self.assertAlmostEqual(
                    window.winfo_height(), scrollable.winfo_reqheight() + 2,
                    delta=4,
                )
                # Invoke the registered Tk binding even when macOS has not
                # granted this test process foreground keyboard focus.
                enter_command = window.bind("<Return>").split("[", 1)[1].split()[0]
                window.tk.call(enter_command)
                buttons[0].invoke()
                window.tk.call(window.protocol("WM_DELETE_WINDOW"))
                selections = [e for e in events.queue if e["type"] == "input"]
                self.assertEqual(selections[0]["payload"], _BtnPressed(no.id))
                self.assertEqual(selections[1]["payload"], _BtnPressed(yes.id))
                closes = [e for e in events.queue if e["type"] == "close_requested"]
                self.assertEqual(closes[0]["widget_id"], card.widget_id)
                self.assertEqual(closes[0]["attachment_id"], "popup-attachment")
            except Exception as error:
                failures.append(error)
            finally:
                commands.put(dict(type="shutdown"))
                card.stop()

        root.after(350, check)
        with patch.object(ctk, "CTk", return_value=root):
            run_ui_process(commands, events, Mock())
        if failures:
            raise failures[0]


if __name__ == "__main__":
    unittest.main()
