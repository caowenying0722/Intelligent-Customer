from __future__ import annotations

import re

from langchain_core.documents import Document

from rag.guardrails import is_out_of_scope_query, low_confidence_response
from rag.tokenization import cjk_bm25_tokenizer


def _split_sentences(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_lines: list[str] = []
    for line in lines:
        if line.startswith("#"):
            continue
        normalized_lines.append(re.sub(r"^-+\s*", "", line).strip())

    text = "\n".join(normalized_lines)
    parts = re.split(r"(?<=[。！？!?；;])|\n", text)
    sentences = [part.strip() for part in parts if part.strip()]
    if sentences:
        return sentences
    return [text.strip()] if text.strip() else []


def _score_sentence(query_tokens: set[str], sentence: str) -> float:
    sentence_tokens = set(cjk_bm25_tokenizer(sentence))
    if not query_tokens:
        return 0.0
    score = len(query_tokens & sentence_tokens) / len(query_tokens)
    if "检测：" in sentence or "修复：" in sentence or "建议" in sentence or "应" in sentence:
        score += 0.12
    if re.search(r"[？?]\*{0,2}$", sentence) or sentence.startswith("##"):
        score -= 0.2
    return max(score, 0.0)


def build_extractive_answer(
    query: str,
    docs: list[Document],
    max_sentences: int = 4,
    min_sentence_score: float = 0.12,
) -> str:
    if is_out_of_scope_query(query):
        return low_confidence_response()

    if not docs:
        return low_confidence_response()

    query_tokens = set(cjk_bm25_tokenizer(query))
    candidates: list[tuple[float, int, str]] = []
    for doc_index, doc in enumerate(docs, start=1):
        for sentence in _split_sentences(doc.page_content):
            candidates.append((_score_sentence(query_tokens, sentence), doc_index, sentence))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates or candidates[0][0] < min_sentence_score:
        return low_confidence_response()

    selected: list[str] = []
    seen: set[str] = set()
    for score, doc_index, sentence in candidates:
        normalized = re.sub(r"\s+", "", sentence)
        if not normalized or normalized in seen:
            continue
        if score < min_sentence_score and selected:
            continue
        seen.add(normalized)
        selected.append(f"{sentence}【资料{doc_index}】")
        if len(selected) >= max_sentences:
            break

    if not selected:
        return low_confidence_response()

    return "".join(selected)
