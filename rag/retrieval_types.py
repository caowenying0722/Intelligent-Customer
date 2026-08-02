"""Stable result contract shared by dense, sparse, fusion and rerank stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document


def build_chroma_scope_filter(
    *, tenant_id: str | None = None, index_version: str | None = None
) -> dict[str, object] | None:
    """Build a local/Qdrant-compatible metadata filter without partial scope."""
    if index_version and not tenant_id:
        raise ValueError("tenant_id is required when index_version is provided")
    if tenant_id and index_version:
        return {
            "$and": [
                {"tenant_id": tenant_id},
                {"index_version": index_version},
            ]
        }
    if tenant_id:
        return {"tenant_id": tenant_id}
    return None


def filter_documents_by_scope(
    documents: list[Document], *, tenant_id: str, index_version: str
) -> list[Document]:
    """Fail closed when candidate metadata is absent or outside the requested scope."""
    if not tenant_id.strip() or not index_version.strip():
        raise ValueError("tenant_id and index_version must not be empty")
    return [
        document
        for document in documents
        if document.metadata.get("tenant_id") == tenant_id
        and document.metadata.get("index_version") == index_version
    ]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """A tenant-scoped retrieval candidate with auditable version metadata."""

    chunk_id: str
    document_id: str
    tenant_id: str
    document_version: str
    index_version: str
    source: str
    dense_score: float | None = None
    sparse_score: float | None = None
    fused_score: float | None = None
    reranker_score: float | None = None
    final_rank: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "chunk_id",
            "document_id",
            "tenant_id",
            "document_version",
            "index_version",
            "source",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.final_rank is not None and self.final_rank < 1:
            raise ValueError("final_rank must be positive")

    @classmethod
    def from_document(
        cls,
        document: Document,
        *,
        tenant_id: str,
        index_version: str,
        final_rank: int | None = None,
        source: str | None = None,
        fused_score: float | None = None,
    ) -> RetrievalResult:
        metadata = dict(document.metadata)
        actual_tenant = str(metadata.get("tenant_id", ""))
        if actual_tenant != tenant_id:
            raise ValueError("document tenant_id does not match requested tenant")
        actual_index = str(metadata.get("index_version", ""))
        if actual_index != index_version:
            raise ValueError("document index_version does not match requested index")
        chunk_id = str(metadata.get("chunk_id") or metadata.get("id") or "")
        document_id = str(metadata.get("document_id") or metadata.get("source") or "")
        return cls(
            chunk_id=chunk_id or document.page_content,
            document_id=document_id or chunk_id or document.page_content,
            tenant_id=tenant_id,
            document_version=str(metadata.get("document_version", "unknown")),
            index_version=index_version,
            source=source or str(metadata.get("source", "unknown")),
            fused_score=fused_score,
            final_rank=final_rank,
            metadata=metadata,
        )
