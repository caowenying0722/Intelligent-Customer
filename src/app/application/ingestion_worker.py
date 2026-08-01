"""Recovery orchestration for persisted ingestion jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobManager,
    IngestionJobStatus,
    RetryableIngestionError,
)


class RecoverableJobStore(Protocol):
    def list_recoverable_jobs(self, *, tenant_id: str | None = None) -> list[IngestionJob]: ...

    def update_job_status(
        self, *, tenant_id: str, job_id: UUID, status: IngestionJobStatus, error: str | None = None
    ) -> IngestionJob: ...


class IngestionWorker:
    def __init__(self, manager: IngestionJobManager, store: RecoverableJobStore):
        self.manager = manager
        self.store = store

    def recover_queued(
        self,
        *,
        tenant_id: str | None,
        operation_for: Callable[[IngestionJob], Callable[[], Any]],
        task_type: str | None = None,
    ) -> list[UUID]:
        """Resume queued jobs with their original IDs; running jobs are not duplicated."""
        recovered: list[UUID] = []
        for persisted in self.store.list_recoverable_jobs(tenant_id=tenant_id):
            if persisted.status != IngestionJobStatus.QUEUED:
                continue
            if task_type is not None and persisted.task_type != task_type:
                continue
            operation = operation_for(persisted)

            def run(operation=operation, persisted=persisted):
                try:
                    result = operation()
                except Exception as exc:
                    current = self.manager.get(
                        tenant_id=persisted.tenant_id, job_id=persisted.job_id
                    )
                    exhausted = current is None or current.attempt >= current.max_attempts
                    if not isinstance(exc, RetryableIngestionError) or exhausted:
                        self.store.update_job_status(
                            tenant_id=persisted.tenant_id,
                            job_id=persisted.job_id,
                            status=IngestionJobStatus.FAILED,
                            error=str(exc),
                        )
                    raise
                self.store.update_job_status(
                    tenant_id=persisted.tenant_id,
                    job_id=persisted.job_id,
                    status=IngestionJobStatus.COMPLETED,
                )
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
            current = self.manager.get(tenant_id=job.tenant_id, job_id=job.job_id) or job
            status = (
                current.status
                if current.status in {IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED}
                else IngestionJobStatus.RUNNING
            )
            self.store.update_job_status(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                status=status,
                error=current.error,
            )
        return recovered
