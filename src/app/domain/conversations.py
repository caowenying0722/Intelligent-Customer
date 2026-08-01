"""Small in-memory conversation repository for the API bootstrap phase."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
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
    version: int = 0
    user_id: str = "local"
    status: str = "active"
    messages: list[Message] = field(default_factory=list)


class ConcurrencyConflict(RuntimeError):
    """The conversation changed since the caller last read it."""


class IdempotencyConflict(RuntimeError):
    def __init__(self, run_id: UUID):
        super().__init__(run_id)
        self.run_id = run_id


class RunStateConflict(RuntimeError):
    pass


RUN_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"queued", "running", "cancelled"},
    "running": {"running", "completed", "failed", "cancelled"},
    "completed": {"completed"},
    "failed": {"failed"},
    "cancelled": {"cancelled"},
}


@dataclass(frozen=True)
class AgentRun:
    run_id: UUID
    tenant_id: str
    conversation_id: UUID
    status: str
    error: str | None = None
    idempotency_key: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        end = self.completed_at or datetime.now(tz=timezone.utc)
        if self.started_at is None:
            return None
        return max(0, int((end - self.started_at).total_seconds() * 1000))


class ConversationRepositoryProtocol(Protocol):
    def create(self, tenant_id: str, user_id: str = "local") -> Conversation: ...

    def get(self, tenant_id: str, conversation_id: UUID) -> Conversation | None: ...

    def append(
        self,
        tenant_id: str,
        conversation_id: UUID,
        role: str,
        content: str,
        expected_version: int | None = None,
    ) -> Message: ...

    def close(self) -> None: ...

    def check_ready(self) -> bool: ...

    def create_run(
        self,
        tenant_id: str,
        conversation_id: UUID,
        idempotency_key: str | None = None,
    ) -> AgentRun: ...

    def get_run(self, tenant_id: str, run_id: UUID) -> AgentRun | None: ...

    def update_run(
        self, tenant_id: str, run_id: UUID, status: str, error: str | None = None
    ) -> AgentRun: ...

    def list_runs(
        self,
        tenant_id: str,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRun]: ...


class ConversationRepository:
    """Thread-safe process-local repository; replace with PostgreSQL in stage 3."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}
        self._lock = Lock()

    def create(self, tenant_id: str, user_id: str = "local") -> Conversation:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        conversation = Conversation(
            tenant_id=tenant_id, conversation_id=uuid4(), user_id=user_id
        )
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
        self,
        tenant_id: str,
        conversation_id: UUID,
        role: str,
        content: str,
        expected_version: int | None = None,
    ) -> Message:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.tenant_id != tenant_id:
                raise KeyError(conversation_id)
            if (
                expected_version is not None
                and conversation.version != expected_version
            ):
                raise ConcurrencyConflict(conversation_id)
            message = Message(
                role=role,
                content=content,
                created_at=datetime.now(tz=timezone.utc),
            )
            conversation.messages.append(message)
            conversation.version += 1
            return message

    def close(self) -> None:
        """Keep the in-memory adapter compatible with lifecycle-managed stores."""

    def check_ready(self) -> bool:
        return True

    def create_run(
        self,
        tenant_id: str,
        conversation_id: UUID,
        idempotency_key: str | None = None,
    ) -> AgentRun:
        if self.get(tenant_id, conversation_id) is None:
            raise KeyError(conversation_id)
        run = AgentRun(
            uuid4(),
            tenant_id,
            conversation_id,
            "queued",
            idempotency_key=idempotency_key,
        )
        with self._lock:
            if not hasattr(self, "_runs"):
                self._runs: dict[UUID, AgentRun] = {}
            for existing in self._runs.values():
                if (
                    existing.tenant_id == tenant_id
                    and existing.idempotency_key == idempotency_key
                    and idempotency_key
                ):
                    raise IdempotencyConflict(existing.run_id)
            self._runs[run.run_id] = run
        return run

    def get_run(self, tenant_id: str, run_id: UUID) -> AgentRun | None:
        run = getattr(self, "_runs", {}).get(run_id)
        return run if run is not None and run.tenant_id == tenant_id else None

    def update_run(
        self, tenant_id: str, run_id: UUID, status: str, error: str | None = None
    ) -> AgentRun:
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ValueError("invalid run status")
        with self._lock:
            run = self.get_run(tenant_id, run_id)
            if run is None:
                raise KeyError(run_id)
            if status not in RUN_TRANSITIONS[run.status]:
                raise RunStateConflict(f"{run.status}->{status}")
            updated = AgentRun(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                conversation_id=run.conversation_id,
                status=status,
                error=error,
                idempotency_key=run.idempotency_key,
                created_at=run.created_at,
                started_at=run.started_at
                or (datetime.now(tz=timezone.utc) if status == "running" else None),
                completed_at=(
                    datetime.now(tz=timezone.utc)
                    if status in {"completed", "failed", "cancelled"}
                    else run.completed_at
                ),
            )
            self._runs[run_id] = updated
            return updated

    def list_runs(
        self,
        tenant_id: str,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRun]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid pagination")
        runs = [
            run
            for run in getattr(self, "_runs", {}).values()
            if run.tenant_id == tenant_id
            and (status is None or run.status == status)
            and (created_after is None or run.created_at >= created_after)
            and (created_before is None or run.created_at <= created_before)
        ]
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return runs[offset : offset + limit]
