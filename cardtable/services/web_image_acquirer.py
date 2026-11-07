from collections import deque
from concurrent.futures import CancelledError, Future, InvalidStateError
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Condition, Thread
from time import monotonic

import cv2
import numpy as np
import requests

from ._service import Service


class WebImageAcquirer(Service):
    """Acquire web images in a worker, associating each result with its request."""

    def __init__(self):
        super().__init__("WebImageAcquirer")
        self._condition = Condition()
        self._requests = deque()
        self._inflight = set()
        self._worker: Thread | None = None
        self._started = False
        self._generation = 0

    def _wait(self, predicate, timeout: float | None) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else monotonic() + timeout
        generation = self._generation
        while True:
            if self._generation != generation or not self._started:
                raise RuntimeError("WebImageAcquirer is stopped")
            if predicate():
                return
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("WebImageAcquirer operation timed out")
            self._condition.wait(remaining)

    def submit(
        self, url: str, *, timeout: float | None = None
    ) -> Future[np.ndarray | None]:
        """Queue a URL and return its future; timeout bounds the enqueue wait."""
        with self._condition:
            self._wait(lambda: not self._requests, timeout)
            future = Future()
            self._requests.append((url, future))
            self._inflight.add(future)
            future.add_done_callback(self._finished)
            self._condition.notify_all()
            return future

    def _finished(self, future: Future) -> None:
        with self._condition:
            self._inflight.discard(future)
            if future.cancelled():
                # Notify concurrent.futures.wait/as_completed about cancellation.
                future.set_running_or_notify_cancel()
                self._requests = deque(
                    item for item in self._requests if item[1] is not future
                )
                self._condition.notify_all()

    def result(
        self, future: Future[np.ndarray | None], *, timeout: float | None = None
    ) -> tuple[bool, np.ndarray | None]:
        """Wait for this request; discard its eventual result on timeout."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        try:
            result = future.result(timeout=timeout)
        except (FutureTimeoutError, TimeoutError) as error:
            if future.done() and not future.cancelled() and future.exception() is error:
                raise RuntimeError("WebImageAcquirer worker failed") from error
            future.cancel()
            raise TimeoutError("WebImageAcquirer operation timed out") from None
        except CancelledError:
            raise RuntimeError(
                "WebImageAcquirer is stopped or request was cancelled"
            ) from None
        except Exception as error:
            raise RuntimeError("WebImageAcquirer worker failed") from error
        return result is not None, result

    def get(
        self, url: str, *, timeout: float | None = None
    ) -> tuple[bool, np.ndarray | None]:
        """Submit an image URL and wait for its result within one timeout."""
        return self.execute(url, timeout=timeout)

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("previous WebImageAcquirer worker is still stopping")
            self._requests.clear()
            self._stop_event.clear()
            self._started = True
            self._worker = Thread(target=self._processing_loop, daemon=True)
            self._worker.start()

    def _processing_loop(self) -> None:
        while True:
            with self._condition:
                while not self._requests and not self._stop_event.is_set():
                    self._condition.wait()
                if self._stop_event.is_set():
                    return
                url, future = self._requests.popleft()
                self._condition.notify_all()
            if future.cancelled():
                continue
            try:
                result = self.acquire_image(url)
            except Exception as error:
                try:
                    future.set_exception(error)
                except InvalidStateError:
                    pass
            else:
                try:
                    future.set_result(result)
                except InvalidStateError:
                    pass

    def acquire_image(self, url: str) -> np.ndarray | None:
        """Acquire and decode an image, returning None for HTTP errors."""
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            encoded_image = np.frombuffer(response.content, dtype=np.uint8)
            return cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)
        except requests.RequestException:
            return None

    def request_stop(self) -> None:
        with self._condition:
            self._stop_event.set()
            self._started = False
            self._generation += 1
            for future in tuple(self._inflight):
                future.cancel()
            self._requests.clear()
            self._condition.notify_all()

    def stop(self) -> None:
        self.request_stop()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=1.0)
