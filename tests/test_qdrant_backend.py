import sys
import time
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest

from rag.qdrant_backend import (
    QdrantMetadataFilter,
    QdrantVectorBackend,
    VectorBackendError,
    build_qdrant_backend,
)


def test_qdrant_builder_rounds_subsecond_timeout_for_client(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs):
            self.timeout = kwargs["timeout"]

    fake_module = ModuleType("qdrant_client")
    setattr(fake_module, "QdrantClient", FakeClient)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)

    backend = build_qdrant_backend("http://qdrant:6333", timeout_seconds=0.25)

    assert backend is not None
    assert backend.client.timeout == 1


class FakeQdrantClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_collections(self):
        return {"collections": []}

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return ["point"]

    def upsert(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "completed"}

    def update_collection_aliases(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "completed"}

    def delete_collection(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "completed"}

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            points=[
                {
                    "id": "chunk-1",
                    "score": 0.75,
                    "payload": {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "document_version": "v2",
                        "tenant_id": "tenant-a",
                        "index_version": "idx-1",
                        "source": "manual.txt",
                    },
                }
            ]
        )


def test_qdrant_search_always_carries_tenant_and_index_filter() -> None:
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")

    assert backend.check_ready() is True
    assert backend.search(
        [0.1, 0.2], tenant_id="tenant-a", index_version="idx-3", limit=2
    ) == ["point"]
    query_filter = client.calls[0]["query_filter"]
    assert query_filter["must"] == [
        {"key": "tenant_id", "match": {"value": "tenant-a"}},
        {"key": "index_version", "match": {"value": "idx-3"}},
    ]


def test_qdrant_search_rejects_missing_scope_and_invalid_limit() -> None:
    backend = QdrantVectorBackend(FakeQdrantClient(), collection_name="knowledge")
    with pytest.raises(ValueError):
        backend.search([0.1], tenant_id="", index_version="idx-1")
    with pytest.raises(ValueError):
        backend.search([0.1], tenant_id="tenant-a", index_version="idx-1", limit=0)


def test_qdrant_readiness_and_search_are_bounded() -> None:
    class SlowClient(FakeQdrantClient):
        def get_collections(self):
            time.sleep(0.05)

        def search(self, **kwargs):
            time.sleep(0.05)
            return []

    backend = QdrantVectorBackend(
        SlowClient(), collection_name="knowledge", timeout_seconds=0.001
    )
    assert backend.check_ready() is False
    with pytest.raises(TimeoutError, match="timeout"):
        backend.search([0.1], tenant_id="tenant-a", index_version="idx-1")


def test_qdrant_backend_wraps_client_failures() -> None:
    class BrokenClient(FakeQdrantClient):
        def search(self, **kwargs):
            raise OSError("connection refused")

    backend = QdrantVectorBackend(BrokenClient(), collection_name="knowledge")
    with pytest.raises(VectorBackendError, match="search failed"):
        backend.search([0.1], tenant_id="tenant-a", index_version="idx-1")


def test_qdrant_search_results_normalizes_point_contract() -> None:
    class PointClient(FakeQdrantClient):
        def search(self, **kwargs):
            return [
                {
                    "id": "chunk-1",
                    "score": 0.91,
                    "payload": {
                        "tenant_id": "tenant-a",
                        "index_version": "idx-1",
                        "document_id": "doc-1",
                        "source": "manual.txt",
                    },
                }
            ]

    backend = QdrantVectorBackend(PointClient(), collection_name="knowledge")
    result = backend.search_results(
        [0.1], tenant_id="tenant-a", index_version="idx-1", limit=1
    )[0]
    assert (result.chunk_id, result.fused_score, result.final_rank) == (
        "chunk-1",
        0.91,
        1,
    )


