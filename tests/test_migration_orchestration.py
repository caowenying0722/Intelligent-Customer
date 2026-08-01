import json
from pathlib import Path

import pytest

from evaluation.quality_gate import evaluate_quality_gate
from scripts.compare_retrieval_backends import run


def test_migration_comparison_cli_writes_traceable_artifact() -> None:
    input_path = Path("output") / "migration-input-test.json"
    output_path = Path("output") / "migration-report-test.json"
    input_path.write_text(
        json.dumps(
            {
                "baseline": {"a": ["d1", "d2"]},
                "candidate": {"a": ["d2", "d1"]},
                "relevant": {"a": ["d2"]},
            }
        ),
        encoding="utf-8",
    )
    try:
        run(str(input_path), str(output_path))
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["comparison"]["sample_count"] == 1
        assert "repository" in report
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def test_quality_gate_rejects_candidate_regression() -> None:
    result = evaluate_quality_gate(
        {
            "retrieval_regression": {"complete": True, "metrics": {}},
            "comparison": {
                "baseline_metrics": {"mrr": 1.0},
                "candidate_metrics": {"mrr": 0.5},
            },
        },
        minimum_metrics={},
    )
    assert result.passed is False
    assert any("regressed" in failure for failure in result.failures)


def test_migration_comparison_requires_explicit_candidate() -> None:
    input_path = Path("output") / "invalid-migration-input-test.json"
    output_path = Path("output") / "invalid-migration-output-test.json"
    input_path.write_text(json.dumps({"baseline": {}}), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="candidate"):
            run(str(input_path), str(output_path))
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
