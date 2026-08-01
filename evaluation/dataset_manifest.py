"""Versioned, deterministic evaluation dataset manifest validation."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.dataset import file_sha256, load_jsonl_dataset, resolve_project_path


class DatasetManifestError(ValueError):
    """Raised when a dataset manifest or its data fails validation."""


_SPLITS = frozenset({"dev", "regression", "hidden", "red_team"})
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class DatasetManifest:
    dataset_version: str
    split: str
    dataset_path: Path
    sample_count: int
    sha256: str


def _manifest(raw: dict[str, Any], manifest_path: Path) -> DatasetManifest:
    required = {"dataset_version", "split", "dataset_path", "sample_count", "sha256"}
    missing = sorted(required - raw.keys())
    if missing:
        raise DatasetManifestError(f"manifest missing fields: {', '.join(missing)}")
    version = raw["dataset_version"]
    split = raw["split"]
    sample_count = raw["sample_count"]
    sha256 = raw["sha256"]
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise DatasetManifestError("dataset_version has invalid format")
    if split not in _SPLITS:
        raise DatasetManifestError(f"unsupported dataset split: {split}")
    if not isinstance(sample_count, int) or sample_count < 1:
        raise DatasetManifestError("sample_count must be a positive integer")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise DatasetManifestError("sha256 must be a lowercase SHA-256 digest")
    dataset_path = resolve_project_path(str(raw["dataset_path"]))
    if not dataset_path.is_file():
        raise DatasetManifestError(f"dataset file does not exist: {dataset_path}")
    if dataset_path == manifest_path:
        raise DatasetManifestError("manifest cannot point to itself")
    return DatasetManifest(version, split, dataset_path, sample_count, sha256)


def validate_manifest(path: str | Path) -> dict[str, object]:
    """Validate manifest metadata, file hash, and sample-level invariants."""

    manifest_path = resolve_project_path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetManifestError(f"invalid manifest: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise DatasetManifestError("manifest must be a JSON object")
    manifest = _manifest(raw, manifest_path)
    actual_hash = file_sha256(manifest.dataset_path)
    if actual_hash != manifest.sha256:
        raise DatasetManifestError("dataset SHA-256 does not match manifest")
    samples = load_jsonl_dataset(manifest.dataset_path)
    if len(samples) != manifest.sample_count:
        raise DatasetManifestError("dataset sample_count does not match manifest")
    ids = [sample.id for sample in samples]
    if len(ids) != len(set(ids)):
        raise DatasetManifestError("dataset sample IDs must be unique")
    if any(not sample.question.strip() for sample in samples):
        raise DatasetManifestError("dataset questions must not be empty")
    if any(not str(sample.metadata.get("category", "")).strip() for sample in samples):
        raise DatasetManifestError("dataset samples must declare metadata.category")
    return {
        "dataset_version": manifest.dataset_version,
        "split": manifest.split,
        "dataset_path": str(manifest.dataset_path),
        "sample_count": len(samples),
        "sha256": actual_hash,
        "categories": sorted({str(sample.metadata["category"]) for sample in samples}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="data/evaluation/rag_eval_dataset.manifest.json"
    )
    args = parser.parse_args()
    print(json.dumps(validate_manifest(args.manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
