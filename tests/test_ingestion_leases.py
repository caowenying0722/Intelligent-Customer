from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobManager,
    IngestionJobStatus,
    IngestionLeaseLost,
)
from src.app.application.ingestion_worker import IngestionWorker
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from src.app.infrastructure.postgres import IngestionJobRow


def _queued(key: str) -> IngestionJob:
    return IngestionJob(
        job_id=uuid4(),
        tenant_id="tenant-a",
        idempotency_key=key,
        status=IngestionJobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
    )


def test_claim_uses_fencing_and_rejects_stale_worker_completion() -> None:
    repository = SqlAlchemyIngestionRepository(
        "sqlite+pysqlite:///:memory:", initialize_schema=True
    )
    job = _queued("lease-1")
    repository.create_job(job=job)

    first = repository.claim_recoverable_jobs(worker_id="worker-1", lease_seconds=30)[0]
    assert (
        repository.claim_recoverable_jobs(worker_id="worker-2", lease_seconds=30) == []
    )

    with Session(repository.engine) as session:
        row = session.get(IngestionJobRow, str(job.job_id))
        assert row is not None
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    second = repository.claim_recoverable_jobs(worker_id="worker-2", lease_seconds=30)[
        0
    ]
    assert second.fence_version == first.fence_version + 1

    with pytest.raises(IngestionLeaseLost):
        repository.complete_claimed_job(
            tenant_id="tenant-a",
            job_id=job.job_id,
            worker_id=first.worker_id,
            lease_token=first.lease_token,
            fence_version=first.fence_version,
            status=IngestionJobStatus.COMPLETED,
        )

    completed = repository.complete_claimed_job(
        tenant_id="tenant-a",
        job_id=job.job_id,
        worker_id=second.worker_id,
        lease_token=second.lease_token,
        fence_version=second.fence_version,
        status=IngestionJobStatus.COMPLETED,
    )
    assert completed.status == IngestionJobStatus.COMPLETED
    repository.close()


def test_recovery_worker_claims_and_completes_persisted_job() -> None:
    database = Path("output") / "ingestion_lease_worker.db"
    database.unlink(missing_ok=True)
    repository = SqlAlchemyIngestionRepository(
        f"sqlite+pysqlite:///{database.as_posix()}", initialize_schema=True
    )
    job = _queued("lease-worker")
    repository.create_job(job=job)
    manager = IngestionJobManager(max_workers=1)
    worker = IngestionWorker(manager, repository, worker_id="worker-1")

    recovered = worker.recover_queued(
        tenant_id="tenant-a", operation_for=lambda _job: lambda: "ok"
    )
    deadline = time.monotonic() + 2
    persisted = repository.get_job(tenant_id="tenant-a", job_id=job.job_id)
    while (
        persisted is not None
        and persisted.status
        not in {IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED}
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
        persisted = repository.get_job(tenant_id="tenant-a", job_id=job.job_id)

    assert recovered == [job.job_id]
    assert persisted is not None
    assert persisted.status == IngestionJobStatus.COMPLETED
    assert persisted.progress == 100
    manager.close()
    repository.close()
    database.unlink()
