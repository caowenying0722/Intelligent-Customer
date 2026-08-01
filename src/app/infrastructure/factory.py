"""Composition-root helpers for selecting repository implementations."""

import os

from src.app.domain.conversations import (
    ConversationRepository,
    ConversationRepositoryProtocol,
)
from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


def build_conversation_repository(
    database_url: str | None = None,
) -> ConversationRepositoryProtocol:
    """Select SQLAlchemy only when an explicit database URL is configured."""
    configured_url = database_url or os.getenv("DATABASE_URL")
    if configured_url:
        return SqlAlchemyConversationRepository(configured_url)
    return ConversationRepository()
