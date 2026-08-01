"""Optional Qdrant backend boundary with explicit scope and timeouts.

The adapter deliberately depends on an injected client, so importing and
testing the application does not require qdrant-client or a running service.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from typing import Any


class VectorBackendError(RuntimeError):
    """A vector backend operation failed or returned an unusable response."""


class QdrantVectorBackend:
    def __init__(
        self,
        client: Any,
        *,
        collection_name: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = client
        self.collection_name = collection_name
        self.timeout_seconds = timeout_seconds

    def check_ready(self) -> bool:
        """Perform a bounded health request; readiness failures return false."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-health")
        future = executor.submit(self.client.get_collections)
        try:
            future.result(timeout=self.timeout_seconds)
            return True
        except Exception:
            future.cancel()
            return False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_bounded(self, operation: Callable[[], Any], label: str) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-call")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"Qdrant {label} exceeded its configured timeout") from exc
        except Exception as exc:
            future.cancel()
            if isinstance(exc, ValueError):
                raise
            raise VectorBackendError(f"Qdrant {label} failed") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def search(
        self,
        query_vector: list[float],
        *,
        tenant_id: str,
        index_version: str,
        limit: int = 10,
    ) -> list[Any]:
        if not tenant_id.strip() or not index_version.strip():
            raise ValueError("tenant_id and index_version must not be empty")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        query_filter = {
            "must": [
                {"key": "tenant_id", "match": {"value": tenant_id}},
                {"key": "index_version", "match": {"value": index_version}},
            ]
        }

        def call_backend() -> list[Any]:
            kwargs = {
                "collection_name": self.collection_name,
                "query_vector": query_vector,
                "query_filter": query_filter,
                "limit": limit,
                "timeout": self.timeout_seconds,
            }
            if hasattr(self.client, "search"):
                return list(self.client.search(**kwargs))
            if hasattr(self.client, "query_points"):
                return list(self.client.query_points(**kwargs).points)
            raise VectorBackendError("Qdrant client has no search method")

        return self._run_bounded(call_backend, "search")

    def upsert(
        self,
        points: Sequence[dict[str, Any]],
        *,
        tenant_id: str,
        index_version: str,
        batch_size: int = 64,
    ) -> int:
        """Upsert bounded batches after validating every point's scope payload."""
        if not tenant_id.strip() or not index_version.strip():
            raise ValueError("tenant_id and index_version must not be empty")
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        normalized = list(points)
        for point in normalized:
            payload = point.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("every point must have a payload")
            if (
                payload.get("tenant_id") != tenant_id
                or payload.get("index_version") != index_version
            ):
                raise ValueError("point payload is outside the requested scope")

        for offset in range(0, len(normalized), batch_size):
            batch = normalized[offset : offset + batch_size]

            def call_backend(batch: list[dict[str, Any]] = batch) -> Any:
                return self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                    wait=True,
                    timeout=self.timeout_seconds,
                )

            self._run_bounded(call_backend, "upsert")
        return len(normalized)

    def switch_active_alias(self, *, alias_name: str, target_collection: str) -> None:
        """Atomically replace an active alias with a validated target collection."""
        if not alias_name.strip() or not target_collection.strip():
            raise ValueError("alias_name and target_collection must not be empty")

        def call_backend() -> Any:
            return self.client.update_collection_aliases(
                change_aliases=[
                    {"delete_alias": {"alias_name": alias_name}},
                    {
                        "create_alias": {
                            "collection_name": target_collection,
                            "alias_name": alias_name,
                        }
                    },
                ],
                timeout=self.timeout_seconds,
            )

        self._run_bounded(call_backend, "alias switch")

    def rollback_active_alias(self, *, alias_name: str, previous_collection: str) -> None:
        """Rollback by atomically pointing the alias at a known-good collection."""
        self.switch_active_alias(
            alias_name=alias_name, target_collection=previous_collection
        )

    def cleanup_old_collections(
        self,
        collections: Sequence[str],
        *,
        active_collection: str,
        retain_collections: int = 1,
    ) -> list[str]:
        """Delete only non-active collections beyond the newest retention window.

        ``collections`` must be ordered newest first. The active collection is
        always protected, even if it falls outside the requested retention.
        """
        if not active_collection.strip():
            raise ValueError("active_collection must not be empty")
        if retain_collections < 0:
            raise ValueError("retain_collections must not be negative")
        ordered = list(dict.fromkeys(collections))
        protected = set(ordered[:retain_collections]) | {active_collection}
        deleted: list[str] = []
        for collection in ordered:
            if not collection.strip() or collection in protected:
                continue

            def call_backend(collection: str = collection) -> Any:
                return self.client.delete_collection(
                    collection_name=collection,
                    timeout=self.timeout_seconds,
                )

            self._run_bounded(call_backend, "collection cleanup")
            deleted.append(collection)
        return deleted
