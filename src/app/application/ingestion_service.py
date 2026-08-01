"""Application service joining upload validation, storage and background jobs."""

from __future__ import annotations

import threading
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.app.application.ingestion import IngestionJob, IngestionJobManager
from src.app.application.document_metadata import (
    DocumentMetadataRegistry,
    DocumentRecord,
    DocumentStatus,
)
from src.app.application.upload_storage import SecureUploadStorage
from src.app.application.uploads import ValidatedUpload, validate_upload


@dataclass(frozen=True)
class DocumentSubmission:
    document: DocumentRecord
    job: IngestionJob | None
    created: bool


class DocumentIngestionService:
    def __init__(
        self,
        storage: SecureUploadStorage,
        jobs: IngestionJobManager,
        metadata: DocumentMetadataRegistry | None = None,
    ) -> None:
        self.storage = storage
        self.jobs = jobs
        self.metadata = metadata
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        filename: str,
        content: bytes,
        content_type: str | None,
        operation: Callable[[Path, ValidatedUpload], Any],
    ) -> IngestionJob:
        """Validate/save synchronously, then enqueue expensive work exactly once."""
        with self._lock:
            existing = self.jobs.get_by_idempotency(
                tenant_id=tenant_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing
            upload = validate_upload(filename, content, content_type)
            path = self.storage.persist(upload)
            try:
                return self.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=lambda: operation(path, upload),
                )
            except Exception:
                self.storage.remove(upload.storage_name)
                raise

    def submit_document(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        filename: str,
        content: bytes,
        content_type: str | None,
        parser_version: str,
        chunker_version: str,
        embedding_model: str,
        embedding_dimension: int,
        index_version: str,
        operation: Callable[[Path, ValidatedUpload, DocumentRecord], Any],
    ) -> DocumentSubmission:
        """Register metadata and link job lifecycle to document status."""
        if self.metadata is None:
            raise RuntimeError("document metadata registry is not configured")
        with self._lock:
            existing = self.metadata.get_by_hash(
                tenant_id=tenant_id,
                content_hash=hashlib.sha256(content).hexdigest(),
            )
            if existing is not None:
                return DocumentSubmission(document=existing, job=None, created=False)
            upload = validate_upload(filename, content, content_type)
            record, created = self.metadata.register(
                tenant_id=tenant_id,
                upload=upload,
                parser_version=parser_version,
                chunker_version=chunker_version,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                index_version=index_version,
            )
            if not created:
                return DocumentSubmission(document=record, job=None, created=False)
            path = self.storage.persist(upload)
            self.metadata.update_status(
                tenant_id=tenant_id,
                document_id=record.document_id,
                status=DocumentStatus.INDEXING,
            )

            def run() -> Any:
                try:
                    result = operation(path, upload, record)
                except Exception:
                    self.metadata.update_status(
                        tenant_id=tenant_id,
                        document_id=record.document_id,
                        status=DocumentStatus.FAILED,
                    )
                    raise
                self.metadata.update_status(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                    status=DocumentStatus.ACTIVE,
                )
                return result

            try:
                job = self.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=run,
                )
            except Exception:
                self.storage.remove(upload.storage_name)
                self.metadata.update_status(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                    status=DocumentStatus.FAILED,
                )
                raise
            return DocumentSubmission(document=record, job=job, created=True)
