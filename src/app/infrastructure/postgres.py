"""SQLAlchemy conversation adapter; PostgreSQL is the production target."""

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from src.app.domain.conversations import (
    RUN_TRANSITIONS,
    AgentRun,
    ConcurrencyConflict,
    Conversation,
    Message,
    RunStateConflict,
)

EXPECTED_SCHEMA_REVISION = "0012_add_ingestion_job_leases"


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(default=0)
    user_id: Mapped[str] = mapped_column(String(128), default="local")
    status: Mapped[str] = mapped_column(String(32), default="active")
    messages: Mapped[list["MessageRow"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageRow.created_at",
    )


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(
            "ix_agent_runs_tenant_status_created", "tenant_id", "status", "created_at"
        ),
        Index("ix_agent_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_hash", "tenant_id", "content_hash", unique=True),
        Index(
            "ix_documents_tenant_status_created", "tenant_id", "status", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    document_version: Mapped[int] = mapped_column(default=1)
    parser_version: Mapped[str] = mapped_column(String(64))
    chunker_version: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_dimension: Mapped[int] = mapped_column()
    index_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index(
            "ix_ingestion_jobs_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ux_ingestion_jobs_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), index=True, nullable=True
    )
    task_type: Mapped[str] = mapped_column(
        String(64), default="ingestion", server_default="ingestion"
    )
    task_payload: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(default=0)
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    error: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fence_version: Mapped[int] = mapped_column(default=0)


class SqlAlchemyConversationRepository:
    def __init__(
        self,
        database_url: str,
        *,
        initialize_schema: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
        connect_timeout: float = 10.0,
        isolation_level: str = "READ COMMITTED",
    ):
        parsed = urlparse(database_url)
        engine_options: dict[str, object] = {
            "future": True,
        }
        if parsed.scheme.startswith("postgresql"):
            engine_options.update(
                {
                    "isolation_level": isolation_level,
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_timeout": pool_timeout,
                    "connect_args": {"connect_timeout": int(connect_timeout)},
                }
            )
        self.engine = create_engine(database_url, **engine_options)
        if initialize_schema:
            Base.metadata.create_all(self.engine)

    def create(self, tenant_id: str, user_id: str = "local") -> Conversation:
        conversation = Conversation(
            tenant_id=tenant_id, conversation_id=uuid4(), user_id=user_id
        )
        with Session(self.engine) as session:
            session.add(
                ConversationRow(
                    id=str(conversation.conversation_id),
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            )
            session.commit()
        return conversation

    def get(self, tenant_id: str, conversation_id: UUID) -> Conversation | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == str(conversation_id),
                    ConversationRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                return None
            return Conversation(
                tenant_id=row.tenant_id,
                conversation_id=UUID(row.id),
                version=row.version,
                user_id=row.user_id,
                status=row.status,
                messages=[
                    Message(
                        role=item.role, content=item.content, created_at=item.created_at
                    )
                    for item in row.messages
                ],
            )

    def append(
        self,
        tenant_id: str,
        conversation_id: UUID,
        role: str,
        content: str,
        expected_version: int | None = None,
    ) -> Message:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("unsupported message role")
        if not content or len(content) > 4000:
            raise ValueError("message content must contain 1-4000 characters")
        with Session(self.engine) as session:
            row = session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == str(conversation_id),
                    ConversationRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                raise KeyError(conversation_id)
            if expected_version is not None and row.version != expected_version:
                raise ConcurrencyConflict(conversation_id)
            message = Message(
                role=role, content=content, created_at=datetime.now().astimezone()
            )
            row.messages.append(
                MessageRow(
                    id=str(uuid4()),
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                )
            )
            row.version += 1
            session.commit()
            return message

    def close(self) -> None:
        self.engine.dispose()

    def check_ready(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            if not inspect(connection).has_table("alembic_version"):
                return False
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        return version == EXPECTED_SCHEMA_REVISION

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
        with Session(self.engine) as session:
            if idempotency_key:
                existing = session.scalar(
                    select(AgentRunRow).where(
                        AgentRunRow.tenant_id == tenant_id,
                        AgentRunRow.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    from src.app.domain.conversations import IdempotencyConflict

                    raise IdempotencyConflict(UUID(existing.id))
            session.add(
                AgentRunRow(
                    id=str(run.run_id),
                    tenant_id=tenant_id,
                    conversation_id=str(conversation_id),
                    status=run.status,
                    created_at=run.created_at,
                    idempotency_key=idempotency_key,
                )
            )
            session.commit()
        return run

    def get_run(self, tenant_id: str, run_id: UUID) -> AgentRun | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(AgentRunRow).where(
                    AgentRunRow.id == str(run_id), AgentRunRow.tenant_id == tenant_id
                )
            )
            if row is None:
                return None
            return AgentRun(
                run_id=UUID(row.id),
                tenant_id=row.tenant_id,
                conversation_id=UUID(row.conversation_id),
                status=row.status,
                error=row.error,
                idempotency_key=row.idempotency_key,
                created_at=row.created_at,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )

    def update_run(
        self, tenant_id: str, run_id: UUID, status: str, error: str | None = None
    ) -> AgentRun:
        if status not in RUN_TRANSITIONS:
            raise ValueError("invalid run status")
        with Session(self.engine) as session:
            row = session.scalar(
                select(AgentRunRow).where(
                    AgentRunRow.id == str(run_id), AgentRunRow.tenant_id == tenant_id
                )
            )
            if row is None:
                raise KeyError(run_id)
            if status not in RUN_TRANSITIONS[row.status]:
                raise RunStateConflict(f"{row.status}->{status}")
            row.status = status
            row.error = error
            if status == "running" and row.started_at is None:
                row.started_at = datetime.now().astimezone()
            if (
                status in {"completed", "failed", "cancelled"}
                and row.completed_at is None
            ):
                row.completed_at = datetime.now().astimezone()
            session.commit()
            return AgentRun(
                run_id=UUID(row.id),
                tenant_id=row.tenant_id,
                conversation_id=UUID(row.conversation_id),
                status=row.status,
                error=row.error,
                idempotency_key=row.idempotency_key,
                created_at=row.created_at,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )

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
        statement = select(AgentRunRow).where(AgentRunRow.tenant_id == tenant_id)
        if status is not None:
            statement = statement.where(AgentRunRow.status == status)
        if created_after is not None:
            statement = statement.where(AgentRunRow.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(AgentRunRow.created_at <= created_before)
        with Session(self.engine) as session:
            rows = session.scalars(
                statement.order_by(AgentRunRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [
                AgentRun(
                    run_id=UUID(row.id),
                    tenant_id=row.tenant_id,
                    conversation_id=UUID(row.conversation_id),
                    status=row.status,
                    error=row.error,
                    idempotency_key=row.idempotency_key,
                    created_at=row.created_at,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                )
                for row in rows
            ]
