import threading
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.application.uploads import validate_upload
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from src.app.main import create_app


def test_api_database_url_recovers_document_query_without_processor() -> None:
    database = Path("output") / "ingestion-api-persistence.db"
    if database.exists():
        database.unlink()
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    url = f"sqlite:///{database.as_posix()}"
    repository = SqlAlchemyIngestionRepository(url)
    upload = validate_upload("manual.txt", b"persisted", "text/plain")
    record, _ = DocumentMetadataRegistry().register(
        tenant_id="tenant-a",
        upload=upload,
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-1",
    )
    repository.create_document(record)
    repository.close()
    app = create_app(database_url=url)
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/documents/{record.document_id}",
            headers={"x-tenant-id": "tenant-a"},
        )
        assert response.status_code == 200
        assert response.json()["content_hash"] == upload.sha256
        unavailable = client.post(
            "/api/v1/documents",
            headers={"x-tenant-id": "tenant-a"},
            json={
                "filename": "a.txt",
                "content_base64": "eA==",
                "idempotency_key": "x",
            },
        )
        assert unavailable.status_code == 503
    database.unlink()


def test_api_database_url_persists_index_rebuild_job() -> None:
    database = Path("output") / "index-rebuild-api-persistence.db"
    if database.exists():
        database.unlink()
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    url = f"sqlite:///{database.as_posix()}"
    app = create_app(
        database_url=url,
        index_rebuild_operation=lambda _tenant, version: None,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/indexes/rebuild",
            headers={"x-tenant-id": "tenant-a", "idempotency-key": "rebuild-1"},
            json={"index_version": "v2"},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        queried = client.get(
            f"/api/v1/jobs/{job_id}", headers={"x-tenant-id": "tenant-a"}
        )
        assert queried.status_code == 200
    database.unlink()


def test_api_database_url_reuses_persisted_rebuild_idempotency() -> None:
    database = Path("output") / "index-rebuild-api-idempotency.db"
    try:
        if database.exists():
            database.unlink()
        config = Config(str(Path("alembic.ini").resolve()))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
        command.upgrade(config, "head")
        url = f"sqlite:///{database.as_posix()}"
        calls = []
        app = create_app(
            database_url=url,
            index_rebuild_operation=lambda _tenant, version: calls.append(version),
        )
        with TestClient(app) as client:
            headers = {"x-tenant-id": "tenant-a", "idempotency-key": "rebuild-1"}
            first = client.post(
                "/api/v1/indexes/rebuild", headers=headers, json={"index_version": "v2"}
            )
            second = client.post(
                "/api/v1/indexes/rebuild", headers=headers, json={"index_version": "v2"}
            )
            assert first.status_code == second.status_code == 200
            assert first.json()["job_id"] == second.json()["job_id"]
        assert calls == ["v2"]
    finally:
        if database.exists():
            database.unlink()


def test_lifespan_recovers_persisted_index_rebuild_job() -> None:
    database = Path("output") / "index-rebuild-recovery.db"
    try:
        if database.exists():
            database.unlink()
        config = Config(str(Path("alembic.ini").resolve()))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
        command.upgrade(config, "head")
        url = f"sqlite:///{database.as_posix()}"
        repository = SqlAlchemyIngestionRepository(url)
        from datetime import datetime, timezone

        job = IngestionJob(
            job_id=uuid4(),
            tenant_id="tenant-a",
            idempotency_key="recover-1",
            status=IngestionJobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
            task_type="index_rebuild",
            task_payload="v3",
        )
        repository.create_job(job=job)
        repository.close()
        seen = []
        done = threading.Event()

        def rebuild(_tenant, version):
            seen.append(version)
            done.set()

        app = create_app(database_url=url, index_rebuild_operation=rebuild)
        with TestClient(app):
            assert done.wait(1)
        assert seen == ["v3"]
    finally:
        if database.exists():
            database.unlink()
