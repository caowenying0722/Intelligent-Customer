"""Rank-based fusion primitives for combining heterogeneous retrievers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]],
    *,
    k: int = 60,
    limit: int | None = None,
    key_fn: Callable[[T], str] | None = None,
) -> list[T]:
    """Fuse ranked result lists using reciprocal rank, preserving stable ties.

    The input order is the rank order for each retriever. Items with the same
    key are de-duplicated and retain the first encountered representative.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    key = key_fn or (lambda item: str(item))
    scores: dict[str, float] = {}
    representatives: dict[str, T] = {}
    first_seen: dict[str, int] = {}
    encounter = 0
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            item_key = key(item)
            if item_key not in representatives:
                representatives[item_key] = item
                first_seen[item_key] = encounter
                encounter += 1
            scores[item_key] = scores.get(item_key, 0.0) + 1.0 / (k + rank)

    ordered_keys = sorted(
        scores,
        key=lambda item_key: (-scores[item_key], first_seen[item_key]),
    )
    if limit is not None:
        ordered_keys = ordered_keys[:limit]
    return [representatives[item_key] for item_key in ordered_keys]
