"""Calendar-based scheduling of multiple cron expressions with croniter."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime
from threading import Lock, Thread, current_thread
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterError, croniter
from tzlocal import get_localzone

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.schedule_event_data import ScheduleEventData
from cardtable.data_classes.trigger_message import TriggerMessage

from ._trigger import Trigger

_logger = logging.getLogger(__name__)
_SEARCH_YEARS = 50
_CLOCK_CHECK_SECONDS = 1.0


def _normalize(schedules: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(schedules, str):
        schedules = (schedules,)
    if isinstance(schedules, bytes) or not isinstance(schedules, Sequence):
        raise TypeError("schedules must be a cron string or sequence of strings")
    expressions = []
    for expression in schedules:
        if not isinstance(expression, str):
            raise TypeError("schedules must contain strings")
        expression = " ".join(expression.split())
        if len(expression.split()) != 5:
            raise ValueError(
                "each schedule must have five fields: minute hour day month weekday"
            )
        # Random/hash expressions would require a stable per-expression seed.
        if re.search(r"(?<![a-z])[hr](?![a-z])", expression, re.IGNORECASE):
            raise ValueError("random and hashed cron fields are not supported")
        if expression not in expressions:
            expressions.append(expression)
    if not expressions:
        raise ValueError("schedules must not be empty")
    return tuple(expressions)


class ScheduleTrigger(Trigger):
    """Emit events for one or more five-field cron expressions.

    ``timezone=None`` resolves the machine's local timezone at construction.
    Equal planned instants are grouped. After a delay, only the latest elapsed
    instant is emitted; a timestamp watermark prevents clock rollback replay.
    """

    def __init__(
        self,
        schedules: str | Sequence[str],
        callback: TriggerCallback | None = None,
        *,
        timezone: str | None = None,
        day_or: bool = True,
        drop_if_busy: bool = False,
        q_size: int = 100,
        log_level: str | int = "INFO",
    ):
        if timezone is not None and not isinstance(timezone, str):
            raise TypeError("timezone must be an IANA timezone name or None")
        if not isinstance(day_or, bool):
            raise TypeError("day_or must be a bool")
        try:
            resolved_timezone = (
                get_localzone() if timezone is None else ZoneInfo(timezone)
            )
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"cannot resolve timezone: {timezone!r}") from error
        self.schedules = _normalize(schedules)
        self.timezone = resolved_timezone
        self.day_or = day_or
        # Validate both syntax and existence of a future occurrence before the
        # base class registers this trigger in the lifecycle registry.
        now = self.get_timestamp()
        for expression in self.schedules:
            self._next_after(expression, now)
        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self._lifecycle_lock = Lock()
        self._state_lock = Lock()
        self._watch_thread: Thread | None = None
        self._next_times: dict[str, float] = {}
        self._cursor = float("-inf")

    def _iterator(self, expression: str, timestamp: float) -> croniter:
        return croniter(
            expression,
            datetime.fromtimestamp(timestamp, self.timezone),
            day_or=self.day_or,
            max_years_between_matches=_SEARCH_YEARS,
        )

    def _next_after(self, expression: str, timestamp: float) -> float:
        try:
            result = self._iterator(expression, timestamp).get_next(float)
        except (CroniterError, ValueError, OverflowError) as error:
            raise ValueError(
                f"invalid or unschedulable cron expression: {expression!r} "
                f"(search limit: {_SEARCH_YEARS} years)"
            ) from error
        if result <= timestamp:
            raise ValueError(f"cron expression did not advance time: {expression!r}")
        return result

    def _prepare(self, now: float) -> None:
        """Reset upcoming times; caller holds the state lock."""
        cursor = max(now, self._cursor)
        upcoming = {
            expression: self._next_after(expression, cursor)
            for expression in self.schedules
        }
        self._next_times = upcoming
        self._cursor = cursor

    def start(self) -> None:
        """Start after the current time; repeated calls do not add threads."""
        with self._lifecycle_lock:
            if self._watch_thread is not None and self._watch_thread.is_alive():
                return
            with self._state_lock:
                self._prepare(self.get_timestamp())
                self._stop_event.clear()
                self.is_stopped = False
            self._watch_thread = Thread(
                target=self.watching_loop,
                name=f"ScheduleTrigger-{self.id}",
                daemon=True,
            )
            try:
                self._watch_thread.start()
            except Exception:
                self._stop_event.set()
                self._watch_thread = None
                self._next_times.clear()
                self.clear_event()
                self.is_stopped = True
                raise

    def stop(self) -> None:
        """Interrupt waits, join the worker and discard undispatched events."""
        with self._lifecycle_lock:
            self._stop_event.set()
            worker = self._watch_thread
            if worker is not None and worker is not current_thread():
                worker.join()
            with self._state_lock:
                self._next_times.clear()
                self.clear_event()
            self._watch_thread = None
            self.is_stopped = True

    def _check_due(self, now: float) -> TriggerMessage | None:
        """Advance past elapsed occurrences, coalescing to the latest instant."""
        with self._state_lock:
            due = {
                expression: timestamp
                for expression, timestamp in self._next_times.items()
                if timestamp <= now
            }
            if not due:
                return None
            for expression, timestamp in due.items():
                # A microsecond in epoch time makes get_prev inclusive even
                # at an exact minute, while preserving the fold at DST rollback.
                previous = self._iterator(expression, now + 0.000001).get_prev(float)
                if timestamp < previous <= now:
                    due[expression] = previous
            latest = max(due.values())
            matched = tuple(
                expression for expression in due if due[expression] == latest
            )
            upcoming = {
                expression: self._next_after(expression, now)
                for expression in self.schedules
            }
            self._next_times = upcoming
            self._cursor = latest
            data: ScheduleEventData = {
                "scheduled_at": datetime.fromtimestamp(latest, self.timezone),
                "schedules": matched,
            }
            return TriggerMessage(timestamp=now, data=data)

    def watching_loop(self) -> None:
        """Wait for the nearest occurrence, checking for wall-clock changes."""
        try:
            while not self._stop_event.is_set():
                now = self.get_timestamp()
                message = self._check_due(now)
                if message is not None and not self._set_event(message):
                    _logger.warning(
                        "ScheduleTrigger %s: event dropped (busy or queue full)",
                        self.id,
                    )
                with self._state_lock:
                    if not self._next_times:
                        break
                    remaining = max(0.0, min(self._next_times.values()) - now)
                if self._stop_event.wait(min(remaining, _CLOCK_CHECK_SECONDS)):
                    break
        except Exception:
            _logger.exception("ScheduleTrigger %s: scheduling failed", self.id)
            self._stop_event.set()
        finally:
            self.is_stopped = True
