import shutil
import time
from pathlib import Path
from uuid import uuid4

from src.app.application.document_metadata import DocumentMetadataRegistry, DocumentStatus
from src.app.application.ingestion import IngestionJobManager, IngestionJobStatus
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage


def _finish(manager, tenant_id, job_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(tenant_id=tenant_id, job_id=job_id)
        if job and job.status in {IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def _service(root):
    jobs = IngestionJobManager(max_workers=1)
    registry = DocumentMetadataRegistry()
    return DocumentIngestionService(SecureUploadStorage(root), jobs, registry), jobs, registry


def test_document_lifecycle_reaches_active_and_reuses_hash() -> None:
    root = Path("output") / f"document-lifecycle-{uuid4().hex}"
    service, jobs, registry = _service(root)
    try:
        first = service.submit_document(
            tenant_id="tenant-a", idempotency_key="job-1", filename="a.txt",
            content=b"same", content_type="text/plain", parser_version="p1",
            chunker_version="c1", embedding_model="e1", embedding_dimension=3,
            index_version="idx-1", operation=lambda path, upload, record: "ok",
        )
        assert _finish(jobs, "tenant-a", first.job.job_id).status == IngestionJobStatus.COMPLETED
        assert registry.get(tenant_id="tenant-a", document_id=first.document.document_id).status == DocumentStatus.ACTIVE
        duplicate = service.submit_document(
            tenant_id="tenant-a", idempotency_key="job-2", filename="b.txt",
            content=b"same", content_type="text/plain", parser_version="p2",
            chunker_version="c2", embedding_model="e2", embedding_dimension=4,
            index_version="idx-2", operation=lambda path, upload, record: "bad",
        )
        assert duplicate.created is False
        assert duplicate.job is None
        assert duplicate.document.document_id == first.document.document_id
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)


def test_document_lifecycle_marks_failed_when_operation_raises() -> None:
    root = Path("output") / f"document-lifecycle-{uuid4().hex}"
    service, jobs, registry = _service(root)
    try:
        submission = service.submit_document(
            tenant_id="tenant-a", idempotency_key="job-1", filename="a.txt",
            content=b"fail", content_type="text/plain", parser_version="p1",
            chunker_version="c1", embedding_model="e1", embedding_dimension=3,
            index_version="idx-1", operation=lambda path, upload, record: 1 / 0,
        )
        assert _finish(jobs, "tenant-a", submission.job.job_id).status == IngestionJobStatus.FAILED
        assert registry.get(tenant_id="tenant-a", document_id=submission.document.document_id).status == DocumentStatus.FAILED
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)


def test_document_lifecycle_persists_original_failure_message() -> None:
    root = Path("output") / f"document-lifecycle-{uuid4().hex}"

    class Store:
        def __init__(self):
            self.errors = []

        def update_document_status(self, **kwargs):
            return None

        def create_job(self, **kwargs):
            return None

        def update_job_status(self, **kwargs):
            self.errors.append(kwargs.get("error"))
            return None

    jobs = IngestionJobManager(max_workers=1)
    store = Store()
    service = DocumentIngestionService(
        SecureUploadStorage(root), jobs, DocumentMetadataRegistry(), store
    )
    try:
        submission = service.submit_document(
            tenant_id="tenant-a", idempotency_key="job-1", filename="a.txt",
            content=b"fail", content_type="text/plain", parser_version="p1",
            chunker_version="c1", embedding_model="e1", embedding_dimension=3,
            index_version="idx-1", operation=lambda path, upload, record: (_ for _ in ()).throw(ValueError("boom")),
        )
        assert _finish(jobs, "tenant-a", submission.job.job_id).status == IngestionJobStatus.FAILED
        assert "boom" in store.errors
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)
