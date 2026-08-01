from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from evaluation.dataset import EvaluationSample


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def keyword_group_matched(text: str, keyword_group: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(keyword) in normalized for keyword in keyword_group if keyword)


def matched_keyword_groups(text: str, keyword_groups: list[list[str]]) -> int:
    return sum(1 for group in keyword_groups if keyword_group_matched(text, group))


def source_name(doc: Document) -> str:
    for key in ("source", "file_path", "path"):
        value = doc.metadata.get(key)
        if value:
            return Path(str(value)).name
    return ""


def source_matched(doc: Document, expected_sources: list[str]) -> bool:
    doc_source = normalize_text(source_name(doc))
    return any(normalize_text(source) in doc_source for source in expected_sources)


def document_is_relevant(doc: Document, sample: EvaluationSample) -> bool:
    if sample.expected_sources and source_matched(doc, sample.expected_sources):
        return True

    return matched_keyword_groups(doc.page_content, sample.expected_keywords) > 0


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def char_f1(prediction: str, reference: str) -> float:
    pred_chars = [char for char in normalize_text(prediction) if char]
    ref_chars = [char for char in normalize_text(reference) if char]
    if not pred_chars or not ref_chars:
        return 0.0

    overlap = sum((Counter(pred_chars) & Counter(ref_chars)).values())
    precision = safe_divide(overlap, len(pred_chars))
    recall = safe_divide(overlap, len(ref_chars))
    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def sequence_similarity(prediction: str, reference: str) -> float:
    try:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, normalize_text(prediction), normalize_text(reference)).ratio()
    except Exception:
        return 0.0


def context_overlap(answer: str, contexts: list[str]) -> float:
    context_text = normalize_text("\n".join(contexts))
    answer_chars = [char for char in normalize_text(answer) if char]
    if not answer_chars:
        return 0.0

    grounded_chars = sum(1 for char in answer_chars if char in context_text)
    return safe_divide(grounded_chars, len(answer_chars))


def token_overlap_score(left: str, right: str) -> float:
    try:
        from rag.tokenization import cjk_bm25_tokenizer

        left_tokens = set(cjk_bm25_tokenizer(left))
        right_tokens = set(cjk_bm25_tokenizer(right))
    except Exception:
        left_tokens = set(normalize_text(left))
        right_tokens = set(normalize_text(right))

    return safe_divide(len(left_tokens & right_tokens), len(left_tokens))


def cited_reference_numbers(answer: str) -> list[int]:
    return [int(match) for match in re.findall(r"【资料(\d+)】", answer)]


def contains_low_confidence_terms(answer: str) -> bool:
    normalized_answer = normalize_text(answer)
    low_confidence_terms = ["知识库未提供足够依据", "没有找到足够可靠的依据", "低置信度", "转人工"]
    return any(normalize_text(term) in normalized_answer for term in low_confidence_terms)


def sentence_like_units(answer: str) -> list[str]:
    units = [unit.strip() for unit in re.split(r"[。！？!?；;\n]+", answer) if unit.strip()]
    return units if units else ([answer.strip()] if answer.strip() else [])


def citation_coverage(answer: str) -> float:
    if contains_low_confidence_terms(answer):
        return 1.0

    units = sentence_like_units(answer)
    if not units:
        return 0.0
    cited_units = sum(1 for unit in units if re.search(r"【资料\d+】", unit))
    return safe_divide(cited_units, len(units))


def citation_validity(answer: str, docs: list[Document]) -> float:
    citations = cited_reference_numbers(answer)
    if not citations and contains_low_confidence_terms(answer):
        return 1.0
    if not citations:
        return 0.0
    valid_count = sum(1 for citation in citations if 1 <= citation <= len(docs))
    return safe_divide(valid_count, len(citations))


def low_confidence_matched(sample: EvaluationSample, answer: str) -> float:
    expects_low_confidence = bool(sample.metadata.get("expect_low_confidence"))
    has_low_confidence_response = contains_low_confidence_terms(answer)
    return 1.0 if expects_low_confidence == has_low_confidence_response else 0.0


