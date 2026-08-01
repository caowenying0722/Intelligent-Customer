"""Composition-root helpers for selecting repository implementations."""

import os
from pathlib import Path

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJobManager
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage
from src.app.domain.conversations import (
    ConversationRepository,
    ConversationRepositoryProtocol,
)
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


def build_document_ingestion_service(
    *, database_url: str | None = None, storage_root: str | Path = "output/uploads"
) -> DocumentIngestionService:
    """Build memory or SQL-backed ingestion dependencies from explicit configuration."""
    configured_url = database_url or os.getenv("DATABASE_URL")
    jobs = IngestionJobManager()
    if configured_url:
        repository = SqlAlchemyIngestionRepository(configured_url)
        return DocumentIngestionService(
            SecureUploadStorage(storage_root), jobs, repository, repository
        )
    return DocumentIngestionService(
        SecureUploadStorage(storage_root), jobs, DocumentMetadataRegistry()
    )
