"""Bounded inference jobs and cross-thread completion notification."""

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Lock

from .models import ErrorInfo, EventResponse, Payload


@dataclass
class Job:
    response: EventResponse
    done: Future[EventResponse] = field(default_factory=Future)


class JobHistory:
    def __init__(self, size: int):
        self._size = size
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = Lock()

    def can_add(self) -> bool:
        with self._lock:
            return len(self._jobs) < self._size or any(
                job.done.done() for job in self._jobs.values()
            )

    def add(self, job: Job) -> None:
        with self._lock:
            while len(self._jobs) >= self._size:
                oldest = next(
                    (key for key, value in self._jobs.items() if value.done.done()),
                    None,
                )
                if oldest is None:
                    raise RuntimeError("Pending jobs cannot be evicted")
                del self._jobs[oldest]
            self._jobs[job.response.event_id] = job

    def get(self, event_id: str) -> EventResponse | None:
        with self._lock:
            job = self._jobs.get(event_id)
            return job.response.model_copy(deep=True) if job else None

    def finish(
        self, event_id: str, result: Payload | None, error: ErrorInfo | None
    ) -> None:
        with self._lock:
            job = self._jobs.get(event_id)
            if job is None or job.done.done():
                return
            job.response = job.response.model_copy(
                update={
                    "status": "failed" if error else "succeeded",
                    "result": result,
                    "error": error,
                }
            )
            job.done.set_result(job.response)

    def cancel_pending(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if not job.done.done():
                    job.response = job.response.model_copy(
                        update={
                            "status": "cancelled",
                            "error": ErrorInfo(
                                code="server_stopped",
                                message="Server stopped before a result was available",
                            ),
                        }
                    )
                    job.done.set_result(job.response)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
