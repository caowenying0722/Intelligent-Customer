"""Composable Qdrant hybrid retrieval pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from langchain_core.documents import Document

from rag.qdrant_backend import QdrantMetadataFilter, QdrantVectorBackend


@dataclass(frozen=True, slots=True)
class SparseEncoding:
    indices: list[int]
    values: list[float]

    def __post_init__(self) -> None:
        if not self.indices or len(self.indices) != len(self.values):
            raise ValueError("sparse encoding must be non-empty and aligned")


class DenseQueryEncoder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class SparseQueryEncoder(Protocol):
    def encode_query(self, text: str) -> SparseEncoding: ...


class DocumentReranker(Protocol):
    def rerank(
        self, query: str, docs: list[Document], top_k: int
    ) -> list[Document]: ...


class QdrantHybridRetriever:
    """Encode, fuse and optionally rerank one explicitly scoped query."""

    def __init__(
        self,
        backend: QdrantVectorBackend,
        dense_encoder: DenseQueryEncoder,
        sparse_encoder: SparseQueryEncoder,
        *,
        reranker: DocumentReranker | None = None,
        candidate_k: int = 20,
        final_k: int = 5,
        rrf_k: int = 60,
    ) -> None:
        if final_k < 1 or candidate_k < final_k:
            raise ValueError("candidate_k must be greater than or equal to final_k")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self.backend = backend
        self.dense_encoder = dense_encoder
        self.sparse_encoder = sparse_encoder
        self.reranker = reranker
        self.candidate_k = candidate_k
        self.final_k = final_k
        self.rrf_k = rrf_k

    def invoke(
        self,
        query: str,
        *,
        tenant_id: str,
        index_version: str,
        metadata_filter: QdrantMetadataFilter | None = None,
    ) -> list[Document]:
        if not query.strip():
            raise ValueError("query must not be empty")
        dense = self.dense_encoder.embed_query(query)
        sparse = self.sparse_encoder.encode_query(query)
        results = self.backend.hybrid_search_results(
            dense,
            sparse_indices=sparse.indices,
            sparse_values=sparse.values,
            tenant_id=tenant_id,
            index_version=index_version,
            metadata_filter=metadata_filter,
            prefetch_limit=self.candidate_k,
            limit=self.candidate_k,
            rrf_k=self.rrf_k,
        )
        documents: list[Document] = []
        for result in results:
            metadata = dict(result.metadata)
            content = metadata.pop("content", None)
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Qdrant result payload must contain non-empty content")
            metadata.update(
                {
                    "chunk_id": result.chunk_id,
                    "document_id": result.document_id,
                    "tenant_id": result.tenant_id,
                    "document_version": result.document_version,
                    "index_version": result.index_version,
                    "source": result.source,
                    "fused_score": result.fused_score,
                    "fused_rank": result.final_rank,
                }
            )
            documents.append(Document(page_content=content, metadata=metadata))
        if self.reranker is None:
            for document in documents[: self.final_k]:
                document.metadata["rerank_applied"] = False
            return documents[: self.final_k]
        return self.reranker.rerank(query, documents, self.final_k)


class CallableSparseEncoder:
    """Small adapter for production encoders and deterministic offline tests."""

    def __init__(self, encoder: Callable[[str], SparseEncoding]) -> None:
        self._encoder = encoder

    def encode_query(self, text: str) -> SparseEncoding:
        return self._encoder(text)
