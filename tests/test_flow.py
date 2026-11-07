import unittest
from threading import Barrier, Event, Lock
from unittest.mock import Mock

from cardtable import Btn, Card, Dealer, TimerTrigger, TriggerEvent
from cardtable.core.closure import Closure
from cardtable.data_classes.trigger_message import TriggerMessage
from cardtable.triggers._trigger import Trigger


class DummyTrigger(Trigger):
    def start(self):
        pass

    def watching_loop(self):
        pass

    def stop(self):
        self._stop_event.set()
        self.is_stopped = True


class FlowBindingTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_callback_can_wait_for_shutdown_request(self):
        entered, exited = Event(), Event()

        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                entered.set()
                if self.wait_for_close(2):
                    exited.set()

        app = App()
        self.assertFalse(app.is_closing())
        self.assertFalse(app.wait_for_close(0))
        with self.assertRaises(ValueError):
            app.wait_for_close(-1)
        app.trigger._set_event(TriggerMessage(0, None))
        app._dispatch_messages()
        self.assertTrue(entered.wait(1))
        app.close()
        self.assertTrue(exited.is_set())
        self.assertTrue(app.is_closing())

    def test_trigger_callback_is_registered_after_setup(self):
        class App(Dealer):
            def setup(self):
                self.close_trigger = DummyTrigger(callback=self.close_app)

            def close_app(self, event: TriggerEvent):
                pass

        app = App()

        callbacks = app.trigger_callbacks[app.close_trigger]
        self.assertEqual(len(callbacks), 1)
        self.assertIs(callbacks[0].__self__, app)
        self.assertIs(callbacks[0].__func__, App.close_app)

    def test_button_callback_is_bound_by_flow_after_setup(self):
        class App(Dealer):
            def setup(self):
                with Card(0, 0, 4, 4, "Preview", runtime=Mock()) as self.image:
                    self.capture_button = Btn("Capture", self.capture)

            def capture(self, event: TriggerEvent):
                pass

        app = App()

        self.assertEqual(
            app.trigger_callbacks[app.capture_button._control], [app.capture]
        )

    def test_button_completion_is_sent_even_when_callback_fails(self):
        runtime = Mock()

        class App(Dealer):
            def setup(self):
                with Card(0, 0, 4, 4, "Preview", runtime=runtime) as self.card:
                    self.button = Btn("Run", self.callback)

            def callback(self, event: TriggerEvent):
                raise ValueError("failed")

        app = App()
        app.card.start()
        app.button._control._press()
        app.wait_for_idle(timeout=1)
        runtime.button_finished.assert_called_once_with(app.card.widget_id, app.button.id)
        app.close()

    def test_one_callback_can_be_bound_to_multiple_triggers(self):
        received_messages = []

        class App(Dealer):
            def setup(self):
                self.first_trigger = DummyTrigger(callback=self.callback)
                self.second_trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                received_messages.append(self.current_event.data)

        app = App()

        self.assertEqual(app.trigger_callbacks[app.first_trigger], [app.callback])
        self.assertEqual(app.trigger_callbacks[app.second_trigger], [app.callback])

        app.first_trigger._set_event(TriggerMessage(0, "first"))
        app.wait_for_idle(timeout=1.0)
        app.second_trigger._set_event(TriggerMessage(0, "second"))
        app.wait_for_idle(timeout=1.0)

        self.assertEqual(received_messages, ["first", "second"])

    def test_trigger_callback_can_be_inherited(self):
        class BaseApp(Dealer):
            def callback(self, event: TriggerEvent):
                pass

        class App(BaseApp):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.callback)

        app = App()

        self.assertEqual(app.trigger_callbacks[app.trigger], [app.callback])

    def test_components_are_started_and_ready_before_triggers(self):
        events = []

        class Component:
            def __init__(self):
                Closure.add(self)

            def start(self):
                events.append("component started")

            def wait_ready(self):
                events.append("component ready")

            def stop(self):
                events.append("component stopped")

        class ImmediateTrigger(DummyTrigger):
            def start(self):
                events.append("trigger started")
                self._set_event(TriggerMessage(0, "ready"))

        class App(Dealer):
            def setup(self):
                self.component = Component()
                self.trigger = ImmediateTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                events.append("callback")
                self.close()

        App().start()

        self.assertEqual(
            events[:4],
            [
                "component started",
                "component ready",
                "trigger started",
                "callback",
            ],
        )
        self.assertIn("component stopped", events)

    def test_callback_errors_are_logged_without_stopping_dispatch(self):
        calls = []

        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.failing_callback)
                self.following = DummyTrigger(callback=self.following_callback)
                self.failing = DummyTrigger(callback=self.another_failing_callback)

            def failing_callback(self, event: TriggerEvent):
                calls.append("failing callback")
                raise ValueError("callback failed")

            def following_callback(self, event: TriggerEvent):
                calls.append("following callback")

            def another_failing_callback(self, event: TriggerEvent):
                calls.append("another failing callback")
                raise RuntimeError("another callback failed")

        app = App()
        with self.assertLogs("cardtable.core.dealer", level="ERROR") as captured:
            for trigger in (app.trigger, app.following, app.failing):
                trigger._set_event(TriggerMessage(0, "message"))
                app.wait_for_idle(timeout=1.0)

        self.assertEqual(
            calls,
            ["failing callback", "following callback", "another failing callback"],
        )
        self.assertEqual(len(captured.records), 2)
        log_messages = captured.output
        self.assertIn("failing_callback", log_messages[0])
        self.assertIn("callback failed", log_messages[0])
        self.assertIn("another_failing_callback", log_messages[1])
        self.assertIn("another callback failed", log_messages[1])

    def test_trigger_drops_new_messages_while_callback_is_running_by_default(self):
        calls = []

        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                calls.append(self.current_event.data)
                self.trigger._set_event(TriggerMessage(1, "dropped"))

        app = App()
        app.trigger._set_event(TriggerMessage(0, "first"))

        app.wait_for_idle(timeout=1.0)

        self.assertEqual(calls, ["first"])

    def test_trigger_queues_messages_while_busy_when_configured(self):
        calls = []

        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(
                    callback=self.callback, drop_if_busy=False, q_size=2
                )

            def callback(self, event: TriggerEvent):
                calls.append(self.current_event.data)
                if self.current_event.data == "first":
                    self.trigger._set_event(TriggerMessage(1, "second"))
                    self.trigger._set_event(TriggerMessage(2, "third"))
                    self.trigger._set_event(TriggerMessage(3, "full"))

        app = App()
        app.trigger._set_event(TriggerMessage(0, "first"))

        app.wait_for_idle(timeout=1.0)

        self.assertEqual(calls, ["first", "second", "third"])

    def test_current_event_exposes_trigger_data_and_timestamp(self):
        received = []

        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                received.append(self.current_event)

        app = App()
        app.trigger._set_event(TriggerMessage(12.5, "payload"))
        app.wait_for_idle(timeout=1.0)

        self.assertIs(received[0].trigger, app.trigger)
        self.assertEqual(received[0].timestamp, 12.5)
        self.assertEqual(received[0].data, "payload")
        with self.assertRaisesRegex(RuntimeError, "only available"):
            _ = app.current_event

    def test_different_triggers_run_concurrently_with_isolated_events(self):
        barrier = Barrier(2)
        received = []
        received_lock = Lock()

        class App(Dealer):
            def setup(self):
                self.first = DummyTrigger(callback=self.handle_first)
                self.second = DummyTrigger(callback=self.handle_second)

            def handle_first(self, event: TriggerEvent):
                before = self.current_event
                barrier.wait(timeout=1.0)
                after = self.current_event
                with received_lock:
                    received.append((before.data, after.data))

            def handle_second(self, event: TriggerEvent):
                before = self.current_event
                barrier.wait(timeout=1.0)
                after = self.current_event
                with received_lock:
                    received.append((before.data, after.data))

        app = App(callback_workers=2)
        app.first._set_event(TriggerMessage(0, "first"))
        app.second._set_event(TriggerMessage(0, "second"))

        app.wait_for_idle(timeout=1.0)

        self.assertCountEqual(
            received,
            [("first", "first"), ("second", "second")],
        )

    def test_slow_callback_does_not_block_another_trigger(self):
        slow_started = Event()
        release_slow = Event()
        fast_finished = Event()

        class App(Dealer):
            def setup(self):
                self.slow = DummyTrigger(callback=self.handle_slow)
                self.fast = DummyTrigger(callback=self.handle_fast)

            def handle_slow(self, event: TriggerEvent):
                slow_started.set()
                release_slow.wait(timeout=1.0)

            def handle_fast(self, event: TriggerEvent):
                fast_finished.set()

        app = App(callback_workers=2)
        app.slow._set_event(TriggerMessage(0, "slow"))
        app._dispatch_messages()
        self.assertTrue(slow_started.wait(timeout=1.0))

        app.fast._set_event(TriggerMessage(0, "fast"))
        app._dispatch_messages()

        try:
            self.assertTrue(fast_finished.wait(timeout=1.0))
        finally:
            release_slow.set()
            app.wait_for_idle(timeout=1.0)

    def test_one_callback_bound_to_multiple_triggers_never_overlaps(self):
        first_started = Event()
        release_first = Event()
        state_lock = Lock()
        active = 0
        maximum_active = 0
        calls = 0

        class App(Dealer):
            def setup(self):
                self.first = DummyTrigger(callback=self.shared)
                self.second = DummyTrigger(callback=self.shared)

            def shared(self, event: TriggerEvent):
                nonlocal active, maximum_active, calls
                with state_lock:
                    active += 1
                    calls += 1
                    maximum_active = max(maximum_active, active)
                    current_call = calls
                if current_call == 1:
                    first_started.set()
                    release_first.wait(timeout=1.0)
                with state_lock:
                    active -= 1

        app = App(callback_workers=2)
        app.first._set_event(TriggerMessage(0, "first"))
        app.second._set_event(TriggerMessage(0, "second"))
        app._dispatch_messages()
        self.assertTrue(first_started.wait(timeout=1.0))
        self.assertEqual(maximum_active, 1)

        release_first.set()
        app.wait_for_idle(timeout=1.0)

        self.assertEqual(calls, 2)
        self.assertEqual(maximum_active, 1)

    def test_trigger_callback_with_two_arguments_is_rejected(self):
        class App(Dealer):
            def setup(self):
                self.trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent, extra):
                pass

        with self.assertRaisesRegex(TypeError, "one positional"):
            App()

    def test_trigger_queue_options_are_validated(self):
        with self.assertRaises(TypeError):
            DummyTrigger(drop_if_busy=1)
        with self.assertRaises(ValueError):
            DummyTrigger(drop_if_busy=False, q_size=0)

    def test_trigger_callback_must_be_callable(self):
        for construct in (DummyTrigger, lambda **kw: TimerTrigger(10, **kw)):
            with self.subTest(trigger=construct):
                with self.assertRaisesRegex(TypeError, "callback"):
                    construct(callback="not callable")

    def test_timer_callback_receives_event_without_retained_reference(self):
        received = []

        class App(Dealer):
            def setup(self):
                TimerTrigger(1, callback=self.tick)

            def tick(self, event: TriggerEvent):
                received.append(event)
                self.close()

        app = App()
        app.start()

        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0].trigger, TimerTrigger)
        self.assertEqual(received[0].data, {"interval_ms": 1})
        self.assertTrue(received[0].trigger.is_stopped)

    def test_binding_and_loop_apis_are_removed(self):
        import cardtable
        from cardtable.core import dealer

        for api in (cardtable, dealer):
            self.assertFalse(hasattr(api, "bind"))
            self.assertFalse(hasattr(api, "loop"))
        self.assertFalse(hasattr(Dealer, "bind"))

    def test_component_can_request_flow_close(self):
        class Component:
            def __init__(self):
                self.close_handler = None
                self.stopped = False
                Closure.add(self)

            def _set_close_handler(self, handler):
                self.close_handler = handler

            def stop(self):
                self.stopped = True

        class App(Dealer):
            def setup(self):
                self.component = Component()

        app = App()

        app.component.close_handler()

        self.assertTrue(app._stop_event.is_set())
        self.assertTrue(app.component.stopped)

    def test_timer_trigger_runs_and_stops_with_flow(self):
        calls = []

        class App(Dealer):
            def setup(self):
                self.timer = TimerTrigger(10, callback=self.repeatedly)

            def repeatedly(self, event: TriggerEvent):
                calls.append("called")
                self.close()

        app = App()
        timer_triggers = [
            trigger
            for trigger in app.trigger_callbacks
            if type(trigger).__name__ == "TimerTrigger"
        ]

        self.assertEqual(len(timer_triggers), 1)
        self.assertEqual(timer_triggers[0].interval_ms, 10)
        app.start()
        self.assertEqual(calls, ["called"])
        self.assertTrue(timer_triggers[0].is_stopped)


if __name__ == "__main__":
    unittest.main()
