import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from evaluation.dataset_manifest import DatasetManifestError, validate_manifest


def test_repository_evaluation_manifest_is_valid() -> None:
    summary = validate_manifest("data/evaluation/rag_eval_dataset.manifest.json")

    assert summary["dataset_version"] == "rag-eval-v1"
    assert summary["split"] == "dev"
    assert summary["sample_count"] == 28
    assert "fault" in summary["categories"]


def test_manifest_rejects_duplicate_ids_and_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".dataset-test-"
    ) as directory:
        root = Path(directory)
        dataset = root / "dataset.jsonl"
        dataset.write_text(
            '{"id":"same","question":"a","metadata":{"category":"dev"}}\n'
            '{"id":"same","question":"b","metadata":{"category":"dev"}}\n',
            encoding="utf-8",
        )
        digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "dataset_version": "test-v1",
                    "split": "dev",
                    "dataset_path": str(dataset),
                    "sample_count": 2,
                    "sha256": digest,
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(DatasetManifestError, match="unique"):
            validate_manifest(manifest)

        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_data["sha256"] = "0" * 64
        manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        with pytest.raises(DatasetManifestError, match="SHA-256"):
            validate_manifest(manifest)
