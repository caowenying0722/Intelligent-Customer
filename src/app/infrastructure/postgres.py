"""SQLAlchemy conversation adapter; PostgreSQL is the production target."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from src.app.domain.conversations import Conversation, Message


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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


class SqlAlchemyConversationRepository:
    def __init__(self, database_url: str, *, initialize_schema: bool = False):
        self.engine = create_engine(database_url, future=True)
        if initialize_schema:
            Base.metadata.create_all(self.engine)

    def create(self, tenant_id: str) -> Conversation:
        conversation = Conversation(tenant_id=tenant_id, conversation_id=uuid4())
        with Session(self.engine) as session:
            session.add(
                ConversationRow(
                    id=str(conversation.conversation_id), tenant_id=tenant_id
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
                messages=[
                    Message(
                        role=item.role, content=item.content, created_at=item.created_at
                    )
                    for item in row.messages
                ],
            )

    def append(
        self, tenant_id: str, conversation_id: UUID, role: str, content: str
    ) -> Message:
        with Session(self.engine) as session:
            row = session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == str(conversation_id),
                    ConversationRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                raise KeyError(conversation_id)
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
            session.commit()
            return message

    def close(self) -> None:
        self.engine.dispose()
