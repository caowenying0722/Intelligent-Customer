import shutil
import time
from pathlib import Path
from uuid import uuid4

import pytest

from src.app.application.ingestion import IngestionJobManager, IngestionJobStatus
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage


def _wait(manager, tenant_id, job_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(tenant_id=tenant_id, job_id=job_id)
        if job and job.status in {
            IngestionJobStatus.COMPLETED,
            IngestionJobStatus.FAILED,
        }:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_document_ingestion_service_runs_validation_storage_and_job() -> None:
    root = Path("output") / f"ingestion-service-test-{uuid4().hex}"
    jobs = IngestionJobManager(max_workers=1)
    service = DocumentIngestionService(SecureUploadStorage(root), jobs)
    observed: list[bytes] = []
    try:
        job = service.submit(
            tenant_id="tenant-a",
            idempotency_key="upload-1",
            filename="manual.txt",
            content=b"payload",
            content_type="text/plain",
            operation=lambda path, upload: observed.append(path.read_bytes()),
        )
        assert (
            _wait(jobs, "tenant-a", job.job_id).status == IngestionJobStatus.COMPLETED
        )
        assert observed == [b"payload"]
        assert len(list(root.iterdir())) == 1
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)


def test_document_ingestion_idempotency_prevents_second_file() -> None:
    root = Path("output") / f"ingestion-service-test-{uuid4().hex}"
    jobs = IngestionJobManager(max_workers=1)
    service = DocumentIngestionService(SecureUploadStorage(root), jobs)
    try:
        first = service.submit(
            tenant_id="tenant-a",
            idempotency_key="same",
            filename="a.txt",
            content=b"a",
            content_type="text/plain",
            operation=lambda path, upload: None,
        )
        duplicate = service.submit(
            tenant_id="tenant-a",
            idempotency_key="same",
            filename="b.txt",
            content=b"b",
            content_type="text/plain",
            operation=lambda path, upload: None,
        )
        assert duplicate.job_id == first.job_id
        assert len(list(root.iterdir())) == 1
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)


def test_document_ingestion_rejects_invalid_upload_without_writing() -> None:
    root = Path("output") / f"ingestion-service-test-{uuid4().hex}"
    jobs = IngestionJobManager()
    service = DocumentIngestionService(SecureUploadStorage(root), jobs)
    try:
        with pytest.raises(ValueError):
            service.submit(
                tenant_id="tenant-a",
                idempotency_key="bad",
                filename="../x.txt",
                content=b"x",
                content_type="text/plain",
                operation=lambda p, u: None,
            )
        assert list(root.iterdir()) == []
    finally:
        jobs.close()
        shutil.rmtree(root, ignore_errors=True)
