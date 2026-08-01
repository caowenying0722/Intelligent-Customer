from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from langchain_core.documents import Document

from rag.tokenization import cjk_bm25_tokenizer


@dataclass(frozen=True)
class RerankResult:
    document: Document
    score: float
    reason: str


class CrossEncoderRerankerAdapter:
    """Bounded adapter for an optional local/remote cross-encoder scorer.

    The scorer is injected so tests remain offline. Any timeout, malformed
    response or scorer failure explicitly falls back to the deterministic
    evidence reranker and marks returned documents as degraded.
    """

    def __init__(
        self,
        scorer: Callable[[str, list[Document]], list[float]] | None = None,
        *,
        fallback: LightweightEvidenceReranker | None = None,
        max_candidates: int = 32,
        timeout_seconds: float = 2.0,
    ):
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.scorer = scorer
        self.fallback = fallback or LightweightEvidenceReranker()
        self.max_candidates = max_candidates
        self.timeout_seconds = timeout_seconds

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        candidates = docs[: self.max_candidates]
        if not candidates:
            return []
        if self.scorer is None:
            return self._fallback(query, candidates, top_k)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reranker")
        future = executor.submit(self.scorer, query, candidates)
        try:
            scores = future.result(timeout=self.timeout_seconds)
            if len(scores) != len(candidates):
                raise ValueError("scorer returned an unexpected score count")
            ranked = sorted(
                zip(scores, candidates), key=lambda item: item[0], reverse=True
            )
            return [document for _, document in ranked[:top_k]]
        except Exception:  # noqa: BLE001 - scorer failures use deterministic fallback.
            future.cancel()
            return self._fallback(query, candidates, top_k)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _fallback(
        self, query: str, candidates: list[Document], top_k: int
    ) -> list[Document]:
        result = self.fallback.rerank(query, candidates, top_k)
        for document in result:
            document.metadata["rerank_degraded"] = True
        return result


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _content_key(doc: Document) -> str:
    # Source/file paths are evaluation labels and must not affect ranking or
    # duplicate handling. Keep only stable document identity fields.
    identity = tuple(
        (key, doc.metadata.get(key))
        for key in ("tenant_id", "document_id", "chunk_id", "index_version")
    )
    raw = f"{doc.page_content}|{identity}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


class LightweightEvidenceReranker:
    """A deterministic reranker for local ablation before plugging in a cross-encoder."""

    def __init__(
        self,
        rank_weight: float = 0.55,
        token_weight: float = 0.30,
        char_weight: float = 0.15,
    ):
        self.rank_weight = rank_weight
        self.token_weight = token_weight
        self.char_weight = char_weight

    def score(self, query: str, doc: Document, original_rank: int) -> RerankResult:
        query_tokens = set(cjk_bm25_tokenizer(query))
        doc_tokens = set(cjk_bm25_tokenizer(doc.page_content))
        token_overlap = _safe_divide(len(query_tokens & doc_tokens), len(query_tokens))

        query_chars = set(_normalize_text(query))
        doc_chars = set(_normalize_text(doc.page_content))
        char_overlap = _safe_divide(len(query_chars & doc_chars), len(query_chars))
        rank_score = _safe_divide(1.0, original_rank)

        score = (
            self.rank_weight * rank_score
            + self.token_weight * token_overlap
            + self.char_weight * char_overlap
        )
        reason = (
            f"rank_score={rank_score:.3f}, "
            f"token_overlap={token_overlap:.3f}, char_overlap={char_overlap:.3f}, rank={original_rank}"
        )
        return RerankResult(document=doc, score=round(score, 6), reason=reason)

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        seen: set[str] = set()
        unique_docs: list[tuple[int, Document]] = []
        for index, doc in enumerate(docs, start=1):
            key = _content_key(doc)
            if key in seen:
                continue
            seen.add(key)
            unique_docs.append((index, doc))

        ranked = sorted(
            (self.score(query, doc, rank) for rank, doc in unique_docs),
            key=lambda item: item.score,
            reverse=True,
        )

        selected = ranked[:top_k]

        for result in selected:
            result.document.metadata["rerank_score"] = result.score
            result.document.metadata["rerank_reason"] = result.reason

        return [result.document for result in selected]
