from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobManager,
    IngestionJobStatus,
    IngestionLease,
    PermanentIngestionError,
    RetryableIngestionError,
    TaskDispatcher,
)
from src.app.workers.celery_app import (
    CELERY_TASK_NAME,
    CeleryTaskPublisher,
    build_celery_app,
)
from src.app.workers.contracts import InvalidTaskEnvelope, TaskEnvelope
from src.app.workers.runtime import (
    CeleryTaskRuntime,
    RetryableTaskFailure,
    TaskRuntimeConfig,
    TaskTimeoutError,
)
from src.app.workers.tasks import bounded_retry_delay, register_ingestion_task


def _job(
    *, status: IngestionJobStatus = IngestionJobStatus.QUEUED, attempt: int = 0
) -> IngestionJob:
    return IngestionJob(
        job_id=uuid4(),
        tenant_id="tenant-a",
        idempotency_key="idem-1",
        status=status,
        created_at=datetime.now(timezone.utc),
        attempt=attempt,
        task_type="document_ingestion",
        task_payload="payload-1",
    )


class FakeTaskResult:
    id = "task-1"


class FakeCeleryApp:
    def __init__(self) -> None:
        self.conf: dict[str, Any] = {}
        self.sent: list[dict] = []
        self.task_function: Any | None = None

    def send_task(self, name, **kwargs):
        self.sent.append({"name": name, **kwargs})
        return FakeTaskResult()

    def task(self, **kwargs):
        def decorator(function):
            function.task_options = kwargs
            self.task_function = function
            return function

        return decorator


class FakeStore:
    def __init__(self, job: IngestionJob) -> None:
        self.job = job
        self.lease: IngestionLease | None = None
        self.progress: list[int] = []

    def get_job(self, *, tenant_id: str, job_id):
        if tenant_id != self.job.tenant_id or job_id != self.job.job_id:
            return None
        return self.job

    def claim_job(self, *, tenant_id, job_id, worker_id, lease_seconds):
        if self.job.status != IngestionJobStatus.QUEUED:
            return None
        self.job = replace(self.job, status=IngestionJobStatus.RUNNING)
        self.lease = IngestionLease(
            job=self.job,
            worker_id=worker_id,
            lease_token="lease-1",
            fence_version=1,
        )
        return self.lease

    def update_progress(self, *, tenant_id, job_id, progress):
        self.progress.append(progress)
        self.job = replace(self.job, progress=progress)
        return self.job

    def complete_claimed_job(self, *, status, error=None, attempt=None, **kwargs):
        assert self.lease is not None
        self.job = replace(
            self.job,
            status=status,
            error=error,
            attempt=attempt if attempt is not None else self.job.attempt,
        )
        return self.job

    def release_claimed_job(self, *, attempt, error=None, **kwargs):
        self.job = replace(
            self.job,
            status=IngestionJobStatus.QUEUED,
            attempt=attempt,
            error=error,
        )
        self.lease = None
        return self.job


def test_task_envelope_round_trip_is_json_safe() -> None:
    envelope = TaskEnvelope.from_job(_job())
    assert TaskEnvelope.from_mapping(envelope.as_dict()) == envelope
    with pytest.raises(InvalidTaskEnvelope):
        TaskEnvelope.from_mapping({"job_id": "not-a-uuid"})


def test_celery_publisher_sends_only_identity_envelope() -> None:
    app = FakeCeleryApp()
    publisher = CeleryTaskPublisher(app, queue="ingestion")
    task_id = publisher.dispatch(_job())

    assert task_id == "task-1"
    assert app.sent[0]["name"] == CELERY_TASK_NAME
    assert app.sent[0]["queue"] == "ingestion"
    assert app.sent[0]["retry"] is False
    assert set(app.sent[0]["kwargs"]["envelope"]) == {
        "job_id",
        "tenant_id",
        "idempotency_key",
        "task_type",
        "task_payload",
        "max_attempts",
    }


def test_manager_external_dispatch_does_not_run_operation_in_api_process() -> None:
    published: list[IngestionJob] = []

    class Dispatcher:
        def dispatch(self, job: IngestionJob) -> str:
            published.append(job)
            return "task-1"

    manager = IngestionJobManager(max_workers=1, dispatcher=Dispatcher())
    calls: list[str] = []
    try:
        job = manager.submit(
            tenant_id="tenant-a",
            idempotency_key="external-1",
            operation=lambda: calls.append("must-not-run"),
        )
        assert job.status == IngestionJobStatus.QUEUED
        assert calls == []
        assert [entry.job_id for entry in published] == [job.job_id]
    finally:
        manager.close()


