import pytest

from evaluation.retrieval_comparison import compare_rankings


def test_compare_rankings_reports_metrics_and_overlap() -> None:
    comparison = compare_rankings(
        {"a": ["d1", "d2"]},
        {"a": ["d2", "d3"]},
        {"a": ["d2"]},
    )
    assert comparison["sample_count"] == 1
    assert comparison["overlap_by_sample"] == {"a": 1}
    assert comparison["baseline_metrics"]["mrr"] == 0.5
    assert comparison["candidate_metrics"]["mrr"] == 1.0


def test_compare_rankings_requires_matching_sample_ids() -> None:
    with pytest.raises(ValueError, match="sample IDs"):
        compare_rankings({"a": ["d1"]}, {"b": ["d1"]}, {"a": ["d1"]})
