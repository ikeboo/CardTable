from abc import ABC, abstractmethod
from collections import deque
from threading import Event, Lock
from time import time
from typing import TYPE_CHECKING, Any, Deque, Optional
from uuid import uuid4

from cardtable._logging import _normalize_level
from cardtable.core.closure import Closure
from cardtable.core.message_event import MessageEvent
from cardtable.core.trigger_callback import TriggerCallback, validate_trigger_callback
from cardtable.data_classes.trigger_message import TriggerMessage

if TYPE_CHECKING:
    from cardtable.data_classes.trigger_event import TriggerEvent


class Trigger(ABC):
    """Event trigger for the dealer
    トリガーを検知し、イベントをセットするクラス
    callbackに指定されたコールバックの登録・実行はFlowクラスが行う。
    """

    def __init__(
        self,
        *,
        callback: TriggerCallback | None = None,
        drop_if_busy: bool = True,
        q_size: int = 10,
        log_level: str | int = "INFO",
    ):
        validate_trigger_callback(callback)
        log_level = _normalize_level(log_level)
        if not isinstance(drop_if_busy, bool):
            raise TypeError("drop_if_busy must be a bool")
        if isinstance(q_size, bool) or not isinstance(q_size, int):
            raise TypeError("q_size must be an int")
        if q_size <= 0:
            raise ValueError("q_size must be greater than zero")

        self._id = uuid4().hex
        self.callback = callback
        self.log_level = log_level
        self.drop_if_busy = drop_if_busy
        self.q_size = q_size
        self.message_event = MessageEvent()
        self._message_queue: Deque[TriggerMessage] = deque()
        self._message_lock = Lock()
        self._busy = False
        self._stop_event = Event()
        self.is_stopped = False
        self._closure = Closure()
        self._closure.add(self)

    @property
    def id(self) -> str:
        """Unique source ID, stable for the lifetime of this trigger."""
        return self._id

    @abstractmethod
    def start(self):
        """start observing the trigger event"""
        pass

    @abstractmethod
    def watching_loop(self):
        """observing the trigger event, while not _stop_event.is_set()"""
        pass

    @abstractmethod
    def stop(self):
        """stop observing and close the trigger,
        call _stop_event.set() and closing resource
        """
        pass

    def _set_event(self, message: TriggerMessage) -> bool:
        """Queue a message and notify the dealer.

        Returns ``False`` when the message is dropped because this trigger is
        busy or its pending-message queue is full.
        """
        with self._message_lock:
            if self.drop_if_busy and (self._busy or self._message_queue):
                return False
            if not self.drop_if_busy and len(self._message_queue) >= self.q_size:
                return False

            self._message_queue.append(message)
            self.message_event.set_message(self._message_queue[0])
            return True

    def _take_message(self) -> Optional[TriggerMessage]:
        """Take the next message and mark this trigger as busy."""
        with self._message_lock:
            if self._busy:
                return None
            if not self._message_queue:
                self.message_event.clear()
                return None

            message = self._message_queue.popleft()
            self._busy = True
            if not self._message_queue:
                self.message_event.clear()
            return message

    def _complete_message(self) -> None:
        """Mark callback processing for the current message as complete."""
        with self._message_lock:
            self._busy = False
            if self._message_queue:
                self.message_event.set_message(self._message_queue[0])

    def _callbacks_finished(
        self,
        event: "TriggerEvent",
        results: tuple[object, ...],
        errors: tuple[Exception, ...],
    ) -> None:
        """Observe callback outcomes; ordinary event sources need no action."""
        pass

    def _respond(
        self,
        event_id: str,
        texts: dict[str, str],
        images: dict[str, Any],
        image_format: str = "jpg",
    ) -> None:
        """Deliver an explicit event response when supported by the source."""
        raise NotImplementedError(f"{type(self).__name__} does not support responses")

    def clear_event(self):
        """clear the message event"""
        with self._message_lock:
            self._message_queue.clear()
            self.message_event.clear()

    def get_timestamp(self):
        """return the current timestamp"""
        return time()
