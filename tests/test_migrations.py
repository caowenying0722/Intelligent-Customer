from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migration_upgrade_and_downgrade_on_empty_sqlite_database() -> None:
    database = Path("output") / "migration_smoke.db"
    database.parent.mkdir(exist_ok=True)
    if database.exists():
        database.unlink()
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert set(inspect(engine).get_table_names()) >= {
        "alembic_version",
        "conversations",
        "messages",
    }
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
    database.unlink()
