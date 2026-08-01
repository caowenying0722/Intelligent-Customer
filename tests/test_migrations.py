from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


def test_migration_upgrade_and_downgrade_on_empty_sqlite_database() -> None:
    database = Path("output") / "migration_smoke.db"
    database.parent.mkdir(exist_ok=True)
    if database.exists():
        database.unlink()
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")

    command.upgrade(config, "head")
    repository = SqlAlchemyConversationRepository(f"sqlite:///{database.as_posix()}")
    assert repository.check_ready()
    repository.close()
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert set(inspect(engine).get_table_names()) >= {
        "alembic_version",
        "conversations",
        "messages",
        "documents",
        "ingestion_jobs",
    }
    assert {
        "ix_documents_tenant_hash",
        "ix_documents_tenant_status_created",
    } <= {index["name"] for index in inspect(engine).get_indexes("documents")}
    assert {
        "ix_ingestion_jobs_tenant_status_created",
        "ux_ingestion_jobs_tenant_idempotency",
    } <= {index["name"] for index in inspect(engine).get_indexes("ingestion_jobs")}
    index_names = {index["name"] for index in inspect(engine).get_indexes("agent_runs")}
    assert {
        "ix_agent_runs_tenant_status_created",
        "ix_agent_runs_tenant_created",
    } <= index_names
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT id FROM agent_runs "
            "WHERE tenant_id = 'tenant-a' AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 10"
        ).all()
    assert "ix_agent_runs_tenant_status_created" in " ".join(
        str(row) for row in plan
    )
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    repository = SqlAlchemyConversationRepository(f"sqlite:///{database.as_posix()}")
    assert not repository.check_ready()
    repository.close()
    engine.dispose()
    database.unlink()
