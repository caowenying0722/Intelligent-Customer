import json
import subprocess
import sys
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


def test_deterministic_regression_script_entrypoint_and_quality_gate() -> None:
    output = Path("output") / "deterministic-subprocess-summary.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_deterministic_regression.py",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert str(output) in result.stdout
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["retrieval_regression"]["complete"] is True
    assert len(summary["retrieval_regression"]["dataset_sha256"]) == 64
    gate = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluation.quality_gate",
            "--summary",
            str(output),
            "--min",
            "recall@1=0.5",
            "--min",
            "recall@3=1.0",
            "--min",
            "mrr=1.0",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "quality gate passed" in gate.stdout
    output.unlink()