def answer_relevancy_proxy(sample: EvaluationSample, answer: str, keyword_accuracy: float) -> float:
    if sample.metadata.get("expect_low_confidence"):
        return low_confidence_matched(sample, answer)

    question_answer_overlap = token_overlap_score(sample.question, answer)
    return 0.5 * question_answer_overlap + 0.5 * keyword_accuracy


def factual_correctness_proxy(
    sample: EvaluationSample,
    answer: str,
    docs: list[Document],
    keyword_accuracy: float,
    answer_context_overlap: float,
) -> float:
    if sample.metadata.get("expect_low_confidence"):
        return low_confidence_matched(sample, answer)

    return (
        0.45 * answer_context_overlap
        + 0.35 * citation_validity(answer, docs)
        + 0.2 * keyword_accuracy
    )


def calculate_local_metrics(sample: EvaluationSample, answer: str, docs: list[Document]) -> dict[str, float]:
    contexts = [doc.page_content for doc in docs]
    joined_context = "\n".join(contexts)
    relevant_docs = [doc for doc in docs if document_is_relevant(doc, sample)]

    matched_retrieval_groups = matched_keyword_groups(joined_context, sample.expected_keywords)
    matched_answer_groups = matched_keyword_groups(answer, sample.expected_keywords)

    first_relevant_rank = 0
    for index, doc in enumerate(docs, start=1):
        if document_is_relevant(doc, sample):
            first_relevant_rank = index
            break

    source_hits = 0
    if sample.expected_sources:
        retrieved_sources = normalize_text(" ".join(source_name(doc) for doc in docs))
        source_hits = sum(1 for source in sample.expected_sources if normalize_text(source) in retrieved_sources)

    answer_keyword_accuracy = safe_divide(matched_answer_groups, len(sample.expected_keywords))
    answer_context_overlap = context_overlap(answer, contexts)

    metrics = {
        "retrieval_hit_rate": 1.0 if relevant_docs else 0.0,
        "retrieval_precision": safe_divide(len(relevant_docs), len(docs)),
        "retrieval_recall": safe_divide(matched_retrieval_groups, len(sample.expected_keywords)),
        "retrieval_mrr": safe_divide(1.0, first_relevant_rank) if first_relevant_rank else 0.0,
        "source_recall": safe_divide(source_hits, len(sample.expected_sources)),
        "answer_keyword_accuracy": answer_keyword_accuracy,
        "answer_char_f1": char_f1(answer, sample.reference_answer),
        "answer_similarity": sequence_similarity(answer, sample.reference_answer),
        "answer_context_overlap": answer_context_overlap,
        "answer_citation_coverage": citation_coverage(answer),
        "answer_citation_validity": citation_validity(answer, docs),
        "low_confidence_accuracy": low_confidence_matched(sample, answer),
        "answer_relevancy_proxy": answer_relevancy_proxy(sample, answer, answer_keyword_accuracy),
        "factual_correctness_proxy": factual_correctness_proxy(
            sample,
            answer,
            docs,
            answer_keyword_accuracy,
            answer_context_overlap,
        ),
    }

    return {name: round(value, 6) if math.isfinite(value) else 0.0 for name, value in metrics.items()}


def summarize_metric_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    metric_names: set[str] = set()
    for row in rows:
        metric_names.update(row.get("metrics", {}).keys())
        metric_names.update(row.get("ragas_metrics", {}).keys())

    summary: dict[str, float] = {}
    for metric_name in sorted(metric_names):
        values = []
        for row in rows:
            metrics = row.get("metrics", {})
            ragas_metrics = row.get("ragas_metrics", {})
            value = metrics.get(metric_name, ragas_metrics.get(metric_name))
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values.append(float(value))

        if values:
            summary[metric_name] = round(sum(values) / len(values), 6)

    return summary
