from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, PrivateAttr


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _matches_where(
    metadata: Mapping[str, Any], where: Mapping[str, Any] | None
) -> bool:
    """Evaluate the small Chroma-compatible filter subset used by the app."""

    if where is None:
        return True
    if "$and" in where:
        clauses = where["$and"]
        if not isinstance(clauses, list):
            return False
        return all(
            isinstance(clause, Mapping) and _matches_where(metadata, clause)
            for clause in clauses
        )
    return all(metadata.get(key) == value for key, value in where.items())


class LocalVectorRetriever(BaseRetriever):
    """LangChain retriever facade for the local SQLite vector store."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    search_kwargs: dict[str, Any] = Field(default_factory=dict)
    _store: LocalVectorStore = PrivateAttr()

    def __init__(self, store: LocalVectorStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._store = store

    def _get_relevant_documents(
        self, query: str, *, run_manager: Any
    ) -> list[Document]:
        del run_manager
        filter_value = self.search_kwargs.get("filter")
        if filter_value is not None and not isinstance(filter_value, Mapping):
            raise ValueError("retriever filter must be a mapping")
        return self._store.similarity_search(
            query,
            k=int(self.search_kwargs.get("k", 4)),
            where=filter_value,
        )


class LocalVectorStore:
    """Small dependency-free persistent vector store for the local baseline.

    Qdrant remains the production vector backend. This store exists for the
    offline/Streamlit baseline and keeps the previous ``Chroma``-like adapter
    surface without importing the vulnerable ChromaDB distribution.
    """

    def __init__(
        self,
        *,
        collection_name: str,
        embedding_function: Embeddings,
        persist_directory: str | Path | None,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty")
        self.collection_name = collection_name
        self.embedding_function = embedding_function
        self._lock = RLock()
        self._temporary = persist_directory is None
        if persist_directory is None:
            database_path = ":memory:"
        else:
            directory = Path(persist_directory).expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            database_path = str(directory / "vectors.sqlite3")
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._table_name = self._safe_table_name(collection_name)
        self._create_table()

    @staticmethod
    def _safe_table_name(collection_name: str) -> str:
        encoded = collection_name.encode("utf-8").hex()
        return f"vector_{encoded}"

    def _create_table(self) -> None:
        with self._lock:
            self._connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{self._table_name}" (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )
            self._connection.commit()

    def add_documents(self, documents: list[Document]) -> list[str]:
        if not documents:
            return []
        embeddings = self.embedding_function.embed_documents(
            [document.page_content for document in documents]
        )
        if len(embeddings) != len(documents):
            raise ValueError("embedding count does not match document count")
        rows = [
            (
                uuid.uuid4().hex,
                document.page_content,
                json.dumps(
                    document.metadata, ensure_ascii=False, sort_keys=True, default=str
                ),
                json.dumps(embedding),
            )
            for document, embedding in zip(documents, embeddings)
        ]
        with self._lock:
            self._connection.executemany(
                f'INSERT INTO "{self._table_name}" '
                "(id, content, metadata, embedding) VALUES (?, ?, ?, ?)",
                rows,
            )
            self._connection.commit()
        return [row[0] for row in rows]

    def _read_rows(self, where: Mapping[str, Any] | None = None) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._connection.execute(
                f'SELECT id, content, metadata, embedding FROM "{self._table_name}"'
            ).fetchall()
        if where is None:
            return rows
        return [
            row for row in rows if _matches_where(json.loads(row["metadata"]), where)
        ]

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> Document:
        return Document(
            page_content=str(row["content"]),
            metadata=json.loads(row["metadata"]),
        )

    def get(
        self,
        *,
        include: list[str] | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> dict[str, list[Any]]:
        del include
        rows = self._read_rows(where)
        return {
            "ids": [str(row["id"]) for row in rows],
            "documents": [str(row["content"]) for row in rows],
            "metadatas": [json.loads(row["metadata"]) for row in rows],
        }

    def similarity_search(
        self,
        query: str,
        *,
        k: int = 4,
        where: Mapping[str, Any] | None = None,
    ) -> list[Document]:
        if k < 1:
            return []
        query_embedding = self.embedding_function.embed_query(query)
        scored: list[tuple[float, str, Document]] = []
        for row in self._read_rows(where):
            document = self._document_from_row(row)
            embedding = json.loads(row["embedding"])
            score = _cosine_similarity(query_embedding, embedding)
            scored.append((score, str(row["id"]), document))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored[:k]]

    def as_retriever(
        self, *, search_kwargs: dict[str, Any] | None = None
    ) -> LocalVectorRetriever:
        return LocalVectorRetriever(self, search_kwargs=search_kwargs or {})

    def delete_collection(self) -> None:
        with self._lock:
            self._connection.execute(f'DROP TABLE IF EXISTS "{self._table_name}"')
            self._connection.commit()
        if not self._temporary:
            self._create_table()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
