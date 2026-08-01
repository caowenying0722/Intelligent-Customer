"""Deterministic retrieval regression metrics with no model or network calls."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def _relevant_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("k must be positive")
    return list(retrieved[:k])


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    return len(set(_relevant_at_k(retrieved, relevant_set, k)) & relevant_set) / len(
        relevant_set
    )


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    for rank, document_id in enumerate(retrieved, start=1):
        if document_id in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    gains = [
        1.0 if item in relevant_set else 0.0
        for item in _relevant_at_k(retrieved, relevant_set, k)
    ]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_length = min(len(relevant_set), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_length + 1))
    return dcg / ideal if ideal else 0.0


def evaluate_retrieval(
    retrieved_by_sample: dict[str, Sequence[str]],
    relevant_by_sample: dict[str, Iterable[str]],
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
) -> dict[str, float]:
    if set(retrieved_by_sample) != set(relevant_by_sample):
        raise ValueError("retrieved and relevant sample IDs must match")
    if not retrieved_by_sample:
        raise ValueError("at least one retrieval sample is required")
    return {
        **{
            f"recall@{k}": sum(
                recall_at_k(
                    retrieved_by_sample[sample_id], relevant_by_sample[sample_id], k
                )
                for sample_id in retrieved_by_sample
            )
            / len(retrieved_by_sample)
            for k in ks
        },
        "mrr": sum(
            reciprocal_rank(
                retrieved_by_sample[sample_id], relevant_by_sample[sample_id]
            )
            for sample_id in retrieved_by_sample
        )
        / len(retrieved_by_sample),
        **{
            f"ndcg@{k}": sum(
                ndcg_at_k(
                    retrieved_by_sample[sample_id], relevant_by_sample[sample_id], k
                )
                for sample_id in retrieved_by_sample
            )
            / len(retrieved_by_sample)
            for k in ks
        },
    }
