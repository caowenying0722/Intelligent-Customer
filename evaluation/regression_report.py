"""Build traceable retrieval regression summaries from runner rows."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from evaluation.frozen_regression import load_frozen_regression
from evaluation.retrieval_metrics import evaluate_retrieval
from evaluation.dataset import file_sha256, resolve_project_path


def repository_snapshot() -> dict[str, Any]:
    """Capture commit and dirty state without making evaluation depend on Git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return {"commit": commit, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def build_retrieval_regression_summary(
    rows: list[dict[str, Any]], dataset_path: str | Path
) -> dict[str, Any]:
    samples = load_frozen_regression(dataset_path)
    rows_by_id = {str(row.get("id")): row for row in rows}
    expected = {sample.sample_id: sample.expected_sources for sample in samples}
    retrieved = {
        sample_id: [str(item) for item in rows_by_id[sample_id].get("retrieved_sources", [])]
        for sample_id in expected
        if sample_id in rows_by_id
    }
    missing = sorted(set(expected) - set(retrieved))
    summary: dict[str, Any] = {
        "dataset_path": str(resolve_project_path(dataset_path)),
        "dataset_version": samples[0].dataset_version,
        "dataset_sha256": file_sha256(dataset_path),
        "sample_count": len(samples),
        "evaluated_count": len(retrieved),
        "missing_sample_ids": missing,
        "complete": not missing,
    }
    if retrieved:
        summary["metrics"] = evaluate_retrieval(
            retrieved,
            {sample_id: expected[sample_id] for sample_id in retrieved},
        )
    else:
        summary["metrics"] = {}
    return summary
