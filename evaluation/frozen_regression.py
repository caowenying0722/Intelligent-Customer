"""Versioned, schema-validated retrieval regression dataset loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.dataset import resolve_project_path


@dataclass(frozen=True)
class FrozenRetrievalSample:
    sample_id: str
    question: str
    expected_sources: tuple[str, ...]
    dataset_version: str


def load_frozen_regression(path: str | Path) -> list[FrozenRetrievalSample]:
    dataset_path = resolve_project_path(path)
    payload: Any = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("frozen regression file must contain a samples list")
    version = payload.get("dataset_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("dataset_version is required")

    samples: list[FrozenRetrievalSample] = []
    seen: set[str] = set()
    for raw in payload["samples"]:
        if not isinstance(raw, dict):
            raise ValueError("each regression sample must be an object")
        sample_id = str(raw.get("sample_id", ""))
        question = str(raw.get("question", ""))
        expected_sources = raw.get("expected_sources")
        if (
            not sample_id
            or not question
            or not isinstance(expected_sources, list)
            or not expected_sources
        ):
            raise ValueError("sample_id, question and expected_sources are required")
        if sample_id in seen:
            raise ValueError(f"duplicate sample_id: {sample_id}")
        seen.add(sample_id)
        samples.append(
            FrozenRetrievalSample(
                sample_id=sample_id,
                question=question,
                expected_sources=tuple(str(item) for item in expected_sources),
                dataset_version=version,
            )
        )
    if not samples:
        raise ValueError("frozen regression dataset must not be empty")
    return samples
