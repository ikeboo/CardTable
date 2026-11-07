from abc import ABC, abstractmethod
from concurrent.futures import Future
from threading import Event
from time import monotonic
from typing import Any

from cardtable.core.closure import Closure


class Service(ABC):
    def __init__(self, name: str):
        self.name = name
        self._stop_event = Event()
        Closure.add(self)

    @abstractmethod
    def request_stop(self) -> None:
        """Request shutdown and wake operations waiting for this service."""
        pass

    @abstractmethod
    def submit(self, *args, timeout: float | None = None, **kwargs) -> Future[Any]:
        """Submit a request and return its Future; timeout bounds submission."""
        pass

    @abstractmethod
    def result(self, future: Future[Any], *, timeout: float | None = None) -> Any:
        """Get the result of this request; cancel it if the wait times out."""
        pass

    def execute(self, *args, timeout: float | None = None, **kwargs) -> Any:
        """Submit a request and wait for its result within one timeout."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else monotonic() + timeout
        future = self.submit(*args, timeout=timeout, **kwargs)
        remaining = None if deadline is None else max(0.0, deadline - monotonic())
        return self.result(future, timeout=remaining)

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass
