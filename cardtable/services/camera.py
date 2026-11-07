from __future__ import annotations

from collections import deque
from concurrent.futures import CancelledError, Future, InvalidStateError
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Condition, Thread
from time import monotonic
from typing import Any

import cv2
import numpy as np

from ._service import Service


class Camera(Service):
    """A lifecycle-managed camera with request-specific frame results."""

    def __init__(self, source: int | str = 0, *, backend: int | None = None):
        if not isinstance(source, (int, str)) or isinstance(source, bool):
            raise TypeError("source must be a camera index or video path")
        if backend is not None and not isinstance(backend, int):
            raise TypeError("backend must be an int or None")
        super().__init__("Camera")
        self.source = source
        self.backend = backend
        self._capture: Any | None = None
        self._condition = Condition()
        self._requests: deque[Future[np.ndarray]] = deque()
        self._inflight: set[Future[np.ndarray]] = set()
        self._worker: Thread | None = None
        self._started = False
        self._generation = 0

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("previous Camera worker is still stopping")
            if self.backend is None:
                capture = cv2.VideoCapture(self.source)
            else:
                capture = cv2.VideoCapture(self.source, self.backend)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError(f"failed to open camera source {self.source!r}")
            self._capture = capture
            self._stop_event.clear()
            self._started = True
            self._worker = Thread(target=self._processing_loop, daemon=True)
            self._worker.start()

    def submit(self, *, timeout: float | None = None) -> Future[np.ndarray]:
        """Queue one frame request; timeout bounds the wait for queue capacity."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            generation = self._generation
            while True:
                if not self._started or generation != self._generation:
                    raise RuntimeError("Camera is stopped")
                if not self._requests:
                    break
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("Camera operation timed out")
                self._condition.wait(remaining)
            future: Future[np.ndarray] = Future()
            self._requests.append(future)
            self._inflight.add(future)
            future.add_done_callback(self._finished)
            self._condition.notify_all()
            return future

    def _finished(self, future: Future[np.ndarray]) -> None:
        with self._condition:
            self._inflight.discard(future)
            if future.cancelled():
                future.set_running_or_notify_cancel()
                try:
                    self._requests.remove(future)
                except ValueError:
                    pass
                self._condition.notify_all()

    def result(
        self, future: Future[np.ndarray], *, timeout: float | None = None
    ) -> np.ndarray:
        """Return the requested frame; cancel and discard it on timeout."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        try:
            return future.result(timeout=timeout)
        except (FutureTimeoutError, TimeoutError) as error:
            if future.done() and not future.cancelled() and future.exception() is error:
                raise RuntimeError("Camera worker failed") from error
            future.cancel()
            raise TimeoutError("Camera operation timed out") from None
        except CancelledError:
            raise RuntimeError("Camera is stopped or request was cancelled") from None

    def get(self, *, timeout: float | None = None) -> np.ndarray:
        """Request a frame and wait for it within one timeout."""
        return self.execute(timeout=timeout)

    def _processing_loop(self) -> None:
        capture = self._capture
        try:
            while True:
                with self._condition:
                    while not self._requests and not self._stop_event.is_set():
                        self._condition.wait()
                    if self._stop_event.is_set():
                        return
                    future = self._requests.popleft()
                    self._condition.notify_all()
                if future.cancelled():
                    continue
                try:
                    succeeded, frame = capture.read()
                    if not succeeded or frame is None:
                        raise RuntimeError(
                            f"failed to read camera source {self.source!r}"
                        )
                except Exception as error:
                    try:
                        future.set_exception(error)
                    except InvalidStateError:
                        pass
                else:
                    try:
                        future.set_result(frame)
                    except InvalidStateError:
                        pass
        finally:
            capture.release()
            with self._condition:
                self._capture = None

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
        with self._condition:
            self.request_stop()
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)
