import time

import pytest

from rag.qdrant_backend import QdrantVectorBackend, VectorBackendError


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
