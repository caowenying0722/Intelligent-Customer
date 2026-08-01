import pytest

from src.app.application.document_metadata import (
    DocumentMetadataRegistry,
    DocumentStatus,
)
from src.app.application.uploads import validate_upload


def _upload(content: bytes = b"same"):
    return validate_upload("manual.txt", content, "text/plain")


def test_document_registry_deduplicates_by_tenant_and_content_hash() -> None:
    registry = DocumentMetadataRegistry()
    first, created = registry.register(
        tenant_id="tenant-a",
        upload=_upload(),
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-1",
    )
    duplicate, created_again = registry.register(
        tenant_id="tenant-a",
        upload=_upload(),
        parser_version="p2",
        chunker_version="c2",
        embedding_model="e2",
        embedding_dimension=4,
        index_version="idx-2",
    )
    other_tenant, other_created = registry.register(
        tenant_id="tenant-b",
        upload=_upload(),
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-1",
    )
    assert created is True
    assert created_again is False
    assert duplicate.document_id == first.document_id
    assert other_created is True
    assert other_tenant.tenant_id == "tenant-b"


def test_document_registry_is_tenant_scoped_and_status_auditable() -> None:
    registry = DocumentMetadataRegistry()
    record, _ = registry.register(
        tenant_id="tenant-a",
        upload=_upload(b"one"),
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-1",
    )
    assert registry.get(tenant_id="tenant-b", document_id=record.document_id) is None
    updated = registry.update_status(
        tenant_id="tenant-a",
        document_id=record.document_id,
        status=DocumentStatus.INDEXING,
    )
    assert updated.status == DocumentStatus.INDEXING
    with pytest.raises(KeyError):
        registry.update_status(
            tenant_id="tenant-b",
            document_id=record.document_id,
            status=DocumentStatus.ACTIVE,
        )


def test_document_registry_rejects_invalid_processing_metadata() -> None:
    registry = DocumentMetadataRegistry()
    with pytest.raises(ValueError):
        registry.register(
            tenant_id="tenant-a",
            upload=_upload(),
            parser_version="",
            chunker_version="c1",
            embedding_model="e1",
            embedding_dimension=0,
            index_version="idx-1",
        )


def test_document_registry_delete_is_idempotent_and_releases_hash() -> None:
    registry = DocumentMetadataRegistry()
    record, _ = registry.register(
        tenant_id="tenant-a",
        upload=_upload(),
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-1",
    )
    deleted = registry.delete(tenant_id="tenant-a", document_id=record.document_id)
    assert deleted.status == DocumentStatus.DELETED
    assert (
        registry.delete(tenant_id="tenant-a", document_id=record.document_id) == deleted
    )
    replacement, created = registry.register(
        tenant_id="tenant-a",
        upload=_upload(),
        parser_version="p1",
        chunker_version="c1",
        embedding_model="e1",
        embedding_dimension=3,
        index_version="idx-2",
    )
    assert created is True
    assert replacement.document_id != record.document_id
