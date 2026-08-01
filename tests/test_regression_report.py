from evaluation.regression_report import (
    build_retrieval_regression_summary,
    repository_snapshot,
)


def test_regression_report_records_version_metrics_and_missing_samples() -> None:
    dataset = "data/evaluation/retrieval_regression_v1.json"
    summary = build_retrieval_regression_summary(
        [
            {
                "id": "fault_wifi_connect",
                "retrieved_sources": ["故障排除.txt"],
            }
        ],
        dataset,
    )
    assert summary["dataset_version"] == "retrieval-regression-v1"
    assert summary["complete"] is False
    assert "maintenance_after_cleaning" in summary["missing_sample_ids"]
    assert summary["metrics"]["recall@1"] == 0.5


def test_repository_snapshot_has_stable_keys() -> None:
    assert set(repository_snapshot()) == {"commit", "dirty"}
