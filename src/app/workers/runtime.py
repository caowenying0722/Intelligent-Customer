from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from src.app.application.ingestion import (
    IngestionCancelledError,
    IngestionJob,
    IngestionJobStatus,
    IngestionLease,
    IngestionLeaseLost,
    PermanentIngestionError,
    RetryableIngestionError,
)
from src.app.workers.contracts import TaskEnvelope


class JobStore(Protocol):
    def get_job(self, *, tenant_id: str, job_id: UUID) -> IngestionJob | None: ...

    def claim_job(
        self,
        *,
        tenant_id: str,
        job_id: UUID,
        worker_id: str,
        lease_seconds: float,
    ) -> IngestionLease | None: ...


class RetryableTaskFailure(RetryableIngestionError):
    def __init__(self, message: str, *, attempt: int) -> None:
        super().__init__(message)
        self.attempt = attempt


class TaskNotClaimed(RuntimeError):
    """A duplicate delivery found another active lease or a terminal job."""


class TaskTimeoutError(TimeoutError):
    """The operation exceeded the worker's cooperative timeout."""


@dataclass(frozen=True)
class TaskRuntimeConfig:
    timeout_seconds: float = 300.0
    lease_seconds: float = 360.0
    worker_id: str = ""

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.lease_seconds <= 0:
            raise ValueError("worker timeouts must be positive")
        if self.worker_id and not self.worker_id.strip():
            raise ValueError("worker_id must not be blank")


OperationFactory = Callable[[IngestionJob], Callable[[], Any]]


class CeleryTaskRuntime:
    """Claim and execute one persisted job with lease fencing and bounded time."""

    def __init__(
        self,
        store: JobStore,
        operation_for: OperationFactory,
        *,
        config: TaskRuntimeConfig | None = None,
    ) -> None:
        self.store = store
        self.operation_for = operation_for
        selected = config or TaskRuntimeConfig()
        self.config = TaskRuntimeConfig(
            timeout_seconds=selected.timeout_seconds,
            lease_seconds=selected.lease_seconds,
            worker_id=selected.worker_id or f"celery-{uuid4()}",
        )

    def execute(self, envelope: TaskEnvelope) -> dict[str, str | int]:
        persisted = self.store.get_job(
            tenant_id=envelope.tenant_id, job_id=envelope.job_id
        )
        if persisted is None:
            raise PermanentIngestionError("ingestion job not found")
        self._validate_identity(persisted, envelope)
        if persisted.status in {
            IngestionJobStatus.COMPLETED,
            IngestionJobStatus.FAILED,
            IngestionJobStatus.CANCELLED,
        }:
            return self._result(persisted)

        lease = self.store.claim_job(
            tenant_id=envelope.tenant_id,
            job_id=envelope.job_id,
            worker_id=self.config.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if lease is None:
            current = self.store.get_job(
                tenant_id=envelope.tenant_id, job_id=envelope.job_id
            )
            if current is not None and current.status in {
                IngestionJobStatus.COMPLETED,
                IngestionJobStatus.FAILED,
                IngestionJobStatus.CANCELLED,
            }:
                return self._result(current)
            raise TaskNotClaimed("ingestion job is already leased")

        attempt = lease.job.attempt + 1
        self._update_progress(lease.job, 0)
        try:
            if lease.job.cancel_requested:
                self._complete(lease, IngestionJobStatus.CANCELLED, error="cancelled")
                return self._result(lease.job, status=IngestionJobStatus.CANCELLED)
            operation = self.operation_for(lease.job)
            result = self._run_with_timeout(operation)
            current = self.store.get_job(
                tenant_id=lease.job.tenant_id, job_id=lease.job.job_id
            )
            if current is not None and current.cancel_requested:
                raise IngestionCancelledError("ingestion job cancelled")
            self._update_progress(lease.job, 100)
            self._complete(lease, IngestionJobStatus.COMPLETED)
            del result
            return self._result(lease.job, status=IngestionJobStatus.COMPLETED)
        except IngestionCancelledError:
            self._complete(lease, IngestionJobStatus.CANCELLED, error="cancelled")
            return self._result(lease.job, status=IngestionJobStatus.CANCELLED)
        except RetryableIngestionError as exc:
            if attempt < envelope.max_attempts:
                self._release_for_retry(lease, attempt, error="retryable task failure")
                raise RetryableTaskFailure(
                    "retryable task failure", attempt=attempt
                ) from exc
            self._complete(
                lease,
                IngestionJobStatus.FAILED,
                error="retry attempts exhausted",
                attempt=attempt,
            )
            raise PermanentIngestionError("retry attempts exhausted") from exc
        except (TaskTimeoutError, TimeoutError) as exc:
            self._complete(
                lease, IngestionJobStatus.FAILED, error="task timeout", attempt=attempt
            )
            raise TaskTimeoutError("ingestion task timed out") from exc
        except IngestionLeaseLost:
            raise
        except Exception as exc:  # noqa: BLE001 - persist a safe bounded error.
            self._complete(
                lease,
                IngestionJobStatus.FAILED,
                error=f"{type(exc).__name__}: task failed",
                attempt=attempt,
            )
            raise PermanentIngestionError("ingestion task failed") from exc

    def _run_with_timeout(self, operation: Callable[[], Any]) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="celery-task")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self.config.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TaskTimeoutError("ingestion task timed out") from exc
        finally:
            # A running synchronous provider cannot be safely killed by Python.
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _validate_identity(job: IngestionJob, envelope: TaskEnvelope) -> None:
        if (
            job.tenant_id != envelope.tenant_id
            or job.idempotency_key != envelope.idempotency_key
            or job.task_type != envelope.task_type
            or job.task_payload != envelope.task_payload
        ):
            raise PermanentIngestionError("task envelope does not match persisted job")

    def _update_progress(self, job: IngestionJob, progress: int) -> None:
        updater = getattr(self.store, "update_progress", None)
        if callable(updater):
            updater(tenant_id=job.tenant_id, job_id=job.job_id, progress=progress)

    def _complete(
        self,
        lease: IngestionLease,
        status: IngestionJobStatus,
        *,
        error: str | None = None,
        attempt: int | None = None,
    ) -> None:
        complete = getattr(self.store, "complete_claimed_job", None)
        if not callable(complete):
            raise RuntimeError("job store does not support fenced completion")
        complete(
            tenant_id=lease.job.tenant_id,
            job_id=lease.job.job_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
            fence_version=lease.fence_version,
            status=status,
            error=error,
            attempt=attempt,
        )

    def _release_for_retry(
        self, lease: IngestionLease, attempt: int, *, error: str
    ) -> None:
        release = getattr(self.store, "release_claimed_job", None)
        if not callable(release):
            raise RuntimeError("job store does not support retry release")
        release(
            tenant_id=lease.job.tenant_id,
            job_id=lease.job.job_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
            fence_version=lease.fence_version,
            attempt=attempt,
            error=error,
        )

    @staticmethod
    def _result(
        job: IngestionJob, *, status: IngestionJobStatus | None = None
    ) -> dict[str, str | int]:
        return {
            "job_id": str(job.job_id),
            "tenant_id": job.tenant_id,
            "status": (status or job.status).value,
            "attempt": job.attempt,
        }
