"""Compare deterministic baseline and candidate retrieval rankings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evaluation.retrieval_metrics import evaluate_retrieval


def compare_rankings(
    baseline: Mapping[str, Sequence[str]],
    candidate: Mapping[str, Sequence[str]],
    relevant: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    if set(baseline) != set(candidate) or set(baseline) != set(relevant):
        raise ValueError("baseline, candidate and relevant sample IDs must match")
    baseline_metrics = evaluate_retrieval(baseline, relevant)
    candidate_metrics = evaluate_retrieval(candidate, relevant)
    overlaps = {
        sample_id: len(set(baseline[sample_id]) & set(candidate[sample_id]))
        for sample_id in baseline
    }
    return {
        "sample_count": len(baseline),
        "overlap_by_sample": overlaps,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
    }
