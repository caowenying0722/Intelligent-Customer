from pathlib import Path

from scripts.run_deterministic_regression import run


def test_deterministic_regression_writes_model_free_summary() -> None:
    output = Path("output") / "deterministic-test-summary.json"
    path = run(
        "data/evaluation/retrieval_regression_v1.json",
        str(output),
        limit=1,
    )
    assert path == output
    summary = output.read_text(encoding="utf-8")
    assert '"model_calls": 0' in summary
    assert '"retrieval_regression"' in summary
    output.unlink()
