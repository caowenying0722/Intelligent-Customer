from pathlib import Path


def test_quality_workflow_validates_manifest_and_prepares_artifacts() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "mkdir -p output/ci" in workflow
    assert "python -m evaluation.dataset_manifest" in workflow
    assert "python scripts/run_deterministic_regression.py" in workflow
    assert "python scripts/run_red_team_regression.py" in workflow
    assert "python scripts/run_load_smoke.py" in workflow
    assert "python -m evaluation.quality_gate" in workflow
    assert "--config config/evaluation_quality_gate.yml" in workflow
    assert (
        "python -m mypy agent rag model evaluation utils scripts src/app app.py"
        in workflow
    )
    assert "coverage run -m pytest -q" in workflow
    assert "coverage report" in workflow
