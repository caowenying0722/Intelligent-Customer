import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.app.application.ingestion import IngestionJob, IngestionJobManager, IngestionJobStatus
from src.app.application.ingestion_worker import IngestionWorker


class FakeStore:
    def __init__(self, jobs):
        self.jobs = jobs
        self.updated = []

    def list_recoverable_jobs(self, *, tenant_id=None):
        return [job for job in self.jobs if tenant_id is None or job.tenant_id == tenant_id]

    def update_job_status(self, **kwargs):
        self.updated.append(kwargs)
        return next(job for job in self.jobs if job.job_id == kwargs["job_id"])


def test_worker_recovers_queued_job_with_original_id_and_tenant() -> None:
    job = IngestionJob(
        job_id=uuid4(), tenant_id="tenant-a", idempotency_key="queued",
        status=IngestionJobStatus.QUEUED, created_at=datetime.now(timezone.utc),
    )
    store = FakeStore([job])
    manager = IngestionJobManager(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    try:
        recovered = IngestionWorker(manager, store).recover_queued(
            tenant_id="tenant-a",
            operation_for=lambda persisted: lambda: (started.set(), release.wait(1)),
        )
        assert recovered == [job.job_id]
        assert started.wait(1)
        assert store.updated[0]["status"] == IngestionJobStatus.RUNNING
        assert manager.get(tenant_id="tenant-b", job_id=job.job_id) is None
        release.set()
    finally:
        manager.close()


def test_worker_does_not_duplicate_running_or_other_tenant_jobs() -> None:
    now = datetime.now(timezone.utc)
    jobs = [
        IngestionJob(uuid4(), "tenant-a", "running", IngestionJobStatus.RUNNING, now),
        IngestionJob(uuid4(), "tenant-b", "queued", IngestionJobStatus.QUEUED, now),
    ]
    store = FakeStore(jobs)
    manager = IngestionJobManager(max_workers=1)
    try:
        assert IngestionWorker(manager, store).recover_queued(
            tenant_id="tenant-a", operation_for=lambda job: lambda: None
        ) == []
        assert store.updated == []
    finally:
        manager.close()


def test_worker_persists_fast_terminal_state_instead_of_stale_running() -> None:
    job = IngestionJob(
        job_id=uuid4(), tenant_id="tenant-a", idempotency_key="fast",
        status=IngestionJobStatus.QUEUED, created_at=datetime.now(timezone.utc),
    )
    store = FakeStore([job])
    manager = IngestionJobManager(max_workers=1)
    try:
        assert IngestionWorker(manager, store).recover_queued(
            tenant_id="tenant-a", operation_for=lambda persisted: lambda: None
        ) == [job.job_id]
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not store.updated:
            time.sleep(0.01)
        time.sleep(0.05)
        assert manager.get(tenant_id="tenant-a", job_id=job.job_id).status == IngestionJobStatus.COMPLETED
        assert store.updated[-1]["status"] == IngestionJobStatus.COMPLETED
    finally:
        manager.close()
