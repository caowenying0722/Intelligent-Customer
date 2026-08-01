from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.path_tool import get_abs_path


@dataclass
class EvaluationSample:
    id: str
    question: str
    reference_answer: str
    expected_keywords: list[list[str]] = field(default_factory=list)
    expected_sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvaluationSample:
        keyword_groups = raw.get("expected_keywords", [])
        normalized_keywords = []
        for item in keyword_groups:
            if isinstance(item, str):
                normalized_keywords.append([item])
            elif isinstance(item, list):
                normalized_keywords.append([str(keyword) for keyword in item])

        return cls(
            id=str(raw["id"]),
            question=str(raw["question"]),
            reference_answer=str(raw.get("reference_answer", "")),
            expected_keywords=normalized_keywords,
            expected_sources=[
                str(source) for source in raw.get("expected_sources", [])
            ],
            metadata=dict(raw.get("metadata", {})),
        )


def resolve_project_path(path: str | Path) -> Path:
    path_obj = Path(path)
    if path_obj.is_absolute():
        return path_obj
    return Path(get_abs_path(str(path_obj)))


def load_jsonl_dataset(path: str | Path) -> list[EvaluationSample]:
    dataset_path = resolve_project_path(path)
    samples: list[EvaluationSample] = []

    with dataset_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                samples.append(EvaluationSample.from_dict(json.loads(line)))
            except Exception as exc:
                raise ValueError(
                    f"Invalid evaluation sample at {dataset_path}:{line_no}: {exc}"
                ) from exc

    if not samples:
        raise ValueError(f"No evaluation samples found in {dataset_path}")

    return samples
