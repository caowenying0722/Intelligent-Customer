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
