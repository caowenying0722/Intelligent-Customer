"""Real, model-free document and index operations for ingestion workers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from rag.index_rebuild import BlueGreenIndexCoordinator, IndexRebuildError
from rag.qdrant_backend import QdrantVectorBackend, VectorBackendError
from src.app.application.document_metadata import DocumentRecord, DocumentStatus
from src.app.application.ingestion import (
    IngestionJob,
    IngestionJobStatus,
    PermanentIngestionError,
    RetryableIngestionError,
)

DOCUMENT_INGESTION_TASK = "document_ingestion"
INDEX_REBUILD_TASK = "index_rebuild"
LOCAL_EMBEDDING_MODEL = "local-hash-v1"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_CHARS = 1_000_000
MAX_PDF_PAGES = 500


class WorkerOperationRegistry:
    """Reconstruct persisted business operations without API-process closures."""

    def __init__(
        self,
        store: Any,
        qdrant_client: Any,
        *,
        upload_root: str | Path = "output/uploads",
        timeout_seconds: float = 30.0,
        collection_prefix: str = "knowledge",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("operation timeout must be positive")
        if not collection_prefix.strip():
            raise ValueError("collection prefix must not be blank")
        self.store = store
        self.client = qdrant_client
        self.upload_root = Path(upload_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.request_timeout_seconds = max(1, math.ceil(timeout_seconds))
        self.collection_prefix = collection_prefix

    def operation_for(self, job: IngestionJob) -> Callable[[], Any]:
        if job.task_type == DOCUMENT_INGESTION_TASK:
            document_id = self._document_id(job.task_payload)
            return lambda: self.ingest_document(job.tenant_id, document_id)
        if job.task_type == INDEX_REBUILD_TASK:
            index_version = self._index_version(job.task_payload)
            return lambda: self.rebuild_index(job.tenant_id, index_version)
        raise PermanentIngestionError("unsupported ingestion task type")

    def terminal_hook(self, job: IngestionJob, status: IngestionJobStatus) -> None:
        """Keep document state aligned with a terminal persisted job state."""
        if job.task_type != DOCUMENT_INGESTION_TASK:
            return
        document_id = self._document_id(job.task_payload)
        document = self.store.get_document(
            tenant_id=job.tenant_id, document_id=document_id
        )
        if document is None or document.status == DocumentStatus.DELETED:
            return
        target = {
            IngestionJobStatus.COMPLETED: DocumentStatus.ACTIVE,
            IngestionJobStatus.FAILED: DocumentStatus.FAILED,
            IngestionJobStatus.CANCELLED: DocumentStatus.FAILED,
        }.get(status)
        if target is not None:
            self.store.update_document_status(
                tenant_id=job.tenant_id, document_id=document_id, status=target
            )

    def ingest_document(self, tenant_id: str, document_id: UUID) -> str:
        document = self.store.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise PermanentIngestionError("document metadata not found")
        if document.status == DocumentStatus.DELETED:
            raise PermanentIngestionError("document was deleted")
        self._validate_processing_contract(document)
        path = (self.upload_root / document.storage_name).resolve()
        if path.parent != self.upload_root:
            raise PermanentIngestionError("document storage path is invalid")
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise PermanentIngestionError("document content not found") from exc
        except OSError as exc:
            raise RetryableIngestionError("document storage is unavailable") from exc
        if len(content) > MAX_DOCUMENT_BYTES:
            raise PermanentIngestionError("document exceeds worker size limit")
        if hashlib.sha256(content).hexdigest() != document.content_hash:
            raise PermanentIngestionError("document content hash mismatch")

        text = self._parse(content, suffix=Path(document.storage_name).suffix.lower())
        chunks = self._chunk(self._clean(text))
        collection = self.collection_name(document)
        try:
            self._ensure_collection(collection, document.embedding_dimension)
            backend = QdrantVectorBackend(
                self.client,
                collection_name=collection,
                timeout_seconds=self.timeout_seconds,
            )
            backend.upsert(
                self._points(document, chunks),
                tenant_id=tenant_id,
                index_version=document.index_version,
            )
        except (TimeoutError, VectorBackendError) as exc:
            if self._is_retryable(exc):
                raise RetryableIngestionError(
                    "vector backend is temporarily unavailable"
                ) from exc
            raise PermanentIngestionError("vector backend rejected document") from exc
        return collection

    def rebuild_index(self, tenant_id: str, index_version: str) -> str:
        if not tenant_id.strip() or not index_version.strip():
            raise PermanentIngestionError("tenant and index version are required")
        candidates = self._collections_for_version(tenant_id, index_version)
        if len(candidates) != 1:
            raise PermanentIngestionError(
                "index version must resolve to exactly one embedding dimension"
            )
        collection = candidates[0]
        alias = self.alias_name(tenant_id)
        previous = self._alias_target(alias)

        def validate(candidate: str) -> bool:
            response = self.client.count(
                collection_name=candidate,
                exact=True,
                timeout=self.request_timeout_seconds,
            )
            return int(getattr(response, "count", 0)) > 0

        backend = QdrantVectorBackend(
            self.client,
            collection_name=collection,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            if previous is None:
                if not validate(collection):
                    raise IndexRebuildError("candidate index validation rejected")
                backend.create_active_alias(
                    alias_name=alias,
                    target_collection=collection,
                )
                return collection
            if previous == collection:
                if not validate(collection):
                    raise IndexRebuildError("active index validation rejected")
                return collection
            return BlueGreenIndexCoordinator(
                backend, alias_name=alias, timeout_seconds=self.timeout_seconds
            ).rebuild(
                previous_collection=previous,
                build_candidate=lambda: collection,
                validate_candidate=validate,
            )
        except (TimeoutError, VectorBackendError) as exc:
            if self._is_retryable(exc):
                raise RetryableIngestionError(
                    "index backend is temporarily unavailable"
                ) from exc
            raise PermanentIngestionError("index rebuild failed") from exc
        except IndexRebuildError as exc:
            raise PermanentIngestionError("index rebuild failed") from exc

    def collection_name(self, document: DocumentRecord) -> str:
        return self.collection_name_for(
            tenant_id=document.tenant_id,
            index_version=document.index_version,
            embedding_dimension=document.embedding_dimension,
        )

    def collection_name_for(
        self,
        *,
        tenant_id: str,
        index_version: str,
        embedding_dimension: int | None,
    ) -> str:
        tenant_key = hashlib.sha256(tenant_id.encode()).hexdigest()[:12]
        index_key = hashlib.sha256(index_version.encode()).hexdigest()[:12]
        suffix = "" if embedding_dimension is None else f"-{embedding_dimension}"
        return f"{self.collection_prefix}-{tenant_key}-{index_key}{suffix}"

    def alias_name(self, tenant_id: str) -> str:
        tenant_key = hashlib.sha256(tenant_id.encode()).hexdigest()[:12]
        return f"{self.collection_prefix}-{tenant_key}-active"

    def _collections_for_version(self, tenant_id: str, index_version: str) -> list[str]:
        prefix = (
            self.collection_name_for(
                tenant_id=tenant_id,
                index_version=index_version,
                embedding_dimension=None,
            )
            + "-"
        )
        response = self.client.get_collections()
        return sorted(
            str(item.name)
            for item in getattr(response, "collections", [])
            if str(item.name).startswith(prefix)
        )

    def _alias_target(self, alias_name: str) -> str | None:
        response = self.client.get_aliases()
        for alias in getattr(response, "aliases", []):
            if str(alias.alias_name) == alias_name:
                return str(alias.collection_name)
        return None

    def _ensure_collection(self, collection: str, dimension: int) -> None:
        if self.client.collection_exists(collection):
            return
        try:
            self.client.create_collection(
                collection_name=collection,
                vectors_config={"dense": {"size": dimension, "distance": "Cosine"}},
                sparse_vectors_config={"sparse": {}},
                timeout=self.request_timeout_seconds,
            )
        except Exception:
            if not self.client.collection_exists(collection):
                raise

    @staticmethod
    def _validate_processing_contract(document: DocumentRecord) -> None:
        if document.parser_version != "parser-v1":
            raise PermanentIngestionError("unsupported parser version")
        if document.chunker_version != "chunker-v1":
            raise PermanentIngestionError("unsupported chunker version")
        if document.embedding_model != LOCAL_EMBEDDING_MODEL:
            raise PermanentIngestionError("unsupported embedding model")
        if not 1 <= document.embedding_dimension <= 4096:
            raise PermanentIngestionError("unsupported embedding dimension")

    @staticmethod
    def _parse(content: bytes, *, suffix: str) -> str:
        if suffix == ".txt":
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PermanentIngestionError("text document is not UTF-8") from exc
        if suffix != ".pdf":
            raise PermanentIngestionError("unsupported document format")
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content), strict=True)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise PermanentIngestionError("PDF exceeds worker page limit")
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except PermanentIngestionError:
            raise
        except Exception as exc:
            raise PermanentIngestionError("PDF parsing failed") from exc

    @staticmethod
    def _clean(text: str) -> str:
        normalized = text.replace("\x00", " ").replace("\r\n", "\n")
        normalized = re.sub(r"[\t ]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not normalized:
            raise PermanentIngestionError("document contains no extractable text")
        if len(normalized) > MAX_DOCUMENT_CHARS:
            raise PermanentIngestionError("document exceeds worker character limit")
        return normalized

    @staticmethod
    def _chunk(text: str, *, size: int = 1000, overlap: int = 100) -> list[str]:
        chunks: list[str] = []
        seen: set[str] = set()
        start = 0
        while start < len(text):
            chunk = text[start : start + size].strip()
            digest = hashlib.sha256(chunk.encode()).hexdigest()
            if chunk and digest not in seen:
                chunks.append(chunk)
                seen.add(digest)
            if start + size >= len(text):
                break
            start += size - overlap
        if not chunks:
            raise PermanentIngestionError("document produced no chunks")
        return chunks

    def _points(
        self, document: DocumentRecord, chunks: list[str]
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for position, chunk in enumerate(chunks):
            chunk_hash = hashlib.sha256(chunk.encode()).hexdigest()
            chunk_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{document.tenant_id}:{document.document_id}:{document.document_version}:{chunk_hash}",
                )
            )
            sparse_indices, sparse_values = self._sparse_vector(chunk)
            points.append(
                {
                    "id": chunk_id,
                    "vector": {
                        "dense": self._dense_vector(
                            chunk, document.embedding_dimension
                        ),
                        "sparse": {
                            "indices": sparse_indices,
                            "values": sparse_values,
                        },
                    },
                    "payload": {
                        "tenant_id": document.tenant_id,
                        "index_version": document.index_version,
                        "document_id": str(document.document_id),
                        "document_version": str(document.document_version),
                        "chunk_id": chunk_id,
                        "chunk_position": position,
                        "content": chunk,
                        "source": document.original_name,
                        "content_hash": document.content_hash,
                        "parser_version": document.parser_version,
                        "chunker_version": document.chunker_version,
                        "embedding_model": document.embedding_model,
                    },
                }
            )
        return points

    @staticmethod
    def _dense_vector(text: str, dimension: int) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < dimension:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1
        selected = values[:dimension]
        norm = math.sqrt(sum(value * value for value in selected)) or 1.0
        return [value / norm for value in selected]

    @staticmethod
    def _sparse_vector(text: str) -> tuple[list[int], list[float]]:
        counts = Counter(re.findall(r"\w+", text.casefold()))
        weighted: dict[int, float] = {}
        for token, count in counts.items():
            index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 1_000_003
            weighted[index] = weighted.get(index, 0.0) + float(count)
        pairs = sorted(weighted.items())
        return [index for index, _ in pairs], [value for _, value in pairs]

    @staticmethod
    def _document_id(payload: str | None) -> UUID:
        try:
            value = json.loads(payload or "{}")
            return UUID(str(value["document_id"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PermanentIngestionError("invalid document task payload") from exc

    @staticmethod
    def _index_version(payload: str | None) -> str:
        if payload is None or not payload.strip():
            raise PermanentIngestionError("invalid index rebuild payload")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return payload
        if (
            not isinstance(value, dict)
            or not str(value.get("index_version", "")).strip()
        ):
            raise PermanentIngestionError("invalid index rebuild payload")
        return str(value["index_version"])

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        current: BaseException | None = exc
        while current is not None:
            status = getattr(current, "status_code", None)
            if status == 429 or isinstance(status, int) and status >= 500:
                return True
            if isinstance(current, (TimeoutError, ConnectionError, OSError)):
                return True
            current = current.__cause__
        return False
