import logging
import tempfile
import unittest
from functools import partial

import cardtable as c
from cardtable._logging import _CallerFilter, _LogFormatter
from cardtable.core.closure import Closure
from cardtable.data_classes.trigger_message import TriggerMessage
from cardtable.widgets.elements.button import ButtonControl


class TriggerLoggingTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_setup_start_and_completion_are_logged(self):
        class App(c.Dealer):
            def setup(self):
                pass

        with self.assertLogs("cardtable.core.dealer", level="INFO") as captured:
            app = App()
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["App.setup started", "App.setup completed"],
        )
        app.close()

    def test_failed_setup_does_not_log_completion(self):
        class App(c.Dealer):
            def setup(self):
                raise ValueError("setup failed")

        with self.assertLogs("cardtable.core.dealer", level="INFO") as captured:
            with self.assertRaisesRegex(ValueError, "setup failed"):
                App()
        self.assertEqual(
            [record.getMessage() for record in captured.records], ["App.setup started"]
        )

    def test_defaults_and_overrides_for_all_trigger_types(self):
        with tempfile.TemporaryDirectory() as directory:
            triggers = [
                c.KeyTrigger("<ctrl>+k"),
                c.FileSystemTrigger(directory),
                c.ScheduleTrigger("* * * * *"),
                c.WebhookTrigger(),
                c.JRPCTrigger(),
                ButtonControl(c.Button("Run")),
            ]
            self.assertTrue(all(t.log_level == logging.INFO for t in triggers))
            self.assertEqual(c.TimerTrigger(100).log_level, logging.DEBUG)
            self.assertEqual(
                c.TimerTrigger(100, log_level="info").log_level, logging.INFO
            )
            self.assertEqual(
                c.KeyTrigger("a", log_level=logging.DEBUG).log_level, logging.DEBUG
            )
            button = ButtonControl(c.Button("Run", log_level="DEBUG"))
            self.assertEqual(button.log_level, logging.DEBUG)
            for invalid in ("invalid", None, True):
                with (
                    self.subTest(invalid=invalid),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    c.TimerTrigger(100, log_level=invalid)

    def test_records_only_dispatched_events_at_configured_level(self):
        class App(c.Dealer):
            def setup(self):
                self.key = c.KeyTrigger("a", callback=lambda: None)
                self.timer = c.TimerTrigger(100, callback=lambda: None)

        app = App()
        with self.assertLogs("cardtable.core.dealer", level="DEBUG") as captured:
            for trigger in (app.key, app.timer):
                message = TriggerMessage(0)
                self.assertTrue(trigger._set_event(message))
                self.assertFalse(trigger._set_event(TriggerMessage(0)))
                app._dispatch_messages()
                app.wait_for_idle(timeout=2)
        self.assertEqual(
            [r.levelno for r in captured.records], [logging.INFO, logging.DEBUG]
        )
        self.assertIn(app.key.id, captured.output[0])
        self.assertIn(app.timer.id, captured.output[1])
        app.close()

    def test_callback_errors_remain_error_when_execution_is_debug(self):
        def fail():
            raise ValueError("failure")

        class App(c.Dealer):
            def setup(self):
                self.timer = c.TimerTrigger(100, callback=fail)

        app = App()
        with self.assertLogs("cardtable.core.dealer", level="ERROR") as captured:
            app.timer._set_event(TriggerMessage(0))
            app._dispatch_messages()
            app.wait_for_idle(timeout=2)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelno, logging.ERROR)
        self.assertIsNotNone(captured.records[0].exc_info)
        self.assertEqual(
            captured.records[0].cardtable_caller, "test_trigger_logging.fail"
        )
        app.close()

    def test_each_callback_identifies_its_target_in_formatted_output(self):
        class Handler:
            def __call__(self):
                pass

        def function():
            pass

        class App(c.Dealer):
            def setup(self):
                self.key = c.KeyTrigger("a", callback=self.on_key)

            def on_key(self):
                pass

        app = App()
        app._register_callback(app.key, Handler())
        app._register_callback(app.key, partial(function))
        with self.assertLogs("cardtable.core.dealer", level="INFO") as captured:
            app.key._set_event(TriggerMessage(0))
            app._dispatch_messages()
            app.wait_for_idle(timeout=2)

        names = [record.cardtable_caller for record in captured.records]
        self.assertEqual(
            names, ["App.on_key", "Handler.__call__", "test_trigger_logging.function"]
        )
        formatter = _LogFormatter("%(cardtable_caller)s | %(message)s")
        for record, name in zip(captured.records, names):
            _CallerFilter().filter(record)
            self.assertTrue(formatter.format(record).startswith(name))
            self.assertIn("KeyTrigger callback started", record.getMessage())
        app.close()
