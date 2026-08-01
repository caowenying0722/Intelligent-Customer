"""Tenant-scoped document metadata and content-hash deduplication."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from src.app.application.uploads import ValidatedUpload


class DocumentStatus(str, Enum):
    REGISTERED = "registered"
    INDEXING = "indexing"
    ACTIVE = "active"
    FAILED = "failed"
    DELETED = "deleted"


@dataclass(frozen=True)
class DocumentRecord:
    document_id: UUID
    tenant_id: str
    original_name: str
    storage_name: str
    content_hash: str
    document_version: int
    parser_version: str
    chunker_version: str
    embedding_model: str
    embedding_dimension: int
    index_version: str
    status: DocumentStatus
    created_at: datetime


class DocumentMetadataRegistry:
    """In-memory baseline registry; persistence belongs to the next database target."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[UUID, DocumentRecord] = {}
        self._by_hash: dict[tuple[str, str], UUID] = {}

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
    ) -> tuple[DocumentRecord, bool]:
        if not tenant_id.strip() or not index_version.strip():
            raise ValueError("tenant_id and index_version must not be empty")
        if not all(
            value.strip()
            for value in (parser_version, chunker_version, embedding_model)
        ):
            raise ValueError("document processing versions must not be empty")
        if embedding_dimension < 1:
            raise ValueError("embedding_dimension must be positive")
        key = (tenant_id, upload.sha256)
        with self._lock:
            existing_id = self._by_hash.get(key)
            if existing_id is not None:
                return self._records[existing_id], False
            record = DocumentRecord(
                document_id=uuid4(),
                tenant_id=tenant_id,
                original_name=upload.original_name,
                storage_name=upload.storage_name,
                content_hash=upload.sha256,
                document_version=1,
                parser_version=parser_version,
                chunker_version=chunker_version,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                index_version=index_version,
                status=DocumentStatus.REGISTERED,
                created_at=datetime.now(timezone.utc),
            )
            self._records[record.document_id] = record
            self._by_hash[key] = record.document_id
            return record, True

    def get(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord | None:
        with self._lock:
            record = self._records.get(document_id)
            return record if record and record.tenant_id == tenant_id else None

    def get_by_hash(self, *, tenant_id: str, content_hash: str) -> DocumentRecord | None:
        with self._lock:
            document_id = self._by_hash.get((tenant_id, content_hash))
            return self._records.get(document_id) if document_id is not None else None

    def update_status(
        self,
        *,
        tenant_id: str,
        document_id: UUID,
        status: DocumentStatus | str,
    ) -> DocumentRecord:
        with self._lock:
            record = self._records.get(document_id)
            if record is None or record.tenant_id != tenant_id:
                raise KeyError("document not found")
            updated = replace(record, status=DocumentStatus(status))
            self._records[document_id] = updated
            return updated

    def delete(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord:
        with self._lock:
            record = self._records.get(document_id)
            if record is None or record.tenant_id != tenant_id:
                raise KeyError("document not found")
            if record.status == DocumentStatus.DELETED:
                return record
            self._by_hash.pop((tenant_id, record.content_hash), None)
            updated = replace(record, status=DocumentStatus.DELETED)
            self._records[document_id] = updated
            return updated
