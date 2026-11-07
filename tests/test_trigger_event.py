from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from functools import partial
from unittest.mock import Mock
from uuid import UUID

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.widgets.elements.button import _BtnPressed


class TriggerEventTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_queued_identity_payload_and_source_survive_dispatch(self):
        received = []

        class App(c.Dealer):
            def setup(self):
                self.first = c.TimerTrigger(1000, self.callback, drop_if_busy=False)
                self.second = c.TimerTrigger(1000, self.callback)

            def callback(self, event: c.TriggerEvent):
                received.append(event)
                self.assert_current = event is self.current_event

        app = App()
        payload = {"old_value": 1, "new_value": 2}
        messages = [
            c.TriggerMessage(12.5, data=payload),
            c.TriggerMessage(13.5),
            c.TriggerMessage(14.5, "another source"),
        ]
        app.first._set_event(messages[0])
        app.first._set_event(messages[1])
        app.second._set_event(messages[2])
        app.wait_for_idle(timeout=1)

        by_id = {event.event_id: event for event in received}
        self.assertEqual(set(by_id), {message.event_id for message in messages})
        first = by_id[messages[0].event_id]
        self.assertIs(first.trigger, app.first)
        self.assertEqual(first.trigger_id, app.first.id)
        self.assertEqual(first.timestamp, 12.5)
        self.assertIs(first.data, payload)
        self.assertFalse(hasattr(first, "message"))
        self.assertFalse(hasattr(messages[0], "message"))
        self.assertIsNone(by_id[messages[1].event_id].data)
        self.assertEqual(by_id[messages[1].event_id].trigger_id, first.trigger_id)
        self.assertNotEqual(by_id[messages[2].event_id].trigger_id, first.trigger_id)
        self.assertTrue(app.assert_current)
        for value in [*by_id, app.first.id, app.second.id]:
            self.assertEqual(UUID(value).version, 4)
        with self.assertRaises(FrozenInstanceError):
            first.event_id = "changed"
        with self.assertRaises(FrozenInstanceError):
            first.trigger_id = "changed"
        with self.assertRaises(AttributeError):
            app.first.id = "changed"
        original_id = app.first.id
        app.first.start()
        app.first.stop()
        self.assertEqual(app.first.id, original_id)
        app.close()

    def test_texts_and_images_survive_dispatch_and_defaults_are_independent(self):
        received = []

        class App(c.Dealer):
            def setup(self):
                self.timer = c.TimerTrigger(1000, self.callback, drop_if_busy=False)

            def callback(self, event: c.TriggerEvent):
                received.append(event)

        app = App()
        texts, images = {"prompt": "hello"}, {"image": object()}
        message = c.TriggerMessage(0, texts=texts, images=images)
        app.timer._set_event(message)
        app.timer._set_event(c.TriggerMessage(1))
        app.timer._set_event(c.TriggerMessage(2))
        app.wait_for_idle(timeout=1)
        self.assertIs(received[0].texts, texts)
        self.assertIs(received[0].images, images)
        self.assertEqual(received[1].texts, {})
        self.assertEqual(received[1].images, {})
        self.assertIsNot(received[1].texts, received[2].texts)
        self.assertIsNot(received[1].images, received[2].images)
        self.assertIsNot(c.TriggerMessage(0).texts, c.TriggerMessage(0).texts)
        self.assertIsNot(c.TriggerMessage(0).images, c.TriggerMessage(0).images)
        with self.assertRaises(FrozenInstanceError):
            received[0].texts = {}
        app.close()

    def test_response_forwards_internal_identity_and_payload(self):
        trigger = Mock(id="source")
        event = c.TriggerEvent(trigger=trigger, timestamp=0)
        texts, images = {"answer": "hello"}, {"image": object()}
        event.response(texts=texts, images=images)
        trigger._respond.assert_called_once_with(
            event.event_id, texts, images, image_format="jpg"
        )
        trigger._respond.reset_mock()
        event.response(texts, images, image_format="png")
        trigger._respond.assert_called_once_with(
            event.event_id, texts, images, image_format="png"
        )

    def test_response_on_source_without_response_support_fails(self):
        trigger = c.TimerTrigger(1000)
        event = c.TriggerEvent(trigger=trigger, timestamp=0)
        with self.assertRaisesRegex(NotImplementedError, "does not support responses"):
            event.response({}, {})

    def test_all_callbacks_for_one_occurrence_receive_the_same_event(self):
        received = []

        def first(event: c.TriggerEvent):
            received.append(event)

        def second(event: c.TriggerEvent):
            received.append(event)

        class App(c.Dealer):
            def setup(self):
                self.timer = c.TimerTrigger(1000, first)

        app = App()
        app._register_callback(app.timer, second)
        app.timer._set_event(c.TriggerMessage(0, "test"))
        app.wait_for_idle(timeout=1)
        self.assertEqual(len(received), 2)
        self.assertIs(received[0], received[1])
        app.close()

    def test_button_event_identifies_original_button_and_each_press(self):
        received = []

        class App(c.Dealer):
            def setup(self):
                with c.Card(0, 0, 4, 4, "Buttons", runtime=Mock()) as self.card:
                    self.first = c.Button("Same label", self.callback)
                    self.second = c.Button("Same label", self.callback)

            def callback(self, event: c.TriggerEvent):
                received.append(event)

        app = App()
        for button in (app.first, app.first, app.second):
            app.card._receive_input(_BtnPressed(button.id))
            app.wait_for_idle(timeout=1)
        self.assertEqual(len(received), 3)
        for event, button in zip(received, (app.first, app.first, app.second)):
            self.assertIsInstance(event.trigger, c.ButtonControl)
            self.assertIs(event.trigger.button, button)
            self.assertEqual(event.trigger_id, button._control.id)
            self.assertEqual(event.data, {"button_id": button.id})
        self.assertEqual(received[0].trigger_id, received[1].trigger_id)
        self.assertNotEqual(received[0].trigger_id, received[2].trigger_id)
        self.assertEqual(len({event.event_id for event in received}), 3)
        app.close()


class TriggerCallbackContractTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_invalid_signatures_and_annotations_are_rejected_for_all_sources(self):
        def unannotated(event):
            pass

        def wrong_type(event: str):
            pass

        def extra(event: c.TriggerEvent, other=None):
            pass

        def keyword_only(*, event: c.TriggerEvent):
            pass

        def variadic(*event: c.TriggerEvent):
            pass

        def unresolved(event: UnknownEvent):  # noqa: F821
            pass

        async def asynchronous(event: c.TriggerEvent):
            pass

        async def asynchronous_no_arguments():
            pass

        factories = (
            lambda callback: c.TimerTrigger(1000, callback),
            lambda callback: c.KeyTrigger("<ctrl>+k", callback),
            lambda callback: c.Button("Run", callback),
        )
        for factory in factories:
            for callback in (
                unannotated, wrong_type, extra, keyword_only,
                variadic, unresolved, asynchronous, asynchronous_no_arguments,
            ):
                with self.subTest(factory=factory, callback=callback):
                    with self.assertRaisesRegex(TypeError, "trigger callback"):
                        factory(callback)

    def test_functions_methods_callable_objects_and_partials_receive_events(self):
        received = []

        def function(event: c.TriggerEvent, /):
            received.append(event)

        class Handler:
            def method(self, event: c.TriggerEvent):
                received.append(event)

            def __call__(self, event: c.TriggerEvent):
                received.append(event)

        def with_context(context, event: c.TriggerEvent):
            self.assertEqual(context, "context")
            received.append(event)

        handler = Handler()
        callbacks = [
            function, handler.method, handler, partial(with_context, "context")
        ]

        class App(c.Dealer):
            def setup(self):
                self.timers = [c.TimerTrigger(1000, callback) for callback in callbacks]

        app = App()
        for timer in app.timers:
            timer._set_event(c.TriggerMessage(0, "test"))
        app.wait_for_idle(timeout=1)
        self.assertCountEqual([event.trigger for event in received], app.timers)
        app.close()

    def test_flow_revalidates_callbacks_changed_during_setup(self):
        class App(c.Dealer):
            def setup(self):
                self.timer = c.TimerTrigger(1000)
                self.timer.callback = lambda event: None

        with self.assertRaisesRegex(TypeError, "event: TriggerEvent"):
            App()

    def test_no_argument_callback_receives_current_event(self):
        received = []

        class App(c.Dealer):
            def setup(self):
                self.timer = c.TimerTrigger(1000, self.callback)

            def callback(self):
                received.append(self.current_event)

        app = App()
        app.timer._set_event(c.TriggerMessage(0, "test"))
        app.wait_for_idle(timeout=1)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0].trigger, app.timer)
        app.close()


if __name__ == "__main__":
    unittest.main()
