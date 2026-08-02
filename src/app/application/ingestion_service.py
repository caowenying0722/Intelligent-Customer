"""Application service joining upload validation, storage and background jobs."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from src.app.application.document_metadata import (
    DocumentRecord,
    DocumentStatus,
)
from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobManager,
    IngestionJobStatus,
    TaskDispatchError,
)
from src.app.application.upload_storage import SecureUploadStorage
from src.app.application.uploads import ValidatedUpload, validate_upload


@dataclass(frozen=True)
class DocumentSubmission:
    document: DocumentRecord
    job: IngestionJob | None
    created: bool


class DocumentMetadataStore(Protocol):
    def get(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord | None: ...

    def get_by_hash(
        self, *, tenant_id: str, content_hash: str
    ) -> DocumentRecord | None: ...

    def register(
        self,
        *,
        tenant_id: str,
        upload: ValidatedUpload,
        parser_version: str,
        chunker_version: str,
        embedding_model: str,
        embedding_dimension: int,
        index_version: str,
    ) -> tuple[DocumentRecord, bool]: ...

    def update_status(
        self,
        *,
        tenant_id: str,
        document_id: UUID,
        status: DocumentStatus | str,
    ) -> DocumentRecord: ...

    def delete(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord: ...


class DocumentIngestionService:
    def __init__(
        self,
        storage: SecureUploadStorage,
        jobs: IngestionJobManager,
        metadata: DocumentMetadataStore | None = None,
        job_store: Any | None = None,
    ) -> None:
        self.storage = storage
        self.jobs = jobs
        self.metadata = metadata
        self.job_store = job_store
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
                job = self.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=lambda: operation(path, upload),
                    defer_dispatch=self.jobs.has_dispatcher,
                )
                self.jobs.dispatch(job)
                return job
            except Exception:
                self.storage.remove(upload.storage_name)
                raise

    def close(self) -> None:
        self.jobs.close()
        if self.job_store is not None and hasattr(self.job_store, "close"):
            self.job_store.close()

    def delete_document(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord:
        if self.metadata is None:
            raise RuntimeError("document metadata registry is not configured")
        metadata = self.metadata
        with self._lock:
            document = metadata.get(tenant_id=tenant_id, document_id=document_id)
            if document is None:
                raise KeyError("document not found")
            if document.status != DocumentStatus.DELETED:
                self.storage.remove(document.storage_name)
                document = metadata.delete(tenant_id=tenant_id, document_id=document_id)
                if self.job_store is not None:
                    self.job_store.update_document_status(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        status=DocumentStatus.DELETED,
                    )
            return document

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
        metadata = self.metadata
        with self._lock:
            existing = metadata.get_by_hash(
                tenant_id=tenant_id,
                content_hash=hashlib.sha256(content).hexdigest(),
            )
            if existing is not None:
                return DocumentSubmission(document=existing, job=None, created=False)
            upload = validate_upload(filename, content, content_type)
            record, created = metadata.register(
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
            metadata.update_status(
                tenant_id=tenant_id,
                document_id=record.document_id,
                status=DocumentStatus.INDEXING,
            )
            if self.job_store is not None:
                self.job_store.update_document_status(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                    status=DocumentStatus.INDEXING,
                )

            job_holder: dict[str, UUID] = {}

            def run() -> Any:
                try:
                    result = operation(path, upload, record)
                except Exception as exc:
                    current = metadata.get(
                        tenant_id=tenant_id, document_id=record.document_id
                    )
                    if current is None or current.status != DocumentStatus.DELETED:
                        metadata.update_status(
                            tenant_id=tenant_id,
                            document_id=record.document_id,
                            status=DocumentStatus.FAILED,
                        )
                    if self.job_store is not None:
                        if current is None or current.status != DocumentStatus.DELETED:
                            self.job_store.update_document_status(
                                tenant_id=tenant_id,
                                document_id=record.document_id,
                                status=DocumentStatus.FAILED,
                            )
                        if job_holder.get("id") is not None:
                            self.job_store.update_job_status(
                                tenant_id=tenant_id,
                                job_id=job_holder["id"],
                                status=IngestionJobStatus.FAILED,
                                error=str(exc),
                            )
                    raise
                current = metadata.get(
                    tenant_id=tenant_id, document_id=record.document_id
                )
                if current is None or current.status == DocumentStatus.DELETED:
                    if self.job_store is not None and job_holder.get("id") is not None:
                        self.job_store.update_job_status(
                            tenant_id=tenant_id,
                            job_id=job_holder["id"],
                            status=IngestionJobStatus.COMPLETED,
                        )
                    return result
                metadata.update_status(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                    status=DocumentStatus.ACTIVE,
                )
                if self.job_store is not None:
                    self.job_store.update_document_status(
                        tenant_id=tenant_id,
                        document_id=record.document_id,
                        status=DocumentStatus.ACTIVE,
                    )
                    if job_holder.get("id") is not None:
                        self.job_store.update_job_status(
                            tenant_id=tenant_id,
                            job_id=job_holder["id"],
                            status=IngestionJobStatus.COMPLETED,
                        )
                return result

            try:
                job = self.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=run,
                    task_type="document_ingestion",
                    task_payload=json.dumps(
                        {"document_id": str(record.document_id)},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    defer_dispatch=self.jobs.has_dispatcher,
                )
                job_holder["id"] = job.job_id
                if self.job_store is not None:
                    self.job_store.create_job(job=job, document_id=record.document_id)
                    current = self.jobs.get(tenant_id=tenant_id, job_id=job.job_id)
                    if current is not None and current.status in {
                        IngestionJobStatus.COMPLETED,
                        IngestionJobStatus.FAILED,
                    }:
                        self.job_store.update_job_status(
                            tenant_id=tenant_id,
                            job_id=job.job_id,
                            status=current.status,
                            error=current.error,
                        )
            except Exception:
                self.storage.remove(upload.storage_name)
                metadata.update_status(
                    tenant_id=tenant_id,
                    document_id=record.document_id,
                    status=DocumentStatus.FAILED,
                )
                raise
            try:
                self.jobs.dispatch(job)
            except TaskDispatchError:
                # Keep the durable queued row and uploaded bytes for broker
                # recovery; a publish failure must not mark the document failed.
                raise
            return DocumentSubmission(document=record, job=job, created=True)
