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
