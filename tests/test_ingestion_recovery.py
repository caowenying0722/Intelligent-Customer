from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.application.uploads import validate_upload
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository


def test_persisted_jobs_support_cancel_and_orphan_recovery() -> None:
    database = Path("output") / "ingestion_recovery.db"
    if database.exists():
        database.unlink()
    repository = SqlAlchemyIngestionRepository(
        f"sqlite:///{database.as_posix()}", initialize_schema=True
    )
    upload = validate_upload("a.txt", b"a", "text/plain")
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
    queued = IngestionJob(
        job_id=uuid4(),
        tenant_id="tenant-a",
        idempotency_key="queued",
        status=IngestionJobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
    )
    running = IngestionJob(
        job_id=uuid4(),
        tenant_id="tenant-a",
        idempotency_key="running",
        status=IngestionJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc),
    )
    repository.create_job(job=queued, document_id=record.document_id)
    repository.create_job(job=running, document_id=record.document_id)
    try:
        cancelled = repository.request_cancel(
            tenant_id="tenant-a", job_id=queued.job_id
        )
        assert cancelled.status == IngestionJobStatus.CANCELLED
        recoverable = repository.list_recoverable_jobs(tenant_id="tenant-a")
        assert [job.job_id for job in recoverable] == [running.job_id]
        assert repository.fail_orphaned_jobs() == 1
        failed = repository.get_job(tenant_id="tenant-a", job_id=running.job_id)
        assert failed is not None
        assert failed.status == IngestionJobStatus.FAILED
        repository.update_progress(
            tenant_id="tenant-a", job_id=running.job_id, progress=42
        )
        repository.update_job_status(
            tenant_id="tenant-a",
            job_id=running.job_id,
            status=IngestionJobStatus.FAILED,
            error="final failure",
            attempt=3,
        )
        checked = repository.get_job(tenant_id="tenant-a", job_id=running.job_id)
        assert checked is not None
        assert checked.progress == 42
        assert checked.attempt == 3
        assert checked.error == "final failure"
    finally:
        repository.close()
        database.unlink()
