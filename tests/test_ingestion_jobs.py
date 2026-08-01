import threading
import time
from uuid import UUID

import pytest

from src.app.application.ingestion import IngestionJobManager, IngestionJobStatus


def _wait_for(manager, tenant_id: str, job_id: UUID, status: IngestionJobStatus):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(tenant_id=tenant_id, job_id=job_id)
        if job is not None and job.status == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {status}")


def test_ingestion_jobs_are_tenant_scoped_and_idempotent() -> None:
    manager = IngestionJobManager(max_workers=1)
    try:
        first = manager.submit(
            tenant_id="tenant-a", idempotency_key="upload-1", operation=lambda: "ok"
        )
        duplicate = manager.submit(
            tenant_id="tenant-a", idempotency_key="upload-1", operation=lambda: "bad"
        )
        assert duplicate.job_id == first.job_id
        assert manager.get(tenant_id="tenant-b", job_id=first.job_id) is None
        assert _wait_for(manager, "tenant-a", first.job_id, IngestionJobStatus.COMPLETED).result == "ok"
    finally:
        manager.close()


def test_ingestion_job_failure_and_timeout_are_recorded() -> None:
    manager = IngestionJobManager(max_workers=2, timeout_seconds=0.01)
    try:
        failed = manager.submit(
            tenant_id="tenant-a", idempotency_key="bad", operation=lambda: 1 / 0
        )
        timed = manager.submit(
            tenant_id="tenant-a",
            idempotency_key="slow",
            operation=lambda: time.sleep(0.05),
        )
        assert _wait_for(manager, "tenant-a", failed.job_id, IngestionJobStatus.FAILED).error
        assert "timeout" in (_wait_for(manager, "tenant-a", timed.job_id, IngestionJobStatus.FAILED).error or "")
    finally:
        manager.close()


def test_queued_ingestion_job_can_be_cancelled() -> None:
    manager = IngestionJobManager(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    try:
        manager.submit(
            tenant_id="tenant-a",
            idempotency_key="running",
            operation=lambda: (started.set(), release.wait(1)),
        )
        assert started.wait(1)
        queued = manager.submit(
            tenant_id="tenant-a", idempotency_key="queued", operation=lambda: None
        )
        assert manager.cancel(tenant_id="tenant-a", job_id=queued.job_id) is True
        assert manager.get(tenant_id="tenant-a", job_id=queued.job_id).status == IngestionJobStatus.CANCELLED
        release.set()
    finally:
        manager.close()


def test_ingestion_manager_validates_limits() -> None:
    with pytest.raises(ValueError):
        IngestionJobManager(max_workers=0)
    with pytest.raises(ValueError):
        IngestionJobManager(timeout_seconds=0)
