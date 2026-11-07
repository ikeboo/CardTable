"""Translate watchdog notifications into Dealer events."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Collection, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from threading import Condition, Lock, Thread, current_thread
from time import monotonic
from typing import cast

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.file_system_event_data import (
    FileSystemEventData,
    FileSystemEventKind,
)
from cardtable.data_classes.trigger_message import TriggerMessage

from ._trigger import Trigger

_KINDS: tuple[FileSystemEventKind, ...] = ("created", "modified", "deleted", "moved")
_logger = logging.getLogger(__name__)


def _patterns(value: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of filename patterns")
    if any(not isinstance(pattern, str) for pattern in value):
        raise TypeError(f"{name} must contain strings")
    if any(not pattern or "/" in pattern or "\\" in pattern for pattern in value):
        raise ValueError(f"{name} must contain nonempty filename patterns")
    return tuple(value)


class _Handler(FileSystemEventHandler):
    def __init__(self, trigger: FileSystemTrigger):
        self.trigger = trigger

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.trigger._receive(event)


class FileSystemTrigger(Trigger):
    """Watch one directory, optionally including its descendants.

    Patterns match basenames case-sensitively. Either endpoint of a move may
    match, independently applying scope, inclusion and exclusion rules.
    Only modifications are debounced, per path; this is not a write-completion
    guarantee. The pending debounce map and ready queue share ``q_size`` slots.
    """

    def __init__(
        self,
        path: str | Path,
        callback: TriggerCallback | None = None,
        *,
        events: Collection[FileSystemEventKind] = _KINDS,
        patterns: Sequence[str] = ("*",),
        ignore_patterns: Sequence[str] = (),
        recursive: bool = False,
        include_directories: bool = False,
        debounce_ms: float = 0,
        drop_if_busy: bool = False,
        q_size: int = 1000,
        log_level: str | int = "INFO",
    ):
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a string or Path")
        if isinstance(path, str) and not path:
            raise ValueError("path must not be empty")
        absolute_path = Path(path).resolve()
        if isinstance(events, (str, bytes)) or not isinstance(events, Collection):
            raise TypeError("events must be a collection of event kinds")
        if any(not isinstance(kind, str) for kind in events):
            raise TypeError("events must contain strings")
        if not events or any(kind not in _KINDS for kind in events):
            raise ValueError(f"events must be a nonempty subset of {_KINDS}")
        selected_patterns = _patterns(patterns, "patterns")
        ignored_patterns = _patterns(ignore_patterns, "ignore_patterns")
        for name, value in (
            ("recursive", recursive),
            ("include_directories", include_directories),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool")
        if isinstance(debounce_ms, bool) or not isinstance(debounce_ms, (int, float)):
            raise TypeError("debounce_ms must be a number")
        if not math.isfinite(debounce_ms) or debounce_ms < 0:
            raise ValueError("debounce_ms must be finite and non-negative")

        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self.path = absolute_path
        self.events = frozenset(events)
        self.patterns = selected_patterns
        self.ignore_patterns = ignored_patterns
        self.recursive = recursive
        self.include_directories = include_directories
        self.debounce_ms = debounce_ms
        self._condition = Condition()
        self._lifecycle_lock = Lock()
        self._accepting = False
        self._observer: BaseObserver | None = None
        self._watch_thread: Thread | None = None
        self._pending: dict[Path, tuple[float, TriggerMessage]] = {}

    def start(self) -> None:
        """Start watching an existing directory; repeated calls are harmless."""
        with self._lifecycle_lock:
            if self._observer is not None:
                return
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            if not self.path.is_dir():
                raise NotADirectoryError(self.path)
            self._observer = Observer()
            try:
                self._observer.schedule(
                    _Handler(self), str(self.path), recursive=self.recursive
                )
                # FSEvents can replay creation flags from before start(). Its
                # public suppression option snapshots existing inodes first.
                for emitter in self._observer.emitters:
                    if hasattr(emitter, "suppress_history"):
                        setattr(emitter, "suppress_history", True)
                with self._condition:
                    self._stop_event.clear()
                    self.is_stopped = False
                    self._accepting = True
                self._observer.start()
                if self.debounce_ms:
                    self._watch_thread = Thread(
                        target=self.watching_loop,
                        name=f"FileSystemTrigger-{self.id}",
                        daemon=True,
                    )
                    self._watch_thread.start()
            except Exception:
                self._stop_resources()
                raise

    def stop(self) -> None:
        """Stop and join monitoring threads, discarding unprocessed events."""
        with self._lifecycle_lock:
            self._stop_resources()

    def _stop_resources(self) -> None:
        with self._condition:
            self._accepting = False
            self._stop_event.set()
            self._pending.clear()
            self._condition.notify_all()
        observer = self._observer
        if observer is not None:
            observer.stop()
            if observer.ident is not None and observer is not current_thread():
                observer.join()
        worker = self._watch_thread
        if worker is not None and worker.ident is not None:
            if worker is not current_thread():
                worker.join()
        self._observer = None
        self._watch_thread = None
        self.clear_event()
        self.is_stopped = True

    def clear_event(self) -> None:
        """Discard both ready messages and pending debounced modifications."""
        with self._condition:
            self._pending.clear()
            super().clear_event()
            self._condition.notify_all()

    def _matches(self, path: Path) -> bool:
        if not path.is_relative_to(self.path):
            return False
        if not self.recursive and path != self.path and path.parent != self.path:
            return False
        return any(
            fnmatchcase(path.name, pattern) for pattern in self.patterns
        ) and not any(
            fnmatchcase(path.name, pattern) for pattern in self.ignore_patterns
        )

    def _has_capacity(self) -> bool:
        with self._message_lock:
            return len(self._message_queue) + len(self._pending) < self.q_size

    def _warn_dropped(self) -> None:
        _logger.warning(
            "FileSystemTrigger %s (%s): event dropped (busy or queue full)",
            self.id,
            self.path,
        )

    def _publish(self, message: TriggerMessage) -> None:
        if not self._has_capacity() or not self._set_event(message):
            self._warn_dropped()

    def _flush_related(self, data: FileSystemEventData) -> None:
        # Do not let a delayed modification arrive after a deletion or move.
        endpoints = [data["path"]]
        if data["dest_path"] is not None:
            endpoints.append(data["dest_path"])
        for path in list(self._pending):
            if any(
                path == endpoint
                or (data["is_directory"] and path.is_relative_to(endpoint))
                for endpoint in endpoints
            ):
                _, message = self._pending.pop(path)
                self._publish(message)

    def _receive(self, event: FileSystemEvent) -> None:
        if event.event_type not in _KINDS or not event.src_path:
            return
        path = Path(os.path.abspath(os.fsdecode(event.src_path)))
        dest_path = (
            Path(os.path.abspath(os.fsdecode(event.dest_path)))
            if event.event_type == "moved" and event.dest_path
            else None
        )
        data: FileSystemEventData = {
            "kind": cast(FileSystemEventKind, event.event_type),
            "path": path,
            "dest_path": dest_path,
            "is_directory": event.is_directory,
        }
        with self._condition:
            if not self._accepting:
                return
            if data["kind"] != "modified":
                self._flush_related(data)
            if data["kind"] not in self.events:
                return
            if data["is_directory"] and not self.include_directories:
                return
            if not self._matches(path) and not (
                dest_path is not None and self._matches(dest_path)
            ):
                return
            message = TriggerMessage(timestamp=self.get_timestamp(), data=data)
            if data["kind"] == "modified" and self.debounce_ms:
                if path not in self._pending and not self._has_capacity():
                    self._warn_dropped()
                    return
                deadline = monotonic() + self.debounce_ms / 1000
                self._pending[path] = deadline, message
                self._condition.notify_all()
            else:
                self._publish(message)

    def watching_loop(self) -> None:
        """Publish modifications after each path's quiet period elapses."""
        with self._condition:
            while not self._stop_event.is_set():
                if not self._pending:
                    self._condition.wait()
                    continue
                path = min(self._pending, key=lambda key: self._pending[key][0])
                deadline, message = self._pending[path]
                remaining = deadline - monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                del self._pending[path]
                self._publish(message)