def test_qdrant_upsert_batches_and_validates_scope() -> None:
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")
    points = [
        {
            "id": index,
            "vector": [0.1],
            "payload": {"tenant_id": "tenant-a", "index_version": "idx-1"},
        }
        for index in range(3)
    ]
    assert (
        backend.upsert(
            points, tenant_id="tenant-a", index_version="idx-1", batch_size=2
        )
        == 3
    )
    upsert_calls = [call for call in client.calls if "points" in call]
    assert [len(call["points"]) for call in upsert_calls] == [2, 1]
    with pytest.raises(ValueError, match="outside"):
        backend.upsert(
            [{"id": "bad", "payload": {"tenant_id": "tenant-b"}}],
            tenant_id="tenant-a",
            index_version="idx-1",
        )


def test_qdrant_hybrid_query_uses_named_vectors_rrf_and_all_filters() -> None:
    pytest.importorskip("qdrant_client")
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")
    effective_at = datetime(2026, 8, 2, tzinfo=timezone.utc)

    results = backend.hybrid_search_results(
        [0.1, 0.2],
        sparse_indices=[1, 7],
        sparse_values=[0.4, 0.9],
        tenant_id="tenant-a",
        index_version="idx-1",
        metadata_filter=QdrantMetadataFilter(
            document_version="v2",
            product_model="air-1",
            language="zh-CN",
            effective_at=effective_at,
        ),
        prefetch_limit=8,
        limit=3,
        rrf_k=60,
    )

    call = client.calls[-1]
    assert [item.using for item in call["prefetch"]] == ["dense", "sparse"]
    assert call["query"].rrf.k == 60
    conditions = {condition.key: condition for condition in call["query_filter"].must}
    assert conditions["tenant_id"].match.value == "tenant-a"
    assert conditions["index_version"].match.value == "idx-1"
    assert conditions["document_version"].match.value == "v2"
    assert conditions["product_model"].match.value == "air-1"
    assert conditions["language"].match.value == "zh-CN"
    assert conditions["effective_from"].range.lte == effective_at
    assert conditions["effective_to"].range.gte == effective_at
    assert results[0].fused_score == 0.75


def test_qdrant_hybrid_query_rejects_unscoped_or_malformed_vectors() -> None:
    backend = QdrantVectorBackend(FakeQdrantClient(), collection_name="knowledge")
    with pytest.raises(ValueError, match="tenant_id"):
        backend.hybrid_search_results(
            [0.1],
            sparse_indices=[1],
            sparse_values=[1.0],
            tenant_id="",
            index_version="idx-1",
        )
    with pytest.raises(ValueError, match="aligned"):
        backend.hybrid_search_results(
            [0.1],
            sparse_indices=[1],
            sparse_values=[],
            tenant_id="tenant-a",
            index_version="idx-1",
        )


def test_qdrant_alias_switch_is_atomic_and_bounded() -> None:
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")
    backend.switch_active_alias(alias_name="active", target_collection="build-2")
    alias_call = client.calls[-1]
    assert alias_call["change_aliases"] == [
        {"delete_alias": {"alias_name": "active"}},
        {
            "create_alias": {
                "collection_name": "build-2",
                "alias_name": "active",
            }
        },
    ]


def test_qdrant_alias_rollback_reuses_atomic_switch() -> None:
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")
    backend.rollback_active_alias(alias_name="active", previous_collection="stable-1")
    assert client.calls[-1]["change_aliases"][-1] == {
        "create_alias": {
            "collection_name": "stable-1",
            "alias_name": "active",
        }
    }


def test_qdrant_cleanup_protects_active_and_retains_newest_collections() -> None:
    client = FakeQdrantClient()
    backend = QdrantVectorBackend(client, collection_name="knowledge")
    deleted = backend.cleanup_old_collections(
        ["v3", "v2", "v1", "active-v0"],
        active_collection="active-v0",
        retain_collections=2,
    )
    assert deleted == ["v1"]
    assert [call["collection_name"] for call in client.calls if "timeout" in call] == [
        "v1"
    ]
    with pytest.raises(ValueError):
        backend.cleanup_old_collections(
            ["active-v0"], active_collection="active-v0", retain_collections=-1
        )
