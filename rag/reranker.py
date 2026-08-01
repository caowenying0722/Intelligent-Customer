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
    raw = f"{doc.page_content}|{doc.metadata}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


class LightweightEvidenceReranker:
    """A deterministic reranker for local ablation before plugging in a cross-encoder."""

    def __init__(
        self,
        source_weight: float = 0.45,
        rank_weight: float = 0.35,
        token_weight: float = 0.15,
        char_weight: float = 0.05,
    ):
        self.source_weight = source_weight
        self.rank_weight = rank_weight
        self.token_weight = token_weight
        self.char_weight = char_weight

    @staticmethod
    def _source_text(doc: Document) -> str:
        source = (
            doc.metadata.get("source")
            or doc.metadata.get("file_path")
            or doc.metadata.get("path")
            or ""
        )
        return _normalize_text(str(source))

    @staticmethod
    def _route_hints(query: str) -> list[str]:
        normalized_query = _normalize_text(query)
        hints: list[str] = []

        purchase_terms = [
            "选购",
            "选择",
            "买",
            "购买",
            "配置",
            "参数",
            "户型",
            "家庭",
            "适合",
        ]
        maintenance_terms = [
            "维护",
            "保养",
            "清理",
            "清洁",
            "更换",
            "寿命",
            "多久",
            "长期",
            "存放",
            "耗材",
        ]
        mopping_terms = [
            "拖地",
            "水箱",
            "拖布",
            "清洁液",
            "污水",
            "出水",
            "地毯",
            "湿拖",
            "干拖",
        ]
        fault_terms = [
            "无法",
            "不能",
            "不出",
            "不转",
            "失效",
            "报警",
            "故障",
            "异响",
            "下降",
            "错乱",
            "漏水",
            "水痕",
            "处理",
            "排查",
        ]

        if any(term in normalized_query for term in purchase_terms):
            hints.append("选购指南")
        if any(term in normalized_query for term in maintenance_terms):
            hints.append("维护保养")
        if any(term in normalized_query for term in mopping_terms):
            hints.append("扫拖一体")
        if any(term in normalized_query for term in fault_terms):
            hints.append("故障排除")

        return hints

    def _source_score(self, query: str, doc: Document) -> float:
        hints = self._route_hints(query)
        if not hints:
            return 0.0

        source = self._source_text(doc)
        matched_hints = sum(1 for hint in hints if _normalize_text(hint) in source)
        return _safe_divide(matched_hints, len(hints))

    def score(self, query: str, doc: Document, original_rank: int) -> RerankResult:
        query_tokens = set(cjk_bm25_tokenizer(query))
        doc_tokens = set(cjk_bm25_tokenizer(doc.page_content))
        token_overlap = _safe_divide(len(query_tokens & doc_tokens), len(query_tokens))

        query_chars = set(_normalize_text(query))
        doc_chars = set(_normalize_text(doc.page_content))
        char_overlap = _safe_divide(len(query_chars & doc_chars), len(query_chars))
        source_score = self._source_score(query, doc)
        rank_score = _safe_divide(1.0, original_rank)

        score = (
            self.source_weight * source_score
            + self.rank_weight * rank_score
            + self.token_weight * token_overlap
            + self.char_weight * char_overlap
        )
        reason = (
            f"source_score={source_score:.3f}, rank_score={rank_score:.3f}, "
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

        selected: list[RerankResult] = []
        selected_sources: set[str] = set()
        for result in ranked:
            source = self._source_text(result.document)
            if source in selected_sources and len(selected) < min(
                top_k, len({self._source_text(item.document) for item in ranked})
            ):
                continue
            selected.append(result)
            selected_sources.add(source)
            if len(selected) == top_k:
                break

        if len(selected) < top_k:
            selected_keys = {_content_key(result.document) for result in selected}
            for result in ranked:
                if _content_key(result.document) in selected_keys:
                    continue
                selected.append(result)
                selected_keys.add(_content_key(result.document))
                if len(selected) == top_k:
                    break

        for result in selected:
            result.document.metadata["rerank_score"] = result.score
            result.document.metadata["rerank_reason"] = result.reason

        return [result.document for result in selected]
