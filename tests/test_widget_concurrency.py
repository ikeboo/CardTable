"""Regression tests for controller locking and UI event ordering."""

import pickle
import subprocess
import sys
import unittest
from copy import copy
from queue import Empty, Queue
from threading import Barrier, Event, RLock, Thread, current_thread
from unittest.mock import Mock

from test_widgets import AliveProcess, FakeRuntime

from cardtable import LED, Btn, Card, Entry, Label, Text
from cardtable.core.closure import Closure
from cardtable.widgets._runtime import CardRuntime


class WidgetConcurrencyTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def spawn(self, function, *, name=None):
        errors = []

        def run():
            try:
                function()
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=run, name=name, daemon=True)
        thread.start()
        return thread, errors

    def join(self, *workers):
        for thread, errors in workers:
            thread.join(3)
            self.assertFalse(thread.is_alive(), "controller operation deadlocked")
            self.assertEqual(errors, [])

    def runtime(self):
        runtime = CardRuntime()
        runtime._process = AliveProcess()
        runtime._command_queue = Queue()
        runtime._event_queue = Queue()
        runtime._shutdown_process = Mock()
        return runtime

    def put_input(self, runtime, card, entry, value, *, attachment=None):
        runtime._event_queue.put(
            {
                "type": "input",
                "widget_id": card.widget_id,
                "attachment_id": attachment or runtime._attachments[card.widget_id],
                "payload": {entry.name: value},
            }
        )

    def test_validation_get_reset_and_set_are_exclusive_before_and_after_binding(self):
        for bound in (False, True):
            for operation in ("get", "reset", "set"):
                with self.subTest(bound=bound, operation=operation):
                    entered, release, attempted, finished = (Event() for _ in range(4))

                    class BlockingEntry(Entry):
                        def normalize(self, value):
                            if value == "first":
                                entered.set()
                                if not release.wait(2):
                                    raise TimeoutError(
                                        "test validation was not released"
                                    )
                            return super().normalize(value)

                    if bound:
                        with Card(0, 0, 4, 4, "Test", runtime=FakeRuntime()):
                            entry = BlockingEntry()
                    else:
                        entry = BlockingEntry()
                    first = self.spawn(lambda: entry.set("first"))
                    self.assertTrue(entered.wait(1))

                    def second_call():
                        attempted.set()
                        if operation == "set":
                            entry.set("second")
                        else:
                            getattr(entry, operation)()
                        finished.set()

                    second = self.spawn(second_call)
                    try:
                        self.assertTrue(attempted.wait(1))
                        completed_early = finished.wait(0.05)
                    finally:
                        release.set()
                    self.join(first, second)
                    self.assertFalse(
                        completed_early, "operation bypassed validation lock"
                    )
                    self.assertEqual(
                        entry.get(),
                        {"get": "first", "reset": "", "set": "second"}[operation],
                    )

    def test_slow_element_does_not_block_siblings(self):
        for phase in ("normalize", "display_value", "input"):
            with self.subTest(phase=phase):
                entered, release, finished = Event(), Event(), Event()

                class SlowEntry(Entry):
                    def wait(self, value, stage):
                        if value == "slow" and stage == phase:
                            entered.set()
                            if not release.wait(2):
                                raise TimeoutError("slow element was not released")

                    def normalize(self, value):
                        self.wait(value, "input" if phase == "input" else "normalize")
                        return super().normalize(value)

                    def display_value(self, value):
                        self.wait(value, "display_value")
                        return value

                runtime = self.runtime()
                with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
                    slow = SlowEntry()
                    entry = Entry()
                    led = LED("red")
                card.start()
                if phase == "input":
                    self.put_input(runtime, card, slow, "slow")
                    worker = self.spawn(runtime.poll)
                else:
                    worker = self.spawn(lambda: slow.set("slow"))
                self.assertTrue(entered.wait(1))

                def use_siblings():
                    led.set(True)
                    self.assertTrue(led.get())
                    entry.set("typing")
                    self.assertEqual(entry.get(), "typing")
                    entry.disable()
                    entry.enable()
                    finished.set()

                sibling = self.spawn(use_siblings)
                try:
                    completed = finished.wait(0.5)
                finally:
                    release.set()
                self.join(worker, sibling)
                self.assertTrue(completed, "another element blocked sibling operations")
                card.stop()

    def test_led_update_preserves_unreported_entry_edit(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry()
            led = LED("red")
        card.start()
        # The UI is already ahead of the controller while input is in transit.
        ui_entry, ui_led = copy(entry), copy(led)
        ui_entry.update_ui = Mock()
        ui_led.update_ui = Mock()
        ui = object.__new__(Card)
        ui._ui_elements = {entry.name: ui_entry, led.name: ui_led}
        led.set(True)
        payload = runtime.updates[-1][1]
        self.assertEqual(payload, {led.name: {"value": True, "color": "red"}})
        ui._update_ui(payload)
        ui_entry.update_ui.assert_not_called()
        ui_led.update_ui.assert_called_once_with({"value": True, "color": "red"})

    def test_pending_updates_merge_latest_value_for_each_element(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            first, second = Entry(), Entry()
            led = LED("red")
        card.start()
        runtime._command_queue.get_nowait()  # create
        runtime._command_queue.get_nowait()  # initial values, awaiting ack
        first.set("old")
        second.set("keep")
        first.set("latest")
        led.set(True, color="blue")
        runtime._event_queue.put(
            {
                "type": "update_done",
                "widget_id": card.widget_id,
                "attachment_id": runtime._attachments[card.widget_id],
            }
        )
        runtime.poll()
        self.assertEqual(
            runtime._command_queue.get_nowait()["payload"],
            {
                first.name: "latest",
                second.name: "keep",
                led.name: {"value": True, "color": "blue"},
            },
        )
        # A restart still needs every current value, including user edits.
        card._receive_input({second.name: "edited"})
        card.stop()
        card.start()
        self.assertEqual(
            card._latest_payload,
            {
                first.name: "latest",
                second.name: "edited",
                led.name: {"value": True, "color": "blue"},
            },
        )

    def test_binding_waits_for_an_in_progress_unbound_operation(self):
        entered, release, attempted, bound = (Event() for _ in range(4))

        class BlockingEntry(Entry):
            def normalize(self, value):
                entered.set()
                if not release.wait(2):
                    raise TimeoutError("test validation was not released")
                return super().normalize(value)

        entry = BlockingEntry()
        original_lock, original_name = entry._lock, entry.name
        card = Card(0, 0, 4, 4, "Test", runtime=FakeRuntime())
        writer = self.spawn(lambda: entry.set("value"))
        self.assertTrue(entered.wait(1))

        def bind():
            attempted.set()
            card.add_element(entry)
            bound.set()

        binder = self.spawn(bind)
        try:
            self.assertTrue(attempted.wait(1))
            bound_early = bound.wait(0.05)
        finally:
            release.set()
        self.join(writer, binder)
        self.assertFalse(bound_early)
        self.assertIs(entry._lock, original_lock)
        self.assertEqual(entry.name, original_name)
        self.assertEqual(entry.get(), "value")

    def test_text_polls_before_taking_card_lock(self):
        for operation in (lambda text: text.set("updated"), lambda text: text.reset()):
            runtime = FakeRuntime()
            with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
                text = Text()
            card.start()
            concurrent_operations = []
            lock_was_free = []

            def poll():
                finished = Event()
                worker = self.spawn(lambda: (card.hide(), finished.set()))
                concurrent_operations.append(worker)
                lock_was_free.append(finished.wait(0.5))

            runtime.poll = poll
            operation(text)
            self.join(*concurrent_operations)
            self.assertEqual(lock_was_free, [True])

    def test_concurrent_pollers_deliver_in_transport_order(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry()
        card.start()
        received = []
        entry.on_input = lambda event: received.append(event.value)
        entered, release = Event(), Event()

        class GatedLock:
            def __init__(self):
                self.lock = RLock()

            def acquire(self, *, blocking=True):
                if current_thread().name == "first-poller":
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("test poller was not released")
                return self.lock.acquire(blocking=blocking)

            def release(self):
                self.lock.release()

        runtime._delivery_lock = GatedLock()
        self.put_input(runtime, card, entry, "first")
        first = self.spawn(runtime.poll, name="first-poller")
        self.assertTrue(entered.wait(1))
        self.put_input(runtime, card, entry, "second")
        second = self.spawn(runtime.poll)
        try:
            self.join(second)
        finally:
            release.set()
        self.join(first)
        self.assertEqual(received, ["first", "second"])
        self.assertEqual(entry.get(), "second")

    def test_reentrant_poll_does_not_overtake_already_dequeued_events(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry()
        card.start()
        received = []

        def callback(event):
            received.append(event.value)
            if event.value == "first":
                self.put_input(runtime, card, entry, "third")
                entry.get()

        entry.on_input = callback
        self.put_input(runtime, card, entry, "first")
        self.put_input(runtime, card, entry, "second")
        runtime.poll()
        self.assertEqual(received, ["first", "second", "third"])
        self.assertEqual(entry.get(), "third")

    def test_input_callback_exception_does_not_interrupt_delivery(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry()
            other = Entry()
        card.start()
        received = []

        def fail(event):
            raise ValueError("bad input callback")

        entry.on_input = fail
        other.on_input = lambda event: received.append(event.value)
        self.put_input(runtime, card, entry, "first")
        self.put_input(runtime, card, other, "second")
        with self.assertLogs(
            "cardtable.widgets.elements._input", level="ERROR"
        ) as logs:
            runtime.poll()
        self.assertEqual(received, ["second"])
        self.assertEqual(entry.get(), "first")
        self.assertEqual(other.get(), "second")
        self.assertEqual(len(logs.records), 1)
        self.assertIsInstance(logs.records[0].exc_info[1], ValueError)

    def test_restart_discards_old_deliveries_and_late_transport_events(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry()
        card.start()
        old_attachment = runtime._attachments[card.widget_id]
        received = []

        def callback(event):
            received.append(event.value)
            if event.value == "restart":
                card.stop()
                card.start()
                self.put_input(runtime, card, entry, "late", attachment=old_attachment)
                self.put_input(runtime, card, entry, "fresh")
                for event_type in ("error", "ready", "update_done", "geometry"):
                    runtime._event_queue.put(
                        {
                            "type": event_type,
                            "widget_id": card.widget_id,
                            "attachment_id": old_attachment,
                            "message": "stale error",
                            "geometry": (1, 1, 3, 3),
                        }
                    )

        entry.on_input = callback
        self.put_input(runtime, card, entry, "restart")
        self.put_input(runtime, card, entry, "already dequeued")
        runtime.poll()
        runtime.poll()
        self.assertEqual(received, ["restart", "fresh"])
        self.assertEqual(entry.get(), "fresh")
        self.assertEqual(card.geometry, (0, 0, 4, 4))
        self.assertFalse(runtime._ready[card.widget_id].is_set())
        self.assertIn(card.widget_id, runtime._updates_in_flight)

    def test_shutdown_does_not_wait_for_a_dead_consumers_full_pipe(self):
        # A separate interpreter also checks multiprocessing's exit finalizers.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import multiprocessing
from cardtable.widgets._runtime import CardRuntime
runtime = CardRuntime()
runtime._command_queue = multiprocessing.get_context("spawn").Queue()
runtime._command_queue.put(bytes(2 * 1024 * 1024))
runtime._shutdown_process()
print("stopped")
""",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "stopped")

    def test_stop_cancels_wait_ready(self):
        runtime = self.runtime()
        card = Card(0, 0, 4, 4, "Test", runtime=runtime)
        card.start()
        entered, release = Event(), Event()

        def poll():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test waiter was not released")

        runtime.poll = poll
        waiter = self.spawn(card.wait_ready)
        try:
            self.assertTrue(entered.wait(1))
            card.stop()
        finally:
            release.set()
        self.join(waiter)

    def test_create_command_keeps_an_independent_state_snapshot(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            entry = Entry(label="Original")
        card.start()
        create = runtime._command_queue.get_nowait()
        entry.disable(label="Changed")
        self.assertEqual(
            create["options"]["element_states"][entry.name],
            {"state": "normal", "label": "Original"},
        )
        self.assertEqual(create["attachment_id"], runtime._attachments[card.widget_id])
        pickle.dumps(create)

    def test_copies_have_independent_locks_and_no_owner(self):
        with Card(0, 0, 4, 4, "Test", runtime=FakeRuntime()):
            elements = (Entry(), Text(), Label("Initial"), LED("red"))
        for element in elements:
            for restored in (copy(element), pickle.loads(pickle.dumps(element))):
                self.assertIsNot(restored._lock, element._lock)
                self.assertIsNone(restored._owner)
                self.assertEqual(restored.name, element.name)
                self.assertEqual(restored.get(), element.get())

    def test_element_and_button_cannot_be_bound_to_two_cards(self):
        for element in (Entry(), Btn("Run")):
            first = Card(0, 0, 4, 4, "First", runtime=FakeRuntime())
            second = Card(0, 0, 4, 4, "Second", runtime=FakeRuntime())
            barrier = Barrier(2)
            results = Queue()

            def bind(card):
                barrier.wait(1)
                try:
                    if isinstance(element, Btn):
                        card._add_button(element)
                    else:
                        card.add_element(element)
                except ValueError:
                    results.put(False)
                else:
                    results.put(True)

            workers = [
                self.spawn(lambda card=card: bind(card)) for card in (first, second)
            ]
            self.join(*workers)
            self.assertEqual(
                sorted((results.get_nowait(), results.get_nowait())), [False, True]
            )

    def test_updates_reads_and_lifecycle_can_race_on_one_card(self):
        runtime = self.runtime()
        with Card(0, 0, 4, 4, "Test", runtime=runtime) as card:
            text = Text()
            entry = Entry()
            label = Label("Initial")
            led = LED("red")
            button = Btn("Run")
        barrier = Barrier(5)

        def repeat(operation):
            barrier.wait(2)
            for _ in range(30):
                operation()

        operations = (
            lambda: (card.start(), card.show(), card.hide(), card.stop()),
            lambda: (text.set({"ok": True}), text.get(), text.reset()),
            lambda: (
                entry.set("value"),
                entry.get(),
                entry.reset(),
                entry.disable(),
                entry.enable(),
            ),
            lambda: (label.set("Changed", bg_color="blue"), label.get(), label.reset()),
            lambda: (
                led.set(True),
                led.get(),
                led.reset(),
                button.disable(),
                button.enable(),
                button.reset(),
            ),
        )
        workers = [self.spawn(lambda op=op: repeat(op)) for op in operations]
        self.join(*workers)
        self.assertEqual(card.values(), ("", "", "Initial", False, None))
        card.stop()
        active_attachment = None
        while True:
            try:
                command = runtime._command_queue.get_nowait()
            except Empty:
                break
            if command["type"] == "create":
                self.assertIsNone(active_attachment)
                active_attachment = command["attachment_id"]
            else:
                self.assertEqual(command["attachment_id"], active_attachment)
                if command["type"] == "destroy":
                    active_attachment = None
        self.assertIsNone(active_attachment)


if __name__ == "__main__":
    unittest.main()
