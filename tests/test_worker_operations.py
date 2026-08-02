from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.app.application.document_metadata import DocumentRecord, DocumentStatus
from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobStatus,
    PermanentIngestionError,
    RetryableIngestionError,
)
from src.app.workers.operations import WorkerOperationRegistry


class Store:
    def __init__(self, document: DocumentRecord) -> None:
        self.document = document

    def get_document(self, *, tenant_id, document_id):
        if (
            tenant_id == self.document.tenant_id
            and document_id == self.document.document_id
        ):
            return self.document
        return None

    def update_document_status(self, *, tenant_id, document_id, status):
        assert tenant_id == self.document.tenant_id
        assert document_id == self.document.document_id
        self.document = replace(self.document, status=DocumentStatus(status))
        return self.document


class Qdrant:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}
        self.aliases: dict[str, str] = {}
        self.fail_upsert: Exception | None = None

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, *, collection_name, **_kwargs):
        self.collections[collection_name] = []

    def upsert(self, *, collection_name, points, **_kwargs):
        if self.fail_upsert is not None:
            raise self.fail_upsert
        existing = {point["id"]: point for point in self.collections[collection_name]}
        existing.update({point["id"]: point for point in points})
        self.collections[collection_name] = list(existing.values())

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.collections]
        )

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    def count(self, *, collection_name, **_kwargs):
        return SimpleNamespace(count=len(self.collections[collection_name]))

    def update_collection_aliases(self, *, change_aliases, **_kwargs):
        for change in change_aliases:
            deleted = change.get("delete_alias")
            if deleted:
                self.aliases.pop(deleted["alias_name"], None)
            created = change.get("create_alias")
            if created:
                self.aliases[created["alias_name"]] = created["collection_name"]


def document(
    *, tenant_id: str = "tenant-a", index_version: str = "v1"
) -> DocumentRecord:
    return DocumentRecord(
        document_id=uuid4(),
        tenant_id=tenant_id,
        original_name="guide.txt",
        storage_name=f"{uuid4().hex}.txt",
        content_hash="",
        document_version=1,
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        embedding_model="local-hash-v1",
        embedding_dimension=64,
        index_version=index_version,
        status=DocumentStatus.INDEXING,
        created_at=datetime.now(timezone.utc),
    )


def persist_document(
    root: Path, record: DocumentRecord, content: bytes
) -> DocumentRecord:
    root.mkdir(parents=True, exist_ok=True)
    (root / record.storage_name).write_bytes(content)
    import hashlib

    return replace(record, content_hash=hashlib.sha256(content).hexdigest())


def job_for(record: DocumentRecord) -> IngestionJob:
    return IngestionJob(
        job_id=uuid4(),
        tenant_id=record.tenant_id,
        idempotency_key="document-1",
        status=IngestionJobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
        task_type="document_ingestion",
        task_payload=json.dumps({"document_id": str(record.document_id)}),
    )


def test_document_operation_parses_chunks_and_upserts_idempotently(
    tmp_path: Path,
) -> None:
    record = persist_document(tmp_path, document(), b"alpha beta\n\nalpha beta")
    store = Store(record)
    qdrant = Qdrant()
    registry = WorkerOperationRegistry(store, qdrant, upload_root=tmp_path)

    operation = registry.operation_for(job_for(record))
    collection = operation()
    first_points = list(qdrant.collections[collection])
    assert operation() == collection
    assert qdrant.collections[collection] == first_points
    assert first_points[0]["payload"]["tenant_id"] == "tenant-a"
    assert len(first_points[0]["vector"]["dense"]) == 64
    assert first_points[0]["vector"]["sparse"]["indices"]


def test_document_operation_rejects_contract_or_hash_mismatch(tmp_path: Path) -> None:
    record = persist_document(tmp_path, document(), b"safe")
    registry = WorkerOperationRegistry(Store(record), Qdrant(), upload_root=tmp_path)
    (tmp_path / record.storage_name).write_bytes(b"tampered")
    with pytest.raises(PermanentIngestionError, match="hash mismatch"):
        registry.ingest_document(record.tenant_id, record.document_id)

    unsupported = replace(record, embedding_model="remote-paid-model")
    with pytest.raises(PermanentIngestionError, match="embedding model"):
        WorkerOperationRegistry(
            Store(unsupported), Qdrant(), upload_root=tmp_path
        ).ingest_document(unsupported.tenant_id, unsupported.document_id)


def test_vector_rate_limit_is_retryable_and_does_not_leak_provider_error(
    tmp_path: Path,
) -> None:
    class RateLimited(RuntimeError):
        status_code = 429

    record = persist_document(tmp_path, document(), b"retry me")
    qdrant = Qdrant()
    qdrant.fail_upsert = RateLimited("private backend response")
    registry = WorkerOperationRegistry(Store(record), qdrant, upload_root=tmp_path)
    with pytest.raises(
        RetryableIngestionError, match="temporarily unavailable"
    ) as error:
        registry.ingest_document(record.tenant_id, record.document_id)
    assert "private backend response" not in str(error.value)


def test_blue_green_rebuild_is_tenant_scoped_and_switches_only_valid_candidate(
    tmp_path: Path,
) -> None:
    first = persist_document(tmp_path, document(index_version="v1"), b"first")
    qdrant = Qdrant()
    registry = WorkerOperationRegistry(Store(first), qdrant, upload_root=tmp_path)
    first_collection = registry.ingest_document(first.tenant_id, first.document_id)
    assert registry.rebuild_index("tenant-a", "v1") == first_collection
    alias = registry.alias_name("tenant-a")
    assert qdrant.aliases[alias] == first_collection

    second = persist_document(tmp_path, document(index_version="v2"), b"second")
    registry.store = Store(second)
    second_collection = registry.ingest_document(second.tenant_id, second.document_id)
    assert registry.rebuild_index("tenant-a", "v2") == second_collection
    assert qdrant.aliases[alias] == second_collection
    assert registry.alias_name("tenant-b") != alias


def test_rebuild_failure_preserves_active_alias_and_terminal_hook_updates_document(
    tmp_path: Path,
) -> None:
    record = persist_document(tmp_path, document(), b"status")
    store = Store(record)
    qdrant = Qdrant()
    registry = WorkerOperationRegistry(store, qdrant, upload_root=tmp_path)
    qdrant.aliases[registry.alias_name("tenant-a")] = "stable"
    with pytest.raises(PermanentIngestionError, match="exactly one"):
        registry.rebuild_index("tenant-a", "missing")
    assert qdrant.aliases[registry.alias_name("tenant-a")] == "stable"

    registry.terminal_hook(job_for(record), IngestionJobStatus.COMPLETED)
    assert store.document.status == DocumentStatus.ACTIVE
    registry.terminal_hook(job_for(record), IngestionJobStatus.FAILED)
    assert store.document.status == DocumentStatus.FAILED
