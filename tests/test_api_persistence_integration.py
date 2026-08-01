from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from src.app.main import create_app


class FakeAgent:
    def run(self, message: str) -> str:
        return f"persisted:{message}"

    def stream(self, message: str) -> list[str]:
        return [self.run(message)]


def test_api_recovers_conversation_after_application_restart() -> None:
    database = Path("output") / "api_persistence.db"
    database.parent.mkdir(exist_ok=True)
    if database.exists():
        database.unlink()
    database_url = f"sqlite+pysqlite:///{database.as_posix()}"

    migration_config = Config(str(Path("alembic.ini").resolve()))
    migration_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration_config, "head")

    with TestClient(
        create_app(chat_agent=FakeAgent(), database_url=database_url)
    ) as first:
        created = first.post(
            "/api/v1/chat",
            json={"message": "remember me"},
            headers={"x-tenant-id": "tenant-a", "x-user-id": "user-7"},
        ).json()

    with TestClient(
        create_app(chat_agent=FakeAgent(), database_url=database_url)
    ) as second:
        recovered = second.get(
            f"/api/v1/conversations/{created['conversation_id']}",
            headers={"x-tenant-id": "tenant-a"},
        )

    assert recovered.status_code == 200
    assert recovered.json()["version"] == 2
    assert recovered.json()["user_id"] == "user-7"
    assert recovered.json()["status"] == "active"
    assert [item["content"] for item in recovered.json()["messages"]] == [
        "remember me",
        "persisted:remember me",
    ]
    database.unlink()
