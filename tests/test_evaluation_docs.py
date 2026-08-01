from pathlib import Path


def test_evaluation_runbook_matches_real_entrypoints() -> None:
    document = Path("docs/evaluation/README.md").read_text(encoding="utf-8")

    assert "python -m evaluation.dataset_manifest" in document
    assert "python scripts/run_deterministic_regression.py" in document
    assert "python -m evaluation.quality_gate" in document
    assert "require_model_free" in document
    assert "RAGAS" in document
