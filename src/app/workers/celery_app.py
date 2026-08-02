from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.app.application.ingestion import IngestionJob, TaskDispatcher
from src.app.workers.contracts import TaskEnvelope

CELERY_TASK_NAME = "intelligent_customer.process_ingestion_job"


class WorkerDependencyError(RuntimeError):
    """The optional worker dependencies are not installed."""


def build_celery_app(
    redis_url: str,
    *,
    queue: str = "ingestion",
    task_timeout_seconds: float = 300.0,
    celery_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build a JSON-only Celery app with bounded broker/task settings."""

    if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
        raise ValueError("redis_url must use redis:// or rediss://")
    if not queue.strip():
        raise ValueError("queue must not be empty")
    if task_timeout_seconds <= 0:
        raise ValueError("task_timeout_seconds must be positive")
    if celery_factory is None:
        try:
            from celery import Celery
        except ModuleNotFoundError as exc:  # pragma: no cover - optional package.
            raise WorkerDependencyError(
                "Celery is optional; install requirements-worker.lock to enable workers"
            ) from exc
        celery_factory = Celery
    app = celery_factory("intelligent_customer", broker=redis_url, backend=redis_url)
    app.conf.update(
        task_default_queue=queue,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        broker_connection_timeout=5,
        broker_connection_retry_on_startup=False,
        task_soft_time_limit=int(task_timeout_seconds),
        task_time_limit=int(task_timeout_seconds) + 5,
    )
    return app


class CeleryTaskPublisher(TaskDispatcher):
    """Publish persisted jobs after their database row has been committed."""

    def __init__(self, app: Any, *, queue: str = "ingestion") -> None:
        if not queue.strip():
            raise ValueError("queue must not be empty")
        self.app = app
        self.queue = queue

    @classmethod
    def from_settings(
        cls,
        *,
        redis_url: str,
        queue: str = "ingestion",
        task_timeout_seconds: float = 300.0,
    ) -> CeleryTaskPublisher:
        return cls(
            build_celery_app(
                redis_url,
                queue=queue,
                task_timeout_seconds=task_timeout_seconds,
            ),
            queue=queue,
        )

    def dispatch(self, job: IngestionJob) -> str | None:
        envelope = TaskEnvelope.from_job(job)
        result = self.app.send_task(
            CELERY_TASK_NAME,
            kwargs={"envelope": envelope.as_dict()},
            queue=self.queue,
            retry=False,
        )
        task_id = getattr(result, "id", None)
        return str(task_id) if task_id is not None else None

    def check_ready(self) -> bool:
        """Check broker connectivity with the bounded app connection timeout."""

        connection = self.app.connection_for_read()
        try:
            connection.ensure_connection(max_retries=0)
            return True
        except Exception:  # noqa: BLE001 - readiness fails closed.
            return False
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
