from uuid import UUID

from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


def test_sqlalchemy_repository_persists_order_and_tenant_boundary() -> None:
    repository = SqlAlchemyConversationRepository(
        "sqlite+pysqlite:///:memory:", initialize_schema=True
    )
    created = repository.create("tenant-a")
    repository.append("tenant-a", created.conversation_id, "user", "hello")
    repository.append("tenant-a", created.conversation_id, "assistant", "world")

    loaded = repository.get("tenant-a", UUID(str(created.conversation_id)))
    assert loaded is not None
    assert [message.content for message in loaded.messages] == ["hello", "world"]
    assert repository.get("tenant-b", created.conversation_id) is None
    repository.close()


def test_invalid_message_is_rejected_before_persisting() -> None:
    repository = SqlAlchemyConversationRepository(
        "sqlite+pysqlite:///:memory:", initialize_schema=True
    )
    created = repository.create("tenant-a")

    try:
        repository.append("tenant-a", created.conversation_id, "tool", "bad role")
    except ValueError as exc:
        assert "role" in str(exc)
    else:
        raise AssertionError("invalid role must be rejected")

    loaded = repository.get("tenant-a", created.conversation_id)
    assert loaded is not None
    assert loaded.messages == []
    repository.close()
