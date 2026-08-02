from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.app.workers.celery_app import CELERY_TASK_NAME
from src.app.workers.contracts import TaskEnvelope
from src.app.workers.runtime import (
    CeleryTaskRuntime,
    RetryableTaskFailure,
)


def bounded_retry_delay(attempt: int, *, base_seconds: float = 1.0) -> int:
    """Return a bounded deterministic countdown; jitter belongs at deployment edge."""

    if attempt < 1 or base_seconds < 0:
        raise ValueError("attempt must be positive and base_seconds non-negative")
    return min(300, int(base_seconds * (2 ** (attempt - 1))))


def register_ingestion_task(
    app: Any,
    runtime: CeleryTaskRuntime,
    *,
    retry_backoff_seconds: float = 1.0,
    task_timeout_seconds: float = 300.0,
) -> Any:
    """Register one task with explicit late-ack and worker-loss semantics."""

    if retry_backoff_seconds < 0 or task_timeout_seconds <= 0:
        raise ValueError("invalid worker retry/timeout configuration")

    @app.task(
        bind=True,
        name=CELERY_TASK_NAME,
        acks_late=True,
        reject_on_worker_lost=True,
        soft_time_limit=int(task_timeout_seconds),
        time_limit=int(task_timeout_seconds) + 5,
    )
    def process_ingestion_job(
        task_self: Any, *, envelope: dict[str, Any]
    ) -> dict[str, Any]:
        parsed = TaskEnvelope.from_mapping(envelope)
        try:
            return runtime.execute(parsed)
        except RetryableTaskFailure as exc:
            raise task_self.retry(
                exc=RuntimeError("retryable ingestion task"),
                countdown=bounded_retry_delay(
                    exc.attempt, base_seconds=retry_backoff_seconds
                ),
                max_retries=parsed.max_attempts - 1,
            )

    return process_ingestion_job


def register_task_from_factory(
    app: Any,
    runtime_factory: Callable[[], CeleryTaskRuntime],
    *,
    retry_backoff_seconds: float = 1.0,
    task_timeout_seconds: float = 300.0,
) -> Any:
    """Test-friendly lazy runtime registration; no DB is opened at import time."""

    return register_ingestion_task(
        app,
        runtime_factory(),
        retry_backoff_seconds=retry_backoff_seconds,
        task_timeout_seconds=task_timeout_seconds,
    )