def test_runtime_claims_completes_and_is_idempotent() -> None:
    persisted = _job()
    store = FakeStore(persisted)
    runtime = CeleryTaskRuntime(
        store,
        lambda _job: lambda: "private-result",
        config=TaskRuntimeConfig(timeout_seconds=1, lease_seconds=2, worker_id="w1"),
    )
    envelope = TaskEnvelope.from_job(persisted)

    result = runtime.execute(envelope)
    duplicate = runtime.execute(envelope)

    assert result["status"] == "completed"
    assert result["attempt"] == 1
    assert duplicate["status"] == "completed"
    assert duplicate["attempt"] == 1
    assert store.progress == [0, 100]
    assert "private-result" not in str(result)


def test_runtime_releases_retryable_failure_and_bounds_attempts() -> None:
    persisted = _job()
    store = FakeStore(persisted)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableIngestionError("temporary provider response")

    runtime = CeleryTaskRuntime(
        store,
        lambda _job: operation,
        config=TaskRuntimeConfig(timeout_seconds=1, lease_seconds=2, worker_id="w1"),
    )
    envelope = replace(TaskEnvelope.from_job(persisted), max_attempts=2)

    with pytest.raises(RetryableTaskFailure):
        runtime.execute(envelope)
    assert store.job.status == IngestionJobStatus.QUEUED
    assert store.job.attempt == 1
    assert runtime.execute(envelope)["status"] == "completed"


def test_runtime_timeout_marks_safe_failure() -> None:
    persisted = _job()
    store = FakeStore(persisted)
    runtime = CeleryTaskRuntime(
        store,
        lambda _job: lambda: time.sleep(0.1),
        config=TaskRuntimeConfig(timeout_seconds=0.01, lease_seconds=1, worker_id="w1"),
    )

    with pytest.raises(TaskTimeoutError):
        runtime.execute(TaskEnvelope.from_job(persisted))
    assert store.job.status == IngestionJobStatus.FAILED
    assert store.job.error == "task timeout"


def test_runtime_rejects_mismatched_tenant_or_task_identity() -> None:
    persisted = _job()
    store = FakeStore(persisted)
    runtime = CeleryTaskRuntime(store, lambda _job: lambda: None)
    envelope = replace(TaskEnvelope.from_job(persisted), tenant_id="tenant-b")

    with pytest.raises(PermanentIngestionError):
        runtime.execute(envelope)
    assert store.job.status == IngestionJobStatus.QUEUED


def test_task_registration_declares_late_ack_and_bounded_retry() -> None:
    app = FakeCeleryApp()
    store = FakeStore(_job())
    runtime = CeleryTaskRuntime(store, lambda _job: lambda: None)
    task = register_ingestion_task(
        app, runtime, retry_backoff_seconds=2, task_timeout_seconds=12
    )

    registered = app.task_function
    assert registered is not None
    assert task is registered
    assert registered.task_options["acks_late"] is True
    assert registered.task_options["reject_on_worker_lost"] is True
    assert registered.task_options["soft_time_limit"] == 12
    assert bounded_retry_delay(1, base_seconds=2) == 2
    assert bounded_retry_delay(10, base_seconds=2) == 300
    assert 2 < bounded_retry_delay(1, base_seconds=2, jitter_key="job-a") <= 2.4


def test_build_celery_app_uses_json_and_bounded_settings() -> None:
    app = FakeCeleryApp()
    built = build_celery_app(
        "redis://redis:6379/0",
        queue="ingestion",
        task_timeout_seconds=30,
        celery_factory=lambda *args, **kwargs: app,
    )
    assert built is app
    assert app.conf["accept_content"] == ["json"]
    assert app.conf["task_acks_late"] is True
    assert app.conf["task_reject_on_worker_lost"] is True
    assert app.conf["task_time_limit"] == 35


def test_task_dispatcher_protocol_is_runtime_checkable_by_shape() -> None:
    class Dispatcher:
        def dispatch(self, job: IngestionJob) -> str:
            return str(job.job_id)

    dispatcher: TaskDispatcher = Dispatcher()
    assert dispatcher.dispatch(_job())
