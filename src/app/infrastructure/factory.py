"""Composition-root helpers for selecting repository implementations."""

import os
from pathlib import Path

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJobManager
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage
from src.app.domain.approvals import (
    ApprovalRepositoryProtocol,
    InMemoryApprovalRepository,
)
from src.app.domain.conversations import (
    ConversationRepository,
    ConversationRepositoryProtocol,
)
from src.app.infrastructure.approvals import SqlAlchemyApprovalRepository
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from src.app.infrastructure.postgres import SqlAlchemyConversationRepository
from utils.settings import get_settings


def build_conversation_repository(
    database_url: str | None = None,
) -> ConversationRepositoryProtocol:
    """Select SQLAlchemy only when an explicit database URL is configured."""
    configured_url = database_url or os.getenv("DATABASE_URL")
    if configured_url:
        settings = get_settings()
        return SqlAlchemyConversationRepository(
            configured_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            connect_timeout=settings.database_connect_timeout_seconds,
            isolation_level=settings.database_isolation_level,
        )
    return ConversationRepository()


def build_approval_repository(
    conversation_repository: ConversationRepositoryProtocol,
) -> ApprovalRepositoryProtocol:
    """Share the SQLAlchemy engine when durable conversations are configured."""

    engine = getattr(conversation_repository, "engine", None)
    if engine is not None:
        return SqlAlchemyApprovalRepository(engine)
    return InMemoryApprovalRepository()


def build_document_ingestion_service(
    *, database_url: str | None = None, storage_root: str | Path | None = None
) -> DocumentIngestionService:
    """Build memory or SQL-backed ingestion dependencies from explicit configuration."""
    configured_url = database_url or os.getenv("DATABASE_URL")
    settings = get_settings()
    selected_storage_root = storage_root or settings.upload_storage_root
    dispatcher = None
    if settings.ingestion_worker_backend == "celery":
        if settings.redis_url is None:
            raise ValueError("REDIS_URL is required for the Celery ingestion backend")
        from src.app.workers.celery_app import CeleryTaskPublisher

        dispatcher = CeleryTaskPublisher.from_settings(
            redis_url=settings.redis_url,
            queue=settings.worker_queue,
            task_timeout_seconds=settings.worker_task_timeout_seconds,
        )
    jobs = IngestionJobManager(
        max_attempts=settings.worker_max_attempts,
        timeout_seconds=settings.worker_task_timeout_seconds,
        retry_backoff_seconds=settings.worker_retry_backoff_seconds,
        dispatcher=dispatcher,
    )
    if configured_url:
        repository = SqlAlchemyIngestionRepository(configured_url)
        return DocumentIngestionService(
            SecureUploadStorage(selected_storage_root), jobs, repository, repository
        )
    return DocumentIngestionService(
        SecureUploadStorage(selected_storage_root), jobs, DocumentMetadataRegistry()
    )
