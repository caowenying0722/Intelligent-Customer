"""Run model-free red-team checks against deterministic Agent safety policies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.dataset import file_sha256, load_jsonl_dataset, resolve_project_path
from evaluation.dataset_manifest import validate_manifest
from src.app.security.prompt_guard import PromptInjectionError, PromptSafetyPolicy


def run(manifest_path: str, output_path: str) -> Path:
    manifest_summary = validate_manifest(manifest_path)
    dataset_path = str(manifest_summary["dataset_path"])
    samples = load_jsonl_dataset(dataset_path)
    policy = PromptSafetyPolicy()
    rows: list[dict[str, Any]] = []
    false_negatives: list[str] = []
    invalid_cases: list[str] = []
    for sample in samples:
        expected_action = sample.metadata.get("expected_action")
        if expected_action != "refuse":
            invalid_cases.append(sample.id)
            continue
        refused = False
        try:
            policy.check(sample.question)
        except PromptInjectionError:
            refused = True
        if not refused:
            false_negatives.append(sample.id)
        rows.append(
            {
                "id": sample.id,
                "expected_action": expected_action,
                "observed_action": "refuse" if refused else "allow",
            }
        )

    summary = {
        "security_regression": {
            "complete": not invalid_cases,
            "dataset_version": manifest_summary["dataset_version"],
            "dataset_sha256": file_sha256(dataset_path),
            "case_count": len(samples),
            "blocked_count": sum(row["observed_action"] == "refuse" for row in rows),
            "false_negatives": false_negatives,
            "invalid_cases": invalid_cases,
            "results": rows,
        },
        "model_calls": 0,
    }
    destination = resolve_project_path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if false_negatives or invalid_cases:
        raise RuntimeError("red-team regression failed")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="data/evaluation/red_team/prompt_injection.manifest.json",
    )
    parser.add_argument("--output", default="output/evaluation/red-team-summary.json")
    args = parser.parse_args()
    print(run(args.manifest, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
