import pytest

from evaluation.frozen_regression import load_frozen_regression
from evaluation.retrieval_metrics import (
    evaluate_retrieval,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_retrieval_metrics_have_deterministic_hand_calculation() -> None:
    retrieved = ["d3", "d1", "d2"]
    relevant = ["d1", "d2"]
    assert recall_at_k(retrieved, relevant, 1) == 0.0
    assert recall_at_k(retrieved, relevant, 3) == 1.0
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert ndcg_at_k(retrieved, relevant, 3) == pytest.approx(
        (1 / 1.5849625007 + 1 / 2) / (1 + 1 / 1.5849625007)
    )


def test_evaluate_retrieval_aggregates_and_requires_matching_ids() -> None:
    result = evaluate_retrieval(
        {"a": ["d1"], "b": ["d3", "d2"]},
        {"a": ["d1"], "b": ["d2"]},
        ks=(1, 2),
    )
    assert result["recall@1"] == 0.5
    assert result["mrr"] == pytest.approx(0.75)
    with pytest.raises(ValueError, match="IDs"):
        evaluate_retrieval({"a": ["d1"]}, {"b": ["d1"]})


def test_frozen_regression_dataset_is_versioned_and_validated() -> None:
    samples = load_frozen_regression("data/evaluation/retrieval_regression_v1.json")
    assert len(samples) == 3
    assert {sample.dataset_version for sample in samples} == {"retrieval-regression-v1"}
