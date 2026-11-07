import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from functools import partial
from inspect import signature
from os import cpu_count
from threading import Condition, Event, Lock, RLock
from time import monotonic
from typing import Callable, Optional

from cardtable.data_classes.trigger_event import TriggerEvent
from cardtable.triggers._trigger import Trigger

from .closure import Closure
from .config_manager import _set_config_path
from .trigger_callback import TriggerCallback, validate_trigger_callback

_logger = logging.getLogger(__name__)


def _callback_log_name(callback: Callable) -> str:
    while isinstance(callback, partial):
        callback = callback.func
    name = getattr(callback, "__qualname__", None)
    if name is None:
        return f"{type(callback).__name__}.__call__"
    name = name.rsplit(".<locals>.", 1)[-1]
    if "." in name:
        return ".".join(name.split(".")[-2:])
    module = getattr(callback, "__module__", None)
    return f"{module.rsplit('.', 1)[-1]}.{name}" if module else name

_callback_stop_event: ContextVar[Event | None] = ContextVar(
    "cardtable_callback_stop_event", default=None
)


class Dealer(ABC):
    """Mediator to manage all objects"""

    def __init__(
        self,
        config_path: Optional[str] = None,
        *,
        callback_workers: Optional[int] = None,
    ):
        if callback_workers is None:
            callback_workers = min(32, (cpu_count() or 1) + 4)
        if isinstance(callback_workers, bool) or not isinstance(callback_workers, int):
            raise TypeError("callback_workers must be an int or None")
        if callback_workers <= 0:
            raise ValueError("callback_workers must be greater than zero")

        self.closure = Closure()
        if config_path is not None:
            _set_config_path(config_path)
        self.trigger_callbacks = defaultdict(list)
        self.callback_workers = callback_workers
        self._current_event: ContextVar[Optional[TriggerEvent]] = ContextVar(
            f"cardtable_current_event_{id(self)}", default=None
        )
        self._inside_callback: ContextVar[bool] = ContextVar(
            f"cardtable_inside_callback_{id(self)}", default=False
        )
        self._stop_event = Event()
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = RLock()
        self._callback_futures: set[Future[None]] = set()
        self._future_condition = Condition()
        self._callback_locks: dict[Callable, Lock] = {}
        self._lifecycle_lock = RLock()
        self._finalize_lock = Lock()
        self._running = False
        self._closed = False
        existing_components = {id(component) for component in self.closure.objects}
        _logger.info("%s.setup started", type(self).__name__)
        self.setup()
        _logger.info("%s.setup completed", type(self).__name__)
        self._components = [
            component
            for component in self.closure.objects
            if id(component) not in existing_components
        ]
        self._bind_close_handlers()
        self._register_trigger_callbacks()

    @abstractmethod
    def setup(self):
        pass

    def _register_callback(self, trigger: Trigger, callback: TriggerCallback) -> None:
        validate_trigger_callback(callback)
        self.trigger_callbacks[trigger].append(callback)
        self._callback_locks.setdefault(callback, Lock())

    @property
    def current_event(self) -> TriggerEvent:
        """Return the event for the trigger callback currently being run."""
        event = self._current_event.get()
        if event is None:
            raise RuntimeError(
                "current_event is only available inside a trigger callback"
            )
        return event

    def _bind_close_handlers(self) -> None:
        """Let UI-backed components request closure on the main thread."""
        for component in self._components:
            set_close_handler = getattr(component, "_set_close_handler", None)
            if set_close_handler is not None:
                set_close_handler(self.close)

    def _register_trigger_callbacks(self) -> None:
        """Register callbacks supplied to triggers created during setup."""
        for component in self._components:
            if isinstance(component, Trigger) and component.callback is not None:
                self._register_callback(component, component.callback)

    def _wait_initialization(self):
        """Wait for components backed by another process to become ready."""
        for component in self._components:
            wait_ready = getattr(component, "wait_ready", None)
            if wait_ready is not None:
                wait_ready()

    def start(self):
        """Start all components and dispatch trigger callbacks."""
        with self._lifecycle_lock:
            if self._running:
                raise RuntimeError("dealer is already running")
            if self._closed:
                raise RuntimeError("a closed dealer cannot be restarted")
            self._running = True
            self._stop_event.clear()
        self._ensure_executor()
        try:
            # All views are enqueued before waiting, allowing the one UI process
            # to initialize them together.
            for component in self._components:
                if not isinstance(component, Trigger):
                    component.start()

            self._wait_initialization()

            for trigger in self.trigger_callbacks:
                trigger.start()

            while not self._stop_event.is_set():
                self._dispatch_messages()
                self._poll_components()
                self._stop_event.wait(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_event.set()
            self._finalize()

    def _dispatch_messages(self):
        for trigger, callbacks in self.trigger_callbacks.items():
            if not trigger.message_event.is_set():
                continue

            message = trigger._take_message()
            if message is None:
                continue

            try:
                self._submit(
                    self._run_trigger_callbacks,
                    trigger,
                    tuple(callbacks),
                    message,
                )
            except RuntimeError:
                trigger._complete_message()

    def _run_trigger_callbacks(self, trigger, callbacks, message) -> None:
        event = TriggerEvent(
            trigger=trigger,
            timestamp=message.timestamp,
            data=message.data,
            event_id=message.event_id,
            texts=message.texts,
            images=message.images,
        )
        token = self._current_event.set(event)
        callback_token = self._inside_callback.set(True)
        stop_token = _callback_stop_event.set(self._stop_event)
        results = []
        errors = []
        try:
            for callback in callbacks:
                callback_name = _callback_log_name(callback)
                try:
                    with self._callback_locks[callback]:
                        _logger.log(
                            trigger.log_level,
                            "%s callback started: trigger_id=%s event_id=%s",
                            type(trigger).__name__, trigger.id, event.event_id,
                            extra={"cardtable_caller": callback_name},
                        )
                        if signature(callback).parameters:
                            results.append(callback(event))
                        else:
                            results.append(callback())
                except Exception as error:
                    errors.append(error)
                    _logger.exception(
                        "Trigger callback %s failed: trigger_id=%s event_id=%s",
                        callback_name, trigger.id, event.event_id,
                        extra={"cardtable_caller": callback_name},
                    )
        finally:
            try:
                trigger._callbacks_finished(event, tuple(results), tuple(errors))
            except Exception:
                _logger.exception("Trigger callback outcome handling failed")
            finally:
                _callback_stop_event.reset(stop_token)
                self._inside_callback.reset(callback_token)
                self._current_event.reset(token)
                trigger._complete_message()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.callback_workers,
                    thread_name_prefix=f"{type(self).__name__}-callback",
                )
            return self._executor

    def _submit(self, function: Callable, *args) -> Future[None]:
        with self._executor_lock:
            if self._closed:
                raise RuntimeError("dealer is closed")
            future = self._ensure_executor().submit(function, *args)
            with self._future_condition:
                self._callback_futures.add(future)
            future.add_done_callback(self._callback_finished)
            return future

    def _callback_finished(self, future: Future[None]) -> None:
        with self._future_condition:
            self._callback_futures.discard(future)
            self._future_condition.notify_all()

    def wait_for_idle(self, timeout: float | None = None) -> None:
        """Wait until queued trigger messages and callbacks have completed."""
        if self._inside_callback.get():
            raise RuntimeError("wait_for_idle cannot be called from a callback")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else monotonic() + timeout

        while True:
            self._dispatch_messages()
            with self._future_condition:
                pending = bool(self._callback_futures)
                queued = any(
                    trigger.message_event.is_set() for trigger in self.trigger_callbacks
                )
                if not pending and not queued:
                    return
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("dealer callbacks did not become idle in time")
                self._future_condition.wait(
                    0.01 if remaining is None else min(0.01, remaining)
                )

    def _poll_components(self):
        for component in self._components:
            poll = getattr(component, "poll", None)
            if poll is not None:
                poll()

    def on_close(self):
        """Override this method to perform cleanup when the dealer is closed."""
        pass

    def is_closing(self) -> bool:
        """Return whether shutdown has been requested."""
        return self._stop_event.is_set()

    def wait_for_close(self, timeout: float | None = None) -> bool:
        """Wait for shutdown, returning False if the timeout expires."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        return self._stop_event.wait(timeout)

    def close(self):
        """Stop this dealer and close all components created during setup."""
        self._stop_event.set()
        if self._inside_callback.get():
            return
        with self._lifecycle_lock:
            if self._running:
                return
        self._finalize()

    def _finalize(self) -> None:
        with self._finalize_lock:
            with self._lifecycle_lock:
                if self._closed:
                    self._running = False
                    return
                self._closed = True

            # Wake service operations before waiting for callbacks that may be
            # blocked in them. Resources remain available until callbacks exit.
            for component in self._components:
                request_stop = getattr(component, "request_stop", None)
                if request_stop is not None:
                    request_stop()

            triggers = [
                component
                for component in reversed(self._components)
                if isinstance(component, Trigger)
            ]
            for trigger in triggers:
                self.closure.close(trigger)

            with self._executor_lock:
                executor = self._executor
                self._executor = None
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)

            for component in reversed(self._components):
                if not isinstance(component, Trigger):
                    self.closure.close(component)
            self.on_close()
            with self._lifecycle_lock:
                self._running = False
