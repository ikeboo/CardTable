from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import Mock, patch

from watchdog.events import (
    DirCreatedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent,
)
from watchdog.observers.api import BaseObserver

import cardtable as c
from cardtable.core.closure import Closure

MODULE = "cardtable.triggers.file_system_trigger"


class FileSystemTriggerTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(Closure().close_all)

    def start_fake(self, **options):
        observer = Mock(spec=BaseObserver)
        observer.ident = None
        observer.emitters = set()
        with patch(f"{MODULE}.Observer", return_value=observer):
            trigger = c.FileSystemTrigger(self.root, **options)
            trigger.start()
        return trigger, observer

    def drain(self, trigger):
        messages = []
        while (message := trigger._take_message()) is not None:
            messages.append(message)
            trigger._complete_message()
        return messages

    def test_translates_all_kinds_and_ignores_open_and_directory_events(self):
        trigger, observer = self.start_fake()
        source, destination = self.root / "input.csv", self.root / "output.csv"
        for event in (
            FileCreatedEvent(os.fsencode(source)),
            FileModifiedEvent(str(source)),
            FileMovedEvent(str(source), str(destination)),
            FileDeletedEvent(str(destination)),
            FileOpenedEvent(str(source)),
            DirCreatedEvent(str(self.root / "folder")),
        ):
            observer.schedule.call_args.args[0].dispatch(event)
        messages = self.drain(trigger)
        self.assertEqual(
            [message.data["kind"] for message in messages],
            ["created", "modified", "moved", "deleted"],
        )
        self.assertEqual(
            messages[2].data,
            {
                "kind": "moved",
                "path": source,
                "dest_path": destination,
                "is_directory": False,
            },
        )
        self.assertIsNone(messages[0].data["dest_path"])
        self.assertEqual(len({message.event_id for message in messages}), 4)
        self.assertTrue(all(message.timestamp > 0 for message in messages))
        self.assertFalse(trigger.drop_if_busy)
        self.assertEqual(trigger.q_size, 1000)

    def test_filtering_scope_patterns_and_either_move_endpoint(self):
        trigger, _ = self.start_fake(
            events=("created", "moved"),
            patterns=("*.csv",),
            ignore_patterns=("ignore*", "*.tmp"),
        )
        paths = [
            self.root / "good.csv",
            self.root / "ignore.csv",
            self.root / "notes.txt",
            self.root / "nested" / "other.csv",
            self.root.parent / "outside.csv",
        ]
        for path in paths:
            trigger._receive(FileCreatedEvent(str(path)))
        trigger._receive(FileModifiedEvent(str(paths[0])))
        trigger._receive(
            FileMovedEvent(str(self.root / "report.tmp"), str(self.root / "report.csv"))
        )
        trigger._receive(
            FileMovedEvent(str(self.root / "report.csv"), str(self.root / "report.bak"))
        )
        trigger._receive(
            FileMovedEvent(str(self.root / "ignore.csv"), str(self.root / "notes.txt"))
        )
        trigger._receive(
            FileMovedEvent(
                str(self.root.parent / "outside.csv"), str(self.root / "arrived.csv")
            )
        )
        trigger._receive(
            FileMovedEvent(
                str(self.root / "left.csv"), str(self.root.parent / "left.csv")
            )
        )
        messages = self.drain(trigger)
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0].data["path"], paths[0])
        self.assertEqual(messages[-1].data["path"], self.root / "left.csv")

    def test_recursive_and_directory_options(self):
        trigger, observer = self.start_fake(recursive=True, include_directories=True)
        observer.schedule.assert_called_once_with(
            observer.schedule.call_args.args[0], str(self.root), recursive=True
        )
        trigger._receive(DirCreatedEvent(str(self.root / "nested")))
        trigger._receive(FileCreatedEvent(str(self.root / "nested" / "file")))
        messages = self.drain(trigger)
        self.assertEqual(len(messages), 2)
        self.assertTrue(messages[0].data["is_directory"])
        self.assertFalse(messages[1].data["is_directory"])

    def test_debounce_is_per_path_and_keeps_latest_detection_timestamp(self):
        with patch(f"{MODULE}.monotonic", return_value=10) as clock:
            trigger, _ = self.start_fake(debounce_ms=100)
            first, second = self.root / "first", self.root / "second"
            trigger._receive(FileModifiedEvent(str(first)))
            clock.return_value = 10.05
            trigger._receive(FileModifiedEvent(str(second)))
            clock.return_value = 10.08
            with patch.object(trigger, "get_timestamp", return_value=123):
                trigger._receive(FileModifiedEvent(str(first)))
            self.assertFalse(trigger.message_event.is_set())
            with trigger._condition:
                clock.return_value = 10.16
                trigger._condition.notify_all()
            self.assertTrue(trigger.message_event.wait(2))
            messages = self.drain(trigger)
            self.assertEqual([m.data["path"] for m in messages], [second])
            with trigger._condition:
                clock.return_value = 10.19
                trigger._condition.notify_all()
            self.assertTrue(trigger.message_event.wait(2))
            messages = self.drain(trigger)
            self.assertEqual([m.data["path"] for m in messages], [first])
            self.assertEqual(messages[0].timestamp, 123)
            trigger.stop()

    def test_deletion_and_directory_move_flush_related_updates_first(self):
        trigger, _ = self.start_fake(debounce_ms=60_000, recursive=True)
        file = self.root / "nested" / "file"
        trigger._receive(FileModifiedEvent(str(file)))
        trigger._receive(DirMovedEvent(str(file.parent), str(self.root / "renamed")))
        # Directory events are excluded, but the preceding file update is kept.
        self.assertEqual([m.data["kind"] for m in self.drain(trigger)], ["modified"])
        trigger._receive(FileModifiedEvent(str(file)))
        trigger._receive(FileDeletedEvent(str(file)))
        self.assertEqual(
            [m.data["kind"] for m in self.drain(trigger)], ["modified", "deleted"]
        )
        self.assertEqual(trigger._pending, {})

    def test_queue_capacity_includes_debounce_and_logs_drops(self):
        trigger, _ = self.start_fake(debounce_ms=60_000, q_size=2)
        trigger._receive(FileModifiedEvent(str(self.root / "pending")))
        trigger._receive(FileCreatedEvent(str(self.root / "ready")))
        with self.assertLogs(MODULE, level="WARNING") as logs:
            trigger._receive(FileModifiedEvent(str(self.root / "overflow1")))
            trigger._receive(FileCreatedEvent(str(self.root / "overflow2")))
        self.assertEqual(len(logs.output), 2)
        self.assertEqual(len(trigger._pending), 1)
        self.assertEqual(len(self.drain(trigger)), 1)
        trigger.clear_event()
        self.assertEqual(trigger._pending, {})
        self.assertFalse(trigger.message_event.is_set())

    def test_busy_policy_can_be_overridden(self):
        for drop_if_busy in (False, True):
            trigger, _ = self.start_fake(drop_if_busy=drop_if_busy)
            trigger._receive(FileCreatedEvent(str(self.root / "first")))
            self.assertIsNotNone(trigger._take_message())
            if drop_if_busy:
                with self.assertLogs(MODULE, level="WARNING"):
                    trigger._receive(FileCreatedEvent(str(self.root / "second")))
            else:
                trigger._receive(FileCreatedEvent(str(self.root / "second")))
            trigger._complete_message()
            self.assertEqual(len(self.drain(trigger)), 0 if drop_if_busy else 1)
            trigger.stop()

    def test_stop_clears_events_joins_worker_and_rejects_late_notifications(self):
        trigger, observer = self.start_fake(debounce_ms=60_000)
        worker = trigger._watch_thread
        trigger._receive(FileModifiedEvent(str(self.root / "pending")))
        trigger._receive(FileCreatedEvent(str(self.root / "ready")))
        trigger.stop()
        trigger.stop()
        observer.stop.assert_called_once()
        self.assertFalse(worker.is_alive())
        self.assertTrue(trigger.is_stopped)
        trigger._receive(FileCreatedEvent(str(self.root / "late")))
        self.assertFalse(trigger.message_event.is_set())
        self.assertEqual(trigger._pending, {})
        self.assertIsNone(trigger._observer)

    def test_missing_or_file_watch_root_is_rejected_at_start(self):
        missing = self.root / "not-yet-created"
        trigger = c.FileSystemTrigger(missing)
        with self.assertRaises(FileNotFoundError):
            trigger.start()
        missing.touch()
        with self.assertRaises(NotADirectoryError):
            trigger.start()

    def test_relative_root_is_fixed_at_construction(self):
        trigger = c.FileSystemTrigger("relative")
        self.assertEqual(trigger.path, Path.cwd() / "relative")

    def test_symlink_watch_root_is_canonicalized(self):
        alias = self.root / "alias"
        target = self.root / "target"
        target.mkdir()
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink creation is unavailable: {error}")
        self.assertEqual(c.FileSystemTrigger(alias).path, target)

    def test_start_failure_cleans_up_and_can_be_retried(self):
        observer = Mock(spec=BaseObserver)
        observer.ident = None
        observer.emitters = set()
        observer.start.side_effect = OSError("cannot watch")
        trigger = c.FileSystemTrigger(self.root, debounce_ms=100)
        with patch(f"{MODULE}.Observer", return_value=observer):
            with self.assertRaisesRegex(OSError, "cannot watch"):
                trigger.start()
            self.assertTrue(trigger.is_stopped)
            observer.stop.assert_called_once()
            self.assertIsNone(trigger._watch_thread)
            observer.start.side_effect = None
            trigger.start()
            self.assertFalse(trigger.is_stopped)
            trigger.stop()

    def test_schedule_failure_cleans_up_and_allows_retry(self):
        observer = Mock(spec=BaseObserver)
        observer.ident = None
        observer.emitters = set()
        observer.schedule.side_effect = OSError("cannot schedule")
        trigger = c.FileSystemTrigger(self.root)
        with patch(f"{MODULE}.Observer", return_value=observer):
            with self.assertRaisesRegex(OSError, "cannot schedule"):
                trigger.start()
            observer.start.assert_not_called()
            observer.stop.assert_called_once()
            self.assertIsNone(trigger._observer)
            self.assertTrue(trigger.is_stopped)
            observer.schedule.side_effect = None
            trigger.start()
            self.assertFalse(trigger.is_stopped)
            trigger.stop()

    def test_options_and_callback_are_validated_before_registration(self):
        baseline = Closure().objects
        for options, error in (
            ({"events": "created"}, TypeError),
            ({"events": ()}, ValueError),
            ({"events": ("opened",)}, ValueError),
            ({"patterns": "*.csv"}, TypeError),
            ({"patterns": (1,)}, TypeError),
            ({"patterns": ("dir/*.csv",)}, ValueError),
            ({"ignore_patterns": ("",)}, ValueError),
            ({"recursive": 1}, TypeError),
            ({"include_directories": 1}, TypeError),
            ({"debounce_ms": True}, TypeError),
            ({"debounce_ms": -1}, ValueError),
            ({"debounce_ms": float("nan")}, ValueError),
            ({"debounce_ms": float("inf")}, ValueError),
            ({"q_size": 0}, ValueError),
            ({"callback": lambda event: None}, TypeError),
        ):
            with self.subTest(options=options):
                with self.assertRaises(error):
                    c.FileSystemTrigger(self.root, **options)
        for path, error in ((None, TypeError), ("", ValueError)):
            with self.assertRaises(error):
                c.FileSystemTrigger(path)
        self.assertEqual(Closure().objects, baseline)

    def test_native_observer_detects_disk_changes_and_restarts(self):
        # Preexisting files are not synthesized as created notifications.
        existing = self.root / "existing.csv"
        existing.touch()
        nested = self.root / "nested"
        nested.mkdir()
        trigger = c.FileSystemTrigger(
            self.root,
            patterns=("*.csv",),
            recursive=True,
            events=("created", "modified", "deleted", "moved"),
        )
        trigger.start()
        trigger.message_event.wait(0.1)
        self.assertFalse(
            any(message.data["kind"] == "created" for message in self.drain(trigger))
        )
        observer = trigger._observer
        trigger.start()
        self.assertIs(trigger._observer, observer)

        def wait_for(kind, path):
            from time import monotonic

            deadline = monotonic() + 5
            while monotonic() < deadline:
                trigger.message_event.wait(max(0, deadline - monotonic()))
                for message in self.drain(trigger):
                    if message.data["kind"] == kind and message.data["path"] == path:
                        return
            self.fail(f"missing native {kind} event for {path}")

        created = nested / "new.csv"
        created.write_text("first")
        wait_for("created", created)
        # Changing a separate file avoids backend create/modify coalescing.
        existing.write_text("changed")
        wait_for("modified", existing)
        renamed = nested / "renamed.csv"
        created.rename(renamed)
        wait_for("moved", created)
        created = renamed
        created.unlink()
        wait_for("deleted", created)
        original_id = trigger.id
        trigger.stop()
        self.assertFalse(observer.is_alive())
        trigger.start()
        self.assertIsNot(trigger._observer, observer)
        self.assertEqual(trigger.id, original_id)
        created.touch()
        wait_for("created", created)
        trigger.stop()

    def test_flow_dispatches_typed_payload_and_stops_observer(self):
        detected = Event()
        ready = Event()
        received = []
        root = self.root

        class ReadyTrigger(c.FileSystemTrigger):
            def start(self):
                super().start()
                ready.set()

        class App(c.Dealer):
            def setup(self):
                self.files = ReadyTrigger(
                    root, self.changed, events=("created",), patterns=("*.csv",)
                )

            def changed(self, event: c.TriggerEvent):
                received.append(event)
                detected.set()
                self.close()

        app = App()
        thread = Thread(target=app.start)
        thread.start()
        try:
            self.assertTrue(ready.wait(3))
            path = root / "flow.csv"
            path.touch()
            self.assertTrue(detected.wait(5))
        finally:
            app.close()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(received), 1)
        self.assertIs(received[0].trigger, app.files)
        self.assertEqual(received[0].trigger_id, app.files.id)
        self.assertEqual(received[0].data["path"], path)
        self.assertTrue(app.files.is_stopped)


if __name__ == "__main__":
    unittest.main()
