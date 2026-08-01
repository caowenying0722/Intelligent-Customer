"""Composition-root helpers for selecting repository implementations."""

import os

from src.app.domain.conversations import (
    ConversationRepository,
    ConversationRepositoryProtocol,
)
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
