"""Bounded, idempotent background ingestion job orchestration."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

from opentelemetry import context as otel_context

from src.app.observability.metrics import WorkerMetrics


class IngestionJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryableIngestionError(RuntimeError):
    """An ingestion failure that may be retried within the job limit."""


class PermanentIngestionError(RuntimeError):
    """An ingestion failure that must not be retried."""


class IngestionCancelledError(RuntimeError):
    """A cooperative task cancellation requested by the caller."""


class IngestionLeaseLost(RuntimeError):
    """The persisted job was reclaimed by another worker generation."""


class TaskDispatchError(RuntimeError):
    """A durable job row exists but broker publication did not complete."""


class TaskDispatcher(Protocol):
    """Transport boundary for a durable cross-process task queue."""

    def dispatch(self, job: IngestionJob) -> str | None: ...


@dataclass(frozen=True)
class IngestionJob:
    job_id: UUID
    tenant_id: str
    idempotency_key: str
    status: IngestionJobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: Any = None
    attempt: int = 0
    max_attempts: int = 3
    progress: int = 0
    cancel_requested: bool = False
    task_type: str = "ingestion"
    task_payload: str | None = None


@dataclass(frozen=True)
class IngestionLease:
    job: IngestionJob
    worker_id: str
    lease_token: str
    fence_version: int


class IngestionJobManager:
    """Run ingestion callables off the request path with bounded resources."""

    def __init__(
        self,
        *,
        max_workers: int = 2,
        timeout_seconds: float = 300.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.1,
        dispatcher: TaskDispatcher | None = None,
        tracer: Any | None = None,
        metrics: WorkerMetrics | None = None,
    ):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ingestion"
        )
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._dispatcher = dispatcher
        self.tracer = tracer
        self.metrics = metrics or WorkerMetrics()
        self._lock = threading.Lock()
        self._jobs: dict[UUID, IngestionJob] = {}
        self._futures: dict[UUID, Future[Any]] = {}
        self._idempotency: dict[tuple[str, str], UUID] = {}
        self._dispatched: set[UUID] = set()
        self._dispatching: set[UUID] = set()

    def submit(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        operation: Callable[[], Any],
        job_id: UUID | None = None,
        max_attempts: int | None = None,
        task_type: str = "ingestion",
        task_payload: str | None = None,
        defer_dispatch: bool = False,
    ) -> IngestionJob:
        if not tenant_id.strip() or not idempotency_key.strip():
            raise ValueError("tenant_id and idempotency_key must not be empty")
        key = (tenant_id, idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                return self._jobs[existing_id]
            job = IngestionJob(
                job_id=job_id or uuid4(),
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                status=IngestionJobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
                max_attempts=max_attempts or self._max_attempts,
                task_type=task_type,
                task_payload=task_payload,
            )
            self._jobs[job.job_id] = job
            self._idempotency[key] = job.job_id
            self.metrics.submitted()
            if self._dispatcher is None:
                try:
                    self._futures[job.job_id] = self._executor.submit(
                        self._run,
                        job.job_id,
                        operation,
                        otel_context.get_current(),
                        time.monotonic(),
                    )
                except Exception:
                    self.metrics.submission_failed()
                    del self._jobs[job.job_id]
                    del self._idempotency[key]
                    raise
        if self._dispatcher is not None and not defer_dispatch:
            self.dispatch(job)
        return job

    def dispatch(self, job: IngestionJob) -> str | None:
        """Publish a queued job exactly once per manager instance.

        Persistence must happen before this method is called when a durable
        job store is configured. A failed publish leaves the queued job
        available for an explicit retry or startup recovery.
        """

        dispatcher = self._dispatcher
        if dispatcher is None:
            return None
        with self._lock:
            current = self._jobs.get(job.job_id)
            if current is None or current.tenant_id != job.tenant_id:
                raise KeyError("ingestion job not found")
            if current.status != IngestionJobStatus.QUEUED:
                return None
            if job.job_id in self._dispatched:
                return None
            if job.job_id in self._dispatching:
                return None
            self._dispatching.add(job.job_id)
        try:
            task_id = dispatcher.dispatch(current)
        except Exception as exc:
            with self._lock:
                self._dispatching.discard(job.job_id)
                self.metrics.submission_failed()
            raise TaskDispatchError("ingestion task dispatch failed") from exc
        with self._lock:
            self._dispatching.discard(job.job_id)
            self._dispatched.add(job.job_id)
        return task_id

    def get(self, *, tenant_id: str, job_id: UUID) -> IngestionJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                return None
            return job

    @property
    def has_dispatcher(self) -> bool:
        return self._dispatcher is not None

    @property
    def dispatcher(self) -> TaskDispatcher | None:
        return self._dispatcher

    def get_by_idempotency(
        self, *, tenant_id: str, idempotency_key: str
    ) -> IngestionJob | None:
        with self._lock:
            job_id = self._idempotency.get((tenant_id, idempotency_key))
            return self._jobs.get(job_id) if job_id is not None else None

    def cancel(self, *, tenant_id: str, job_id: UUID) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                return False
            future = self._futures[job_id]
            if future.cancel():
                self._jobs[job_id] = self._replace(
                    job, status=IngestionJobStatus.CANCELLED
                )
                self.metrics.cancelled_queued()
                return True
            if job.status == IngestionJobStatus.RUNNING:
                self._jobs[job_id] = self._replace(job, cancel_requested=True)
                return True
            return False

    def update_progress(
        self, *, tenant_id: str, job_id: UUID, progress: int
    ) -> IngestionJob:
        if progress < 0 or progress > 100:
            raise ValueError("progress must be between 0 and 100")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                raise KeyError("ingestion job not found")
            updated = self._replace(job, progress=progress)
            self._jobs[job_id] = updated
            return updated

    def is_cancel_requested(self, *, tenant_id: str, job_id: UUID) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.tenant_id == tenant_id and job.cancel_requested)

    def close(self) -> None:
        """Stop accepting work and drain running jobs before resources close.

        The job operation may still need its repository after the operation
        callback returns (for example, to persist its terminal state). Waiting
        here prevents the application lifespan from disposing that repository
        while a worker thread is still using it.
        """
        with self._lock:
            queued = [
                (job_id, future)
                for job_id, future in self._futures.items()
                if self._jobs.get(job_id, None)
                and self._jobs[job_id].status == IngestionJobStatus.QUEUED
            ]
        for job_id, future in queued:
            if future.cancel():
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is not None and job.status == IngestionJobStatus.QUEUED:
                        self._jobs[job_id] = self._replace(
                            job, status=IngestionJobStatus.CANCELLED
                        )
                        self.metrics.cancelled_queued()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(
        self,
        job_id: UUID,
        operation: Callable[[], Any],
        parent_context,
        submitted_at: float,
    ) -> None:
        context_token = otel_context.attach(parent_context)
        self.metrics.started(time.monotonic() - submitted_at)
        processing_started = time.monotonic()
        span_context = (
            self.tracer.start_span("worker.ingestion")
            if self.tracer is not None
            else nullcontext(None)
        )
        try:
            with span_context:
                self._run_job(job_id, operation)
        finally:
            current = self.get(tenant_id=self._jobs[job_id].tenant_id, job_id=job_id)
            status = current.status.value if current is not None else "failed"
            self.metrics.finished(status, time.monotonic() - processing_started)
            otel_context.detach(context_token)

    def _run_job(self, job_id: UUID, operation: Callable[[], Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            started = datetime.now(timezone.utc)
            self._jobs[job_id] = self._replace(
                job, status=IngestionJobStatus.RUNNING, started_at=started
            )
        try:
            result = None
            started_monotonic = time.monotonic()
            for attempt in range(1, self._max_attempts + 1):
                with self._lock:
                    current = self._jobs[job_id]
                    self._jobs[job_id] = self._replace(current, attempt=attempt)
                try:
                    result = operation()
                    break
                except RetryableIngestionError:
                    if attempt >= self._max_attempts:
                        raise
                    self.metrics.retry()
                    delay = min(
                        self._retry_backoff_seconds * (2 ** (attempt - 1)),
                        self._timeout_seconds / 4,
                    )
                    time.sleep(delay)
                except PermanentIngestionError:
                    raise
                if time.monotonic() - started_monotonic > self._timeout_seconds:
                    raise TimeoutError("ingestion job exceeded its configured timeout")
            with self._lock:
                current = self._jobs[job_id]
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed > self._timeout_seconds:
                    self._jobs[job_id] = self._replace(
                        current,
                        status=IngestionJobStatus.FAILED,
                        completed_at=datetime.now(timezone.utc),
                        error="ingestion job exceeded its configured timeout",
                    )
                else:
                    self._jobs[job_id] = self._replace(
                        current,
                        status=IngestionJobStatus.COMPLETED,
                        completed_at=datetime.now(timezone.utc),
                        result=result,
                    )
        except Exception as exc:  # noqa: BLE001 - worker records every job failure safely.
            with self._lock:
                current = self._jobs[job_id]
                status = (
                    IngestionJobStatus.CANCELLED
                    if isinstance(exc, IngestionCancelledError)
                    else IngestionJobStatus.FAILED
                )
                self._jobs[job_id] = self._replace(
                    current,
                    status=status,
                    completed_at=datetime.now(timezone.utc),
                    error=str(exc)[:500],
                )

    @staticmethod
    def _replace(job: IngestionJob, **changes: Any) -> IngestionJob:
        values = {field: getattr(job, field) for field in job.__dataclass_fields__}
        values.update(changes)
        return IngestionJob(**values)
