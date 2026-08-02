from __future__ import annotations

from typing import Any

from src.app.application.ingestion import IngestionJob, PermanentIngestionError
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from src.app.workers.celery_app import CeleryTaskPublisher, build_celery_app
from src.app.workers.runtime import CeleryTaskRuntime, TaskRuntimeConfig
from src.app.workers.tasks import register_ingestion_task
from utils.settings import get_settings


def _operation_for(_job: IngestionJob):
    """Fail closed until a deployment registers its parser/index handlers."""

    raise PermanentIngestionError(
        "worker operation registry is not configured for this deployment"
    )


def build_worker_app() -> Any:
    settings = get_settings()
    if settings.redis_url is None or settings.database_url is None:
        raise RuntimeError("REDIS_URL and DATABASE_URL are required for the worker")
    app = build_celery_app(
        settings.redis_url,
        queue=settings.worker_queue,
        task_timeout_seconds=settings.worker_task_timeout_seconds,
    )
    store = SqlAlchemyIngestionRepository(settings.database_url)
    runtime = CeleryTaskRuntime(
        store,
        _operation_for,
        config=TaskRuntimeConfig(
            timeout_seconds=settings.worker_task_timeout_seconds,
            lease_seconds=settings.worker_lease_seconds,
        ),
    )
    register_ingestion_task(
        app,
        runtime,
        retry_backoff_seconds=settings.worker_retry_backoff_seconds,
        task_timeout_seconds=settings.worker_task_timeout_seconds,
    )
    publisher = CeleryTaskPublisher(app, queue=settings.worker_queue)
    # A bounded startup sweep closes the crash window between DB commit and
    # broker publish. Claims/fencing still make duplicate delivery safe.
    for job in store.list_recoverable_jobs()[: settings.worker_claim_limit]:
        if job.status.value in {"queued", "running"}:
            publisher.dispatch(job)
    return app


celery_app = build_worker_app()
