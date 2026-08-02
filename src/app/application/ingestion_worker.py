"""Recovery orchestration for persisted ingestion jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID, uuid4

from src.app.application.ingestion import (
    IngestionCancelledError,
    IngestionJob,
    IngestionJobManager,
    IngestionJobStatus,
    IngestionLease,
    RetryableIngestionError,
)


class RecoverableJobStore(Protocol):
    def list_recoverable_jobs(
        self, *, tenant_id: str | None = None
    ) -> list[IngestionJob]: ...

    def update_job_status(
        self,
        *,
        tenant_id: str,
        job_id: UUID,
        status: IngestionJobStatus,
        error: str | None = None,
        attempt: int | None = None,
    ) -> IngestionJob: ...

    def update_progress(
        self, *, tenant_id: str, job_id: UUID, progress: int
    ) -> IngestionJob: ...


class IngestionWorker:
    def __init__(
        self,
        manager: IngestionJobManager,
        store: RecoverableJobStore,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 360,
        claim_limit: int = 10,
    ):
        if lease_seconds <= 0 or not 1 <= claim_limit <= 100:
            raise ValueError("invalid worker lease configuration")
        self.manager = manager
        self.store = store
        self.worker_id = worker_id or f"worker-{uuid4()}"
        self.lease_seconds = lease_seconds
        self.claim_limit = claim_limit

    def _progress(self, *, tenant_id: str, job_id: UUID, progress: int) -> None:
        self.manager.update_progress(
            tenant_id=tenant_id, job_id=job_id, progress=progress
        )
        updater = getattr(self.store, "update_progress", None)
        if callable(updater):
            updater(tenant_id=tenant_id, job_id=job_id, progress=progress)

    def recover_queued(
        self,
        *,
        tenant_id: str | None,
        operation_for: Callable[[IngestionJob], Callable[[], Any]],
        task_type: str | None = None,
    ) -> list[UUID]:
        """Resume queued jobs with their original IDs; running jobs are not duplicated."""
        recovered: list[UUID] = []
        claim = getattr(self.store, "claim_recoverable_jobs", None)
        entries: list[tuple[IngestionJob, IngestionLease | None]]
        if callable(claim):
            leases = claim(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                limit=self.claim_limit,
                tenant_id=tenant_id,
                task_type=task_type,
            )
            entries = [(lease.job, lease) for lease in leases]
        else:
            entries = [
                (job, None)
                for job in self.store.list_recoverable_jobs(tenant_id=tenant_id)
                if job.status == IngestionJobStatus.QUEUED
                and (task_type is None or job.task_type == task_type)
            ]
        for persisted, lease in entries:
            operation = operation_for(persisted)

            def finish(
                status: IngestionJobStatus,
                *,
                error: str | None = None,
                attempt: int | None = None,
                lease: IngestionLease | None = lease,
                persisted: IngestionJob = persisted,
            ) -> None:
                complete = getattr(self.store, "complete_claimed_job", None)
                if lease is not None and callable(complete):
                    complete(
                        tenant_id=persisted.tenant_id,
                        job_id=persisted.job_id,
                        worker_id=lease.worker_id,
                        lease_token=lease.lease_token,
                        fence_version=lease.fence_version,
                        status=status,
                        error=error,
                        attempt=attempt,
                    )
                    return
                self.store.update_job_status(
                    tenant_id=persisted.tenant_id,
                    job_id=persisted.job_id,
                    status=status,
                    error=error,
                    attempt=attempt,
                )

            def run(
                operation=operation,
                persisted=persisted,
                lease=lease,
                finish=finish,
            ):
                self._progress(
                    tenant_id=persisted.tenant_id, job_id=persisted.job_id, progress=0
                )
                try:
                    renew = getattr(self.store, "renew_lease", None)
                    if lease is not None and callable(renew):
                        renew(
                            tenant_id=persisted.tenant_id,
                            job_id=persisted.job_id,
                            worker_id=lease.worker_id,
                            lease_token=lease.lease_token,
                            fence_version=lease.fence_version,
                            lease_seconds=self.lease_seconds,
                        )
                    if self.manager.is_cancel_requested(
                        tenant_id=persisted.tenant_id, job_id=persisted.job_id
                    ):
                        raise IngestionCancelledError("ingestion job cancelled")
                    result = operation()
                    if self.manager.is_cancel_requested(
                        tenant_id=persisted.tenant_id, job_id=persisted.job_id
                    ):
                        raise IngestionCancelledError("ingestion job cancelled")
                except Exception as exc:
                    current = self.manager.get(
                        tenant_id=persisted.tenant_id, job_id=persisted.job_id
                    )
                    exhausted = (
                        current is None or current.attempt >= current.max_attempts
                    )
                    if isinstance(exc, IngestionCancelledError):
                        finish(IngestionJobStatus.CANCELLED, error=str(exc))
                    elif not isinstance(exc, RetryableIngestionError) or exhausted:
                        finish(
                            IngestionJobStatus.FAILED,
                            error=str(exc),
                            attempt=current.attempt if current is not None else None,
                        )
                    raise
                self._progress(
                    tenant_id=persisted.tenant_id, job_id=persisted.job_id, progress=100
                )
                finish(IngestionJobStatus.COMPLETED)
                return result

            job = self.manager.submit(
                tenant_id=persisted.tenant_id,
                idempotency_key=persisted.idempotency_key,
                operation=run,
                job_id=persisted.job_id,
                max_attempts=persisted.max_attempts,
                task_type=persisted.task_type,
                task_payload=persisted.task_payload,
            )
            recovered.append(job.job_id)
            current = (
                self.manager.get(tenant_id=job.tenant_id, job_id=job.job_id) or job
            )
            status = (
                current.status
                if current.status
                in {IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED}
                else IngestionJobStatus.RUNNING
            )
            if lease is None:
                self.store.update_job_status(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    status=status,
                    error=current.error,
                )
        return recovered
