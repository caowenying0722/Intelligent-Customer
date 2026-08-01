"""Bounded, idempotent background ingestion job orchestration."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable
from uuid import UUID, uuid4


class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class IngestionJobManager:
    """Run ingestion callables off the request path with bounded resources."""

    def __init__(self, *, max_workers: int = 2, timeout_seconds: float = 300.0):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ingestion"
        )
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._jobs: dict[UUID, IngestionJob] = {}
        self._futures: dict[UUID, Future[Any]] = {}
        self._idempotency: dict[tuple[str, str], UUID] = {}

    def submit(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        operation: Callable[[], Any],
    ) -> IngestionJob:
        if not tenant_id.strip() or not idempotency_key.strip():
            raise ValueError("tenant_id and idempotency_key must not be empty")
        key = (tenant_id, idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                return self._jobs[existing_id]
            job = IngestionJob(
                job_id=uuid4(),
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                status=IngestionJobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
            )
            self._jobs[job.job_id] = job
            self._idempotency[key] = job.job_id
            self._futures[job.job_id] = self._executor.submit(
                self._run, job.job_id, operation
            )
            return job

    def get(self, *, tenant_id: str, job_id: UUID) -> IngestionJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                return None
            return job

    def cancel(self, *, tenant_id: str, job_id: UUID) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                return False
            future = self._futures[job_id]
            if not future.cancel():
                return False
            self._jobs[job_id] = self._replace(job, status=IngestionJobStatus.CANCELLED)
            return True

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: UUID, operation: Callable[[], Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            started = datetime.now(timezone.utc)
            self._jobs[job_id] = self._replace(
                job, status=IngestionJobStatus.RUNNING, started_at=started
            )
        try:
            result = operation()
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
        except Exception as exc:
            with self._lock:
                current = self._jobs[job_id]
                self._jobs[job_id] = self._replace(
                    current,
                    status=IngestionJobStatus.FAILED,
                    completed_at=datetime.now(timezone.utc),
                    error=str(exc)[:500],
                )

    @staticmethod
    def _replace(job: IngestionJob, **changes: Any) -> IngestionJob:
        values = {field: getattr(job, field) for field in job.__dataclass_fields__}
        values.update(changes)
        return IngestionJob(**values)
