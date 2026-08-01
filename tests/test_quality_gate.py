from pathlib import Path
import tempfile

import pytest

from evaluation.quality_gate import evaluate_quality_gate, load_quality_gate_config


def _summary(complete: bool = True) -> dict:
    return {
        "retrieval_regression": {
            "complete": complete,
            "metrics": {"recall@1": 0.75, "mrr": 0.8},
        }
    }


def test_quality_gate_passes_explicit_thresholds() -> None:
    result = evaluate_quality_gate(
        _summary(), minimum_metrics={"recall@1": 0.7, "mrr": 0.8}
    )
    assert result.passed is True
    assert result.failures == ()


def test_quality_gate_reports_incomplete_and_regression() -> None:
    result = evaluate_quality_gate(
        _summary(complete=False), minimum_metrics={"recall@1": 0.9, "ndcg@3": 0.2}
    )
    assert result.passed is False
    assert "incomplete" in result.failures[0]
    assert any("below minimum" in failure for failure in result.failures)
    assert any("missing metric" in failure for failure in result.failures)


def test_quality_gate_rejects_model_calls_in_deterministic_mode() -> None:
    summary = _summary()
    summary["retriever"] = {"model_calls": 1}

    result = evaluate_quality_gate(
        summary,
        minimum_metrics={},
        require_model_free=True,
    )

    assert result.passed is False
    assert "model calls" in result.failures[0]


def test_quality_gate_rejects_non_numeric_threshold_value() -> None:
    with pytest.raises(ValueError):
        evaluate_quality_gate(
            _summary(), minimum_metrics={"recall@1": float("nan")}
        )


def test_quality_gate_config_is_versioned_and_cli_overrides() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".gate-test-") as directory:
        config = Path(directory) / "gate.yml"
        config.write_text(
            "require_complete: false\nminimum_metrics:\n  recall@1: 0.7\n",
            encoding="utf-8",
        )

        loaded = load_quality_gate_config(config)

    assert loaded == {
        "require_complete": False,
        "require_model_free": False,
        "minimum_metrics": {"recall@1": 0.7},
    }
