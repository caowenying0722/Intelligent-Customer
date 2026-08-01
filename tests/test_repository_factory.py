from unittest.mock import patch

from src.app.domain.conversations import ConversationRepository
from src.app.infrastructure.factory import build_conversation_repository
from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


def test_repository_factory_defaults_to_memory() -> None:
    repository = build_conversation_repository(None)

    assert isinstance(repository, ConversationRepository)


def test_repository_factory_selects_sqlalchemy_for_explicit_url() -> None:
    repository = build_conversation_repository("sqlite+pysqlite:///:memory:")

    assert isinstance(repository, SqlAlchemyConversationRepository)
    assert repository.check_ready()
    repository.close()


def test_postgres_engine_receives_pool_and_timeout_options() -> None:
    with patch("src.app.infrastructure.postgres.create_engine") as create_engine:
        repository = SqlAlchemyConversationRepository(
            "postgresql+psycopg://user:pass@db/app",
            pool_size=7,
            max_overflow=11,
            pool_timeout=12,
            connect_timeout=13,
            isolation_level="SERIALIZABLE",
        )

    options = create_engine.call_args.kwargs
    assert options["pool_size"] == 7
    assert options["max_overflow"] == 11
    assert options["pool_timeout"] == 12
    assert options["connect_args"] == {"connect_timeout": 13}
    assert options["isolation_level"] == "SERIALIZABLE"
    repository.close()
