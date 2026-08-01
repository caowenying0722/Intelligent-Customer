import threading
import time
from uuid import UUID

import pytest

from src.app.application.ingestion import (
    IngestionJobManager,
    IngestionJobStatus,
    PermanentIngestionError,
    RetryableIngestionError,
)


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
        assert (
            _wait_for(
                manager, "tenant-a", first.job_id, IngestionJobStatus.COMPLETED
            ).result
            == "ok"
        )
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
        assert _wait_for(
            manager, "tenant-a", failed.job_id, IngestionJobStatus.FAILED
        ).error
        assert "timeout" in (
            _wait_for(
                manager, "tenant-a", timed.job_id, IngestionJobStatus.FAILED
            ).error
            or ""
        )
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
        assert (
            manager.get(tenant_id="tenant-a", job_id=queued.job_id).status
            == IngestionJobStatus.CANCELLED
        )
        release.set()
    finally:
        manager.close()


def test_ingestion_manager_validates_limits() -> None:
    with pytest.raises(ValueError):
        IngestionJobManager(max_workers=0)
    with pytest.raises(ValueError):
        IngestionJobManager(timeout_seconds=0)
    with pytest.raises(ValueError):
        IngestionJobManager(max_attempts=0)


def test_ingestion_retries_retryable_errors_with_bounded_attempts() -> None:
    manager = IngestionJobManager(
        max_workers=1, max_attempts=3, retry_backoff_seconds=0
    )
    attempts = 0
    try:

        def operation():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RetryableIngestionError("temporary")
            return "ok"

        job = manager.submit(
            tenant_id="tenant-a", idempotency_key="retry", operation=operation
        )
        completed = _wait_for(
            manager, "tenant-a", job.job_id, IngestionJobStatus.COMPLETED
        )
        assert attempts == 3
        assert completed.attempt == 3
    finally:
        manager.close()


def test_running_job_cancel_is_request_and_progress_is_bounded() -> None:
    manager = IngestionJobManager(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    try:
        job = manager.submit(
            tenant_id="tenant-a",
            idempotency_key="running-cancel",
            operation=lambda: (started.set(), release.wait(1)),
        )
        assert started.wait(1)
        manager.update_progress(tenant_id="tenant-a", job_id=job.job_id, progress=40)
        assert manager.cancel(tenant_id="tenant-a", job_id=job.job_id) is True
        current = manager.get(tenant_id="tenant-a", job_id=job.job_id)
        assert current.progress == 40
        assert current.cancel_requested is True
        with pytest.raises(ValueError):
            manager.update_progress(
                tenant_id="tenant-a", job_id=job.job_id, progress=101
            )
        release.set()
    finally:
        manager.close()


def test_close_waits_for_running_job_before_returning() -> None:
    manager = IngestionJobManager(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    try:
        job = manager.submit(
            tenant_id="tenant-a",
            idempotency_key="shutdown",
            operation=lambda: (started.set(), release.wait(1), "ok")[-1],
        )
        assert started.wait(1)

        def close_manager() -> None:
            manager.close()
            closed.set()

        closer = threading.Thread(target=close_manager)
        closer.start()
        assert not closed.wait(0.05)
        release.set()
        assert closed.wait(1)
        closer.join(1)
        assert manager.get(tenant_id="tenant-a", job_id=job.job_id).status == (
            IngestionJobStatus.COMPLETED
        )
    finally:
        release.set()
        if not closed.is_set():
            manager.close()


def test_ingestion_does_not_retry_permanent_errors_and_exhaustion_fails() -> None:
    manager = IngestionJobManager(
        max_workers=1, max_attempts=2, retry_backoff_seconds=0
    )
    attempts = 0
    try:

        def permanent():
            nonlocal attempts
            attempts += 1
            raise PermanentIngestionError("bad format")

        first = manager.submit(
            tenant_id="tenant-a", idempotency_key="permanent", operation=permanent
        )
        assert _wait_for(
            manager, "tenant-a", first.job_id, IngestionJobStatus.FAILED
        ).error
        assert attempts == 1

        def transient():
            raise RetryableIngestionError("still unavailable")

        second = manager.submit(
            tenant_id="tenant-a", idempotency_key="exhaust", operation=transient
        )
        failed = _wait_for(
            manager, "tenant-a", second.job_id, IngestionJobStatus.FAILED
        )
        assert failed.attempt == 2
    finally:
        manager.close()
