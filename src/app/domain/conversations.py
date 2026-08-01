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
    conversation_id: UUID
    messages: list[Message] = field(default_factory=list)


class ConversationRepository:
    """Thread-safe process-local repository; replace with PostgreSQL in stage 3."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}
        self._lock = Lock()

    def create(self) -> Conversation:
        conversation = Conversation(conversation_id=uuid4())
        with self._lock:
            self._conversations[conversation.conversation_id] = conversation
        return conversation

    def get(self, conversation_id: UUID) -> Conversation | None:
        with self._lock:
            return self._conversations.get(conversation_id)

    def append(self, conversation_id: UUID, role: str, content: str) -> Message:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                raise KeyError(conversation_id)
            message = Message(
                role=role,
                content=content,
                created_at=datetime.now(tz=timezone.utc),
            )
            conversation.messages.append(message)
            return message
