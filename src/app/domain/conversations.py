"""Small in-memory conversation repository for the API bootstrap phase."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    created_at: datetime


@dataclass
class Conversation:
    tenant_id: str
    conversation_id: UUID
    messages: list[Message] = field(default_factory=list)


class ConversationRepository:
    """Thread-safe process-local repository; replace with PostgreSQL in stage 3."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}
        self._lock = Lock()

    def create(self, tenant_id: str) -> Conversation:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        conversation = Conversation(tenant_id=tenant_id, conversation_id=uuid4())
        with self._lock:
            self._conversations[conversation.conversation_id] = conversation
        return conversation

    def get(self, tenant_id: str, conversation_id: UUID) -> Conversation | None:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                return None
            return conversation

    def append(
        self, tenant_id: str, conversation_id: UUID, role: str, content: str
    ) -> Message:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise KeyError(conversation_id)
            message = Message(
                role=role,
                content=content,
                created_at=datetime.now(tz=timezone.utc),
            )
            conversation.messages.append(message)
            return message
