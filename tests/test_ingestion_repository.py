from pathlib import Path

from src.app.application.document_metadata import DocumentMetadataRegistry, DocumentStatus
from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.application.uploads import validate_upload
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from uuid import uuid4
from datetime import datetime, timezone


def test_sqlalchemy_ingestion_repository_recovers_documents_and_jobs() -> None:
    database = Path("output") / "ingestion_repository.db"
    if database.exists():
        database.unlink()
    url = f"sqlite:///{database.as_posix()}"
    first = SqlAlchemyIngestionRepository(url, initialize_schema=True)
    upload = validate_upload("manual.txt", b"payload", "text/plain")
    registry = DocumentMetadataRegistry()
    record, _ = registry.register(
        tenant_id="tenant-a", upload=upload, parser_version="p1", chunker_version="c1",
        embedding_model="e1", embedding_dimension=3, index_version="idx-1",
    )
    first.create_document(record)
    job = IngestionJob(
        job_id=uuid4(), tenant_id="tenant-a", idempotency_key="job-1",
        status=IngestionJobStatus.QUEUED, created_at=datetime.now(timezone.utc),
    )
    first.create_job(job=job, document_id=record.document_id)
    first.close()

    second = SqlAlchemyIngestionRepository(url)
    try:
        recovered = second.get_document(tenant_id="tenant-a", document_id=record.document_id)
        assert recovered is not None
        assert recovered.content_hash == record.content_hash
        assert second.get_document(tenant_id="tenant-b", document_id=record.document_id) is None
        recovered_job = second.get_job(tenant_id="tenant-a", job_id=job.job_id)
        assert recovered_job is not None
        assert recovered_job.status == IngestionJobStatus.QUEUED
        assert second.update_document_status(
            tenant_id="tenant-a", document_id=record.document_id, status=DocumentStatus.ACTIVE
        ).status == DocumentStatus.ACTIVE
    finally:
        second.close()
        database.unlink()
