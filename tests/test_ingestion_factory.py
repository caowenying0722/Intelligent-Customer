import shutil
import time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from src.app.infrastructure.factory import build_document_ingestion_service
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository


def test_ingestion_factory_selects_sql_repository_and_recovers_state() -> None:
    database = Path("output") / "ingestion_factory.db"
    storage = Path("output") / f"ingestion-factory-storage-{uuid4().hex}"
    if database.exists():
        database.unlink()
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    service = build_document_ingestion_service(
        database_url=f"sqlite:///{database.as_posix()}", storage_root=storage
    )
    try:
        submission = service.submit_document(
            tenant_id="tenant-a",
            idempotency_key="factory-job",
            filename="a.txt",
            content=b"factory",
            content_type="text/plain",
            parser_version="p1",
            chunker_version="c1",
            embedding_model="e1",
            embedding_dimension=3,
            index_version="idx-1",
            operation=lambda path, upload, record: None,
        )
        assert submission.job is not None
        deadline = time.monotonic() + 2
        repository = SqlAlchemyIngestionRepository(f"sqlite:///{database.as_posix()}")
        try:
            while time.monotonic() < deadline:
                job = repository.get_job(
                    tenant_id="tenant-a", job_id=submission.job.job_id
                )
                if job and job.status.value == "completed":
                    break
                time.sleep(0.01)
            assert job is not None
            assert job.status.value == "completed"
            document = repository.get_document(
                tenant_id="tenant-a", document_id=submission.document.document_id
            )
            assert document is not None
            assert document.status.value == "active"
        finally:
            repository.close()
    finally:
        service.close()
        shutil.rmtree(storage, ignore_errors=True)
        database.unlink()
