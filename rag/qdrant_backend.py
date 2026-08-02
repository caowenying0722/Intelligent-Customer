"""Optional Qdrant backend boundary with explicit scope and timeouts.

The adapter deliberately depends on an injected client, so importing and
testing the application does not require qdrant-client or a running service.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rag.retrieval_types import RetrievalResult


class VectorBackendError(RuntimeError):
    """A vector backend operation failed or returned an unusable response."""


@dataclass(frozen=True, slots=True)
class QdrantMetadataFilter:
    """Optional business filters applied together with mandatory scope filters."""

    document_version: str | None = None
    product_model: str | None = None
    language: str | None = None
    effective_at: datetime | None = None


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
        self.request_timeout_seconds = max(1, math.ceil(timeout_seconds))

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def check_ready(self) -> bool:
        """Perform a bounded health request; readiness failures return false."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-health")
        future = executor.submit(self.client.get_collections)
        try:
            future.result(timeout=self.timeout_seconds)
            return True
        except Exception:  # noqa: BLE001 - readiness fails closed without leaking client details.
            future.cancel()
            return False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_bounded(self, operation: Callable[[], Any], label: str) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qdrant-call")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self.timeout_seconds)
        except (TimeoutError, FutureTimeoutError) as exc:
            future.cancel()
            raise TimeoutError(
                f"Qdrant {label} exceeded its configured timeout"
            ) from exc
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
                "timeout": self.request_timeout_seconds,
            }
            if hasattr(self.client, "search"):
                return list(self.client.search(**kwargs))
            if hasattr(self.client, "query_points"):
                return list(self.client.query_points(**kwargs).points)
            raise VectorBackendError("Qdrant client has no search method")

        return self._run_bounded(call_backend, "search")

    def search_results(
        self,
        query_vector: list[float],
        *,
        tenant_id: str,
        index_version: str,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        """Normalize Qdrant points into the shared, auditable result contract."""
        points = self.search(
            query_vector,
            tenant_id=tenant_id,
            index_version=index_version,
            limit=limit,
        )
        results: list[RetrievalResult] = []
        for rank, point in enumerate(points, start=1):
            point_id = (
                point.get("id")
                if isinstance(point, dict)
                else getattr(point, "id", None)
            )
            payload = (
                point.get("payload", {})
                if isinstance(point, dict)
                else getattr(point, "payload", {})
            )
            score = (
                point.get("score")
                if isinstance(point, dict)
                else getattr(point, "score", None)
            )
            if not isinstance(payload, dict):
                raise VectorBackendError("Qdrant point payload is invalid")
            if (
                payload.get("tenant_id") != tenant_id
                or payload.get("index_version") != index_version
            ):
                raise ValueError("Qdrant point is outside the requested scope")
            chunk_id = str(payload.get("chunk_id") or point_id or "")
            document_id = str(payload.get("document_id") or chunk_id)
            results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    document_version=str(payload.get("document_version", "unknown")),
                    index_version=index_version,
                    source=str(payload.get("source", "qdrant")),
                    fused_score=float(score)
                    if isinstance(score, (int, float))
                    else None,
                    final_rank=rank,
                    metadata=payload,
                )
            )
        return results

    def hybrid_search_results(
        self,
        dense_vector: list[float],
        *,
        sparse_indices: list[int],
        sparse_values: list[float],
        tenant_id: str,
        index_version: str,
        metadata_filter: QdrantMetadataFilter | None = None,
        dense_vector_name: str = "dense",
        sparse_vector_name: str = "sparse",
        prefetch_limit: int = 20,
        limit: int = 10,
        rrf_k: int = 60,
    ) -> list[RetrievalResult]:
        """Run one tenant-scoped dense+sparse query with server-side RRF."""
        if not tenant_id.strip() or not index_version.strip():
            raise ValueError("tenant_id and index_version must not be empty")
        if not dense_vector:
            raise ValueError("dense_vector must not be empty")
        if len(sparse_indices) != len(sparse_values) or not sparse_indices:
            raise ValueError("sparse indices and values must be non-empty and aligned")
        if prefetch_limit < limit or limit < 1 or prefetch_limit > 1000:
            raise ValueError("prefetch_limit must be between limit and 1000")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")

        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover - clean-install guard.
            raise RuntimeError(
                "qdrant-client is required for hybrid retrieval"
            ) from exc

        conditions: list[Any] = [
            models.FieldCondition(
                key="tenant_id", match=models.MatchValue(value=tenant_id)
            ),
            models.FieldCondition(
                key="index_version", match=models.MatchValue(value=index_version)
            ),
        ]
        optional = metadata_filter or QdrantMetadataFilter()
        for key, value in (
            ("document_version", optional.document_version),
            ("product_model", optional.product_model),
            ("language", optional.language),
        ):
            if value:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        if optional.effective_at is not None:
            conditions.extend(
                [
                    models.FieldCondition(
                        key="effective_from",
                        range=models.DatetimeRange(lte=optional.effective_at),
                    ),
                    models.FieldCondition(
                        key="effective_to",
                        range=models.DatetimeRange(gte=optional.effective_at),
                    ),
                ]
            )

        def call_backend() -> list[Any]:
            response = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=dense_vector,
                        using=dense_vector_name,
                        limit=prefetch_limit,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_indices, values=sparse_values
                        ),
                        using=sparse_vector_name,
                        limit=prefetch_limit,
                    ),
                ],
                query=models.RrfQuery(rrf=models.Rrf(k=rrf_k)),
                query_filter=models.Filter(must=conditions),
                with_payload=True,
                limit=limit,
                timeout=self.request_timeout_seconds,
            )
            return list(response.points)

        points = self._run_bounded(call_backend, "hybrid search")
        return self._normalize_results(
            points,
            tenant_id=tenant_id,
            index_version=index_version,
        )

    @staticmethod
    def _normalize_results(
        points: Sequence[Any], *, tenant_id: str, index_version: str
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        for rank, point in enumerate(points, start=1):
            point_id = (
                point.get("id")
                if isinstance(point, dict)
                else getattr(point, "id", None)
            )
            payload = (
                point.get("payload", {})
                if isinstance(point, dict)
                else getattr(point, "payload", {})
            )
            score = (
                point.get("score")
                if isinstance(point, dict)
                else getattr(point, "score", None)
            )
            if not isinstance(payload, dict):
                raise VectorBackendError("Qdrant point payload is invalid")
            if (
                payload.get("tenant_id") != tenant_id
                or payload.get("index_version") != index_version
            ):
                raise ValueError("Qdrant point is outside the requested scope")
            chunk_id = str(payload.get("chunk_id") or point_id or "")
            document_id = str(payload.get("document_id") or chunk_id)
            results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    document_version=str(payload.get("document_version", "unknown")),
                    index_version=index_version,
                    source=str(payload.get("source", "qdrant")),
                    fused_score=float(score)
                    if isinstance(score, (int, float))
                    else None,
                    final_rank=rank,
                    metadata=payload,
                )
            )
        return results

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
                    timeout=self.request_timeout_seconds,
                )

            self._run_bounded(call_backend, "upsert")
        return len(normalized)

    def switch_active_alias(self, *, alias_name: str, target_collection: str) -> None:
        """Atomically replace an active alias with a validated target collection."""
        if not alias_name.strip() or not target_collection.strip():
            raise ValueError("alias_name and target_collection must not be empty")

        def call_backend() -> Any:
            return self._update_aliases(
                [
                    {"delete_alias": {"alias_name": alias_name}},
                    {
                        "create_alias": {
                            "collection_name": target_collection,
                            "alias_name": alias_name,
                        }
                    },
                ]
            )

        self._run_bounded(call_backend, "alias switch")

    def create_active_alias(self, *, alias_name: str, target_collection: str) -> None:
        """Create the first tenant alias without deleting a nonexistent alias."""
        if not alias_name.strip() or not target_collection.strip():
            raise ValueError("alias_name and target_collection must not be empty")
        self._run_bounded(
            lambda: self._update_aliases(
                [
                    {
                        "create_alias": {
                            "collection_name": target_collection,
                            "alias_name": alias_name,
                        }
                    }
                ]
            ),
            "alias create",
        )

    def _update_aliases(self, changes: list[dict[str, Any]]) -> Any:
        """Translate the stable adapter contract to qdrant-client's model API."""
        if self.client.__class__.__module__.startswith("qdrant_client"):
            from qdrant_client import models

            operations: list[Any] = []
            for change in changes:
                deleted = change.get("delete_alias")
                if deleted is not None:
                    operations.append(
                        models.DeleteAliasOperation(
                            delete_alias=models.DeleteAlias(**deleted)
                        )
                    )
                created = change.get("create_alias")
                if created is not None:
                    operations.append(
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(**created)
                        )
                    )
            return self.client.update_collection_aliases(
                change_aliases_operations=operations,
                timeout=self.request_timeout_seconds,
            )
        return self.client.update_collection_aliases(
            change_aliases=changes,
            timeout=self.request_timeout_seconds,
        )

    def rollback_active_alias(
        self, *, alias_name: str, previous_collection: str
    ) -> None:
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
                    timeout=self.request_timeout_seconds,
                )

            self._run_bounded(call_backend, "collection cleanup")
            deleted.append(collection)
        return deleted


def build_qdrant_backend(
    url: str | None,
    *,
    collection_name: str = "knowledge-active",
    timeout_seconds: float = 5.0,
) -> QdrantVectorBackend | None:
    """Build the optional production adapter without import-time network calls."""
    if url is None:
        return None
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover - clean-install guard.
        raise RuntimeError("qdrant-client is required when QDRANT_URL is set") from exc
    # qdrant-client's constructor accepts integer seconds, while the service
    # configuration and bounded executor use sub-second precision. Round up
    # so a configured positive timeout never becomes an accidental zero.
    client = QdrantClient(url=url, timeout=max(1, math.ceil(timeout_seconds)))
    return QdrantVectorBackend(
        client,
        collection_name=collection_name,
        timeout_seconds=timeout_seconds,
    )
