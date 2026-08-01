import json
from pathlib import Path

from scripts.run_red_team_regression import run


def test_red_team_regression_is_model_free_and_has_no_false_negatives() -> None:
    output = Path("output") / "red-team-test-summary.json"

    path = run(
        "data/evaluation/red_team/prompt_injection.manifest.json",
        str(output),
    )
    summary = json.loads(path.read_text(encoding="utf-8"))

    assert summary["security_regression"]["complete"] is True
    assert summary["security_regression"]["case_count"] == 4
    assert summary["security_regression"]["blocked_count"] == 4
    assert summary["security_regression"]["false_negatives"] == []
    assert summary["model_calls"] == 0
    path.unlink()
