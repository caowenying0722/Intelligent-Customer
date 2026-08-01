import threading
import time

from fastapi.testclient import TestClient

from src.app.application.ingestion import (
    IngestionJobManager,
    IngestionJobStatus,
    RetryableIngestionError,
)
from src.app.main import create_app
from src.app.observability.metrics import WorkerMetrics, render_prometheus


def _wait_for_status(manager, job_id, status: IngestionJobStatus):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(tenant_id="tenant-a", job_id=job_id)
        if job is not None and job.status == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {status}")


def test_worker_metrics_are_bounded_and_aggregate_only() -> None:
    metrics = WorkerMetrics()
    metrics.submitted()
    metrics.started(0.2)
    metrics.retry()
    metrics.finished("completed", 0.3)

    snapshot = metrics.snapshot()
    assert snapshot["queue_depth"] == 0
    assert snapshot["active"] == 0
    assert snapshot["submitted"] == 1
    assert snapshot["completed"] == 1
    assert snapshot["retries"] == 1
    assert snapshot["queue_wait_count"] == 1
    assert snapshot["processing_count"] == 1
    text = render_prometheus({}, {}, worker_snapshot=snapshot)
    assert "worker_queue_depth 0" in text
    assert "worker_retries_total 1" in text
    assert "tenant" not in text
    assert "job_id" not in text


def test_job_manager_records_retry_and_terminal_worker_metrics() -> None:
    metrics = WorkerMetrics()
    manager = IngestionJobManager(
        max_workers=1, max_attempts=2, retry_backoff_seconds=0, metrics=metrics
    )
    attempts = 0
    try:

        def operation():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RetryableIngestionError("temporary")
            return "ok"

        job = manager.submit(
            tenant_id="tenant-a", idempotency_key="retry", operation=operation
        )
        assert (
            _wait_for_status(manager, job.job_id, IngestionJobStatus.COMPLETED).result
            == "ok"
        )
        snapshot = metrics.snapshot()
        assert snapshot["submitted"] == 1
        assert snapshot["completed"] == 1
        assert snapshot["failed"] == 0
        assert snapshot["retries"] == 1
        assert snapshot["queue_depth"] == 0
        assert snapshot["active"] == 0
    finally:
        manager.close()


def test_cancelled_queued_job_is_counted_without_identity_labels() -> None:
    metrics = WorkerMetrics()
    manager = IngestionJobManager(max_workers=1, metrics=metrics)
    started = threading.Event()
    release = threading.Event()

    def running_operation():
        started.set()
        release.wait(1)

    try:
        running = manager.submit(
            tenant_id="tenant-a",
            idempotency_key="running",
            operation=running_operation,
        )
        assert started.wait(1)
        queued = manager.submit(
            tenant_id="tenant-a", idempotency_key="queued", operation=lambda: None
        )
        assert manager.cancel(tenant_id="tenant-a", job_id=queued.job_id)
        release.set()
        _wait_for_status(manager, running.job_id, IngestionJobStatus.COMPLETED)
        snapshot = metrics.snapshot()
        assert snapshot["submitted"] == 2
        assert snapshot["cancelled"] == 1
        assert snapshot["completed"] == 1
        assert snapshot["queue_depth"] == 0
    finally:
        release.set()
        manager.close()


def test_prometheus_endpoint_exposes_zero_worker_metrics_without_ingestion() -> None:
    response = TestClient(create_app()).get("/metrics/prometheus")

    assert response.status_code == 200
    assert "worker_queue_depth 0" in response.text
    assert "worker_jobs_failed_total 0" in response.text
