"""Stable result contract shared by dense, sparse, fusion and rerank stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from langchain_core.documents import Document


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
    ) -> "RetrievalResult":
        metadata = dict(document.metadata)
        actual_tenant = str(metadata.get("tenant_id", tenant_id))
        if actual_tenant != tenant_id:
            raise ValueError("document tenant_id does not match requested tenant")
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
