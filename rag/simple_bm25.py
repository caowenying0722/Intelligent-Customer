from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

from langchain_core.documents import Document

from rag.rrf import reciprocal_rank_fusion, reciprocal_rank_fusion_scored
from rag.retrieval_types import RetrievalResult


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _doc_key(doc: Document) -> str:
    source = (
        doc.metadata.get("source")
        or doc.metadata.get("file_path")
        or doc.metadata.get("path")
        or ""
    )
    return f"{source}|{doc.page_content}"


class SimpleBM25Retriever:
    def __init__(
        self,
        documents: list[Document],
        preprocess_func: Callable[[str], list[str]],
        k: int = 3,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.documents = documents
        self.preprocess_func = preprocess_func
        self.k = k
        self.k1 = k1
        self.b = b
        self._doc_tokens = [self.preprocess_func(doc.page_content) for doc in documents]
        self._doc_freq = self._build_doc_freq()
        self._avg_doc_len = _safe_divide(
            sum(len(tokens) for tokens in self._doc_tokens), len(self._doc_tokens)
        )

    def _build_doc_freq(self) -> dict[str, int]:
        doc_freq: dict[str, int] = {}
        for tokens in self._doc_tokens:
            for token in set(tokens):
                doc_freq[token] = doc_freq.get(token, 0) + 1
        return doc_freq

    def _idf(self, token: str) -> float:
        total_docs = len(self.documents)
        freq = self._doc_freq.get(token, 0)
        return math.log(1 + _safe_divide(total_docs - freq + 0.5, freq + 0.5))

    def _score_tokens(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0

        doc_len = len(doc_tokens)
        term_freq = Counter(doc_tokens)
        score = 0.0
        for token in query_tokens:
            freq = term_freq.get(token, 0)
            if freq == 0:
                continue
            denominator = freq + self.k1 * (
                1 - self.b + self.b * _safe_divide(doc_len, self._avg_doc_len)
            )
            score += self._idf(token) * _safe_divide(freq * (self.k1 + 1), denominator)
        return score

    def invoke(self, query: str) -> list[Document]:
        query_tokens = self.preprocess_func(query)
        scored = [
            (self._score_tokens(query_tokens, doc_tokens), index, doc)
            for index, (doc, doc_tokens) in enumerate(
                zip(self.documents, self._doc_tokens)
            )
        ]
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [doc for score, _, doc in scored[: self.k] if score > 0]


class WeightedHybridRetriever:
    def __init__(
        self,
        vector_retriever,
        keyword_retriever: SimpleBM25Retriever,
        vector_weight: float,
        keyword_weight: float,
        k: int,
    ):
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.k = k

    def invoke(self, query: str) -> list[Document]:
        weighted_docs: dict[str, tuple[float, Document]] = {}

        for rank, doc in enumerate(self.vector_retriever.invoke(query), start=1):
            key = _doc_key(doc)
            score = self.vector_weight / rank
            previous_score, _ = weighted_docs.get(key, (0.0, doc))
            weighted_docs[key] = (previous_score + score, doc)

        for rank, doc in enumerate(self.keyword_retriever.invoke(query), start=1):
            key = _doc_key(doc)
            score = self.keyword_weight / rank
            previous_score, _ = weighted_docs.get(key, (0.0, doc))
            weighted_docs[key] = (previous_score + score, doc)

        ranked = sorted(weighted_docs.values(), key=lambda item: item[0], reverse=True)
        return [doc for _, doc in ranked[: self.k]]


class RRFHybridRetriever:
    """Hybrid adapter using rank fusion while preserving retriever boundaries."""

    def __init__(self, vector_retriever, keyword_retriever, k: int, fusion_k: int = 60):
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.k = k
        self.fusion_k = fusion_k

    def invoke(self, query: str) -> list[Document]:
        rankings = [
            self.vector_retriever.invoke(query),
            self.keyword_retriever.invoke(query),
        ]
        return reciprocal_rank_fusion(rankings, k=self.fusion_k, limit=self.k)

    def invoke_results(
        self, query: str, *, tenant_id: str, index_version: str
    ) -> list[RetrievalResult]:
        """Return the same fusion output with an explicit tenant/version contract."""
        rankings = [
            self.vector_retriever.invoke(query),
            self.keyword_retriever.invoke(query),
        ]
        scored_documents = reciprocal_rank_fusion_scored(
            rankings,
            k=self.fusion_k,
            limit=self.k,
            key_fn=_doc_key,
        )
        results: list[RetrievalResult] = []
        for rank, (document, fused_score) in enumerate(scored_documents, start=1):
            results.append(
                RetrievalResult.from_document(
                    document,
                    tenant_id=tenant_id,
                    index_version=index_version,
                    final_rank=rank,
                    fused_score=fused_score,
                )
            )
        return results
