import base64
import shutil
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.app.application.document_metadata import DocumentMetadataRegistry
from src.app.application.ingestion import IngestionJobManager
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.upload_storage import SecureUploadStorage
from src.app.main import create_app


def test_document_upload_and_job_query_api_contract() -> None:
    storage_root = Path("output") / f"api-upload-{uuid4().hex}"
    jobs = IngestionJobManager(max_workers=1)
    service = DocumentIngestionService(
        SecureUploadStorage(storage_root), jobs, DocumentMetadataRegistry()
    )
    app = create_app(
        ingestion_service=service,
        ingestion_operation=lambda path, upload, record: None,
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/documents",
                headers={"x-tenant-id": "tenant-a"},
                json={
                    "filename": "manual.txt",
                    "content_base64": base64.b64encode(b"hello").decode(),
                    "content_type": "text/plain",
                    "idempotency_key": "upload-1",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["job_id"]
            document = client.get(
                f"/api/v1/documents/{payload['document_id']}",
                headers={"x-tenant-id": "tenant-a"},
            )
            assert document.status_code == 200
            job = client.get(
                f"/api/v1/jobs/{payload['job_id']}",
                headers={"x-tenant-id": "tenant-a"},
            )
            assert job.status_code == 200
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and client.get(
                f"/api/v1/jobs/{payload['job_id']}", headers={"x-tenant-id": "tenant-a"}
            ).json()["status"] != "completed":
                time.sleep(0.01)
            assert client.get(
                f"/api/v1/documents/{payload['document_id']}",
                headers={"x-tenant-id": "tenant-b"},
            ).status_code == 404
    finally:
        service.close()
        shutil.rmtree(storage_root, ignore_errors=True)


def test_document_upload_requires_injected_processor() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/documents",
            json={
                "filename": "manual.txt",
                "content_base64": base64.b64encode(b"hello").decode(),
                "idempotency_key": "upload-1",
            },
        )
    assert response.status_code == 503
    assert response.json()["code"] == "ingestion_unavailable"
