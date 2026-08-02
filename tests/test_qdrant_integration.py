from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from rag.qdrant_backend import QdrantMetadataFilter, QdrantVectorBackend

QDRANT_URL = os.getenv("TEST_QDRANT_URL")
pytestmark = pytest.mark.skipif(
    not QDRANT_URL, reason="TEST_QDRANT_URL is required for Qdrant integration"
)


def test_real_qdrant_hybrid_rrf_enforces_tenant_and_metadata_scope() -> None:
    from qdrant_client import QdrantClient, models

    assert QDRANT_URL is not None
    collection = f"hybrid-test-{uuid4().hex}"
    client = QdrantClient(url=QDRANT_URL, timeout=5)
    client.create_collection(
        collection_name=collection,
        vectors_config={
            "dense": models.VectorParams(size=2, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
    )
    try:
        common = {
            "document_version": "v2",
            "product_model": "air-1",
            "language": "zh-CN",
            "effective_from": "2020-01-01T00:00:00Z",
            "effective_to": "2030-01-01T00:00:00Z",
        }
        client.upsert(
            collection_name=collection,
            wait=True,
            points=[
                models.PointStruct(
                    id=1,
                    vector={
                        "dense": [1.0, 0.0],
                        "sparse": models.SparseVector(indices=[7], values=[1.0]),
                    },
                    payload={
                        **common,
                        "tenant_id": "tenant-a",
                        "index_version": "idx-1",
                        "chunk_id": "chunk-a",
                        "document_id": "doc-a",
                        "source": "manual-a",
                    },
                ),
                models.PointStruct(
                    id=2,
                    vector={
                        "dense": [1.0, 0.0],
                        "sparse": models.SparseVector(indices=[7], values=[1.0]),
                    },
                    payload={
                        **common,
                        "tenant_id": "tenant-b",
                        "index_version": "idx-1",
                        "chunk_id": "chunk-b",
                        "document_id": "doc-b",
                    },
                ),
                models.PointStruct(
                    id=3,
                    vector={
                        "dense": [1.0, 0.0],
                        "sparse": models.SparseVector(indices=[7], values=[1.0]),
                    },
                    payload={
                        **common,
                        "tenant_id": "tenant-a",
                        "index_version": "idx-old",
                        "chunk_id": "chunk-old",
                        "document_id": "doc-old",
                    },
                ),
            ],
        )

        backend = QdrantVectorBackend(
            client, collection_name=collection, timeout_seconds=5
        )
        results = backend.hybrid_search_results(
            [1.0, 0.0],
            sparse_indices=[7],
            sparse_values=[1.0],
            tenant_id="tenant-a",
            index_version="idx-1",
            metadata_filter=QdrantMetadataFilter(
                document_version="v2",
                product_model="air-1",
                language="zh-CN",
                effective_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            prefetch_limit=10,
            limit=5,
            rrf_k=60,
        )

        assert [result.chunk_id for result in results] == ["chunk-a"]
        assert results[0].tenant_id == "tenant-a"
        assert results[0].index_version == "idx-1"
        assert results[0].fused_score is not None
    finally:
        client.delete_collection(collection_name=collection)
        client.close()
