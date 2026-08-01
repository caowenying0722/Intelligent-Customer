import base64
import shutil
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJobManager
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage
from src.app.main import create_app


def test_document_rebuild_cancel_delete_end_to_end() -> None:
    root = Path("output") / f"ingestion-e2e-{uuid4().hex}"
    jobs = IngestionJobManager(max_workers=1)
    service = DocumentIngestionService(
        SecureUploadStorage(root), jobs, DocumentMetadataRegistry()
    )
    release_upload = threading.Event()
    upload_started = threading.Event()
    app = create_app(
        ingestion_service=service,
        ingestion_operation=lambda path, upload, record: (
            upload_started.set(),
            release_upload.wait(1),
        ),
        index_rebuild_operation=lambda version: None,
    )
    try:
        with TestClient(app) as client:
            uploaded = client.post(
                "/api/v1/documents",
                headers={"x-tenant-id": "tenant-a", "idempotency-key": "doc-1"},
                json={
                    "filename": "guide.txt",
                    "content_base64": base64.b64encode(b"guide").decode(),
                    "content_type": "text/plain",
                },
            )
            assert uploaded.status_code == 200
            document_id = uploaded.json()["document_id"]
            assert upload_started.wait(1)

            rebuild = client.post(
                "/api/v1/indexes/rebuild",
                headers={"x-tenant-id": "tenant-a", "idempotency-key": "idx-1"},
                json={"index_version": "v2"},
            )
            assert rebuild.status_code == 200
            cancelled = client.post(
                f"/api/v1/jobs/{rebuild.json()['job_id']}/cancel",
                headers={"x-tenant-id": "tenant-a"},
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"

            release_upload.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                status = client.get(
                    f"/api/v1/jobs/{uploaded.json()['job_id']}",
                    headers={"x-tenant-id": "tenant-a"},
                ).json()["status"]
                if status == "completed":
                    break
                time.sleep(0.01)
            deleted = client.delete(
                f"/api/v1/documents/{document_id}",
                headers={"x-tenant-id": "tenant-a"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["status"] == "deleted"
            assert (
                client.get(
                    f"/api/v1/documents/{document_id}",
                    headers={"x-tenant-id": "tenant-b"},
                ).status_code
                == 404
            )
            assert UUID(document_id)
    finally:
        release_upload.set()
        service.close()
        shutil.rmtree(root, ignore_errors=True)
