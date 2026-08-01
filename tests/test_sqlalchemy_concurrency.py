from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


def test_concurrent_appends_are_all_committed() -> None:
    database = Path("output") / "concurrent.db"
    database.parent.mkdir(exist_ok=True)
    if database.exists():
        database.unlink()
    repository = SqlAlchemyConversationRepository(
        f"sqlite+pysqlite:///{database.as_posix()}", initialize_schema=True
    )
    conversation = repository.create("tenant-a")

    def append(index: int) -> None:
        repository.append("tenant-a", conversation.conversation_id, "user", str(index))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(append, range(20)))

    loaded = repository.get("tenant-a", conversation.conversation_id)
    assert loaded is not None
    assert sorted(int(message.content) for message in loaded.messages) == list(
        range(20)
    )
    repository.close()
    database.unlink()
