from __future__ import annotations

import json
import tempfile
from pathlib import Path

from evaluation.dataset import EvaluationSample
from evaluation.runner import (
    classify_evaluation_error,
    evaluate_samples,
    save_evaluation_report,
)


def test_error_classification_is_bounded() -> None:
    assert classify_evaluation_error(TimeoutError()) == "timeout"
    assert classify_evaluation_error(ConnectionError()) == "upstream"
    assert classify_evaluation_error(ValueError()) == "invalid_output"
    assert classify_evaluation_error(RuntimeError()) == "unknown"


def test_evaluation_rows_and_summary_record_duration_and_error_types(
    monkeypatch,
) -> None:
    class FakeRagService:
        def retriever_docs(self, query: str) -> list:
            if query == "broken":
                raise TimeoutError("provider body must not be recorded")
            return []

        def summarize_with_docs(self, query: str, context_docs: list) -> str:
            return "answer"

    monkeypatch.setattr(
        "evaluation.bm25_rag_service.BM25RagEvaluationService", FakeRagService
    )
    samples = [
        EvaluationSample(id="ok", question="ok", reference_answer="answer"),
        EvaluationSample(id="bad", question="broken", reference_answer="answer"),
    ]

    rows, error = evaluate_samples(
        samples,
        generate_answers=False,
        answer_mode="reference",
        retriever_mode="bm25",
    )

    assert error is None
    assert rows[0]["duration_ms"] >= 0
    assert rows[0]["error_type"] is None
    assert rows[1]["error_type"] == "timeout"
    assert rows[1]["metrics"] == {}

    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".evaluation-test-"
    ) as root:
        report_dir = save_evaluation_report(
            rows,
            root,
            "data/evaluation/rag_eval_dataset.jsonl",
            False,
            "reference",
            "bm25",
            False,
        )
        summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["error_count"] == 1
        assert summary["error_types"] == {"timeout": 1}
        assert "duration_ms" in (report_dir / "metrics.csv").read_text(
            encoding="utf-8-sig"
        )


def test_redacted_artifact_does_not_write_evaluation_content() -> None:
    rows = [
        {
            "id": "sample-1",
            "question": "private question",
            "answer": "private answer",
            "reference_answer": "private reference",
            "contexts": ["private context"],
            "retrieved_sources": ["/private/path/manual.txt"],
            "metrics": {"answer_similarity": 0.5},
            "metadata": {"category": "fault", "path": "/private/path"},
            "duration_ms": 1.2,
            "error_type": None,
        }
    ]

    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".evaluation-redacted-"
    ) as root:
        report_dir = save_evaluation_report(
            rows,
            root,
            "data/evaluation/rag_eval_dataset.jsonl",
            False,
            "reference",
            "bm25",
            False,
            artifact_profile="redacted",
        )
        samples = (report_dir / "samples.jsonl").read_text(encoding="utf-8")
        metrics = (report_dir / "metrics.csv").read_text(encoding="utf-8-sig")

    for secret in (
        "private question",
        "private answer",
        "private reference",
        "private context",
        "/private/path",
    ):
        assert secret not in samples
        assert secret not in metrics
