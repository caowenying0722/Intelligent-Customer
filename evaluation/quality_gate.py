"""Deterministic quality gate for previously generated evaluation reports."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evaluation.dataset import resolve_project_path


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]


def load_quality_gate_config(path: str | Path) -> dict[str, Any]:
    """Load finite, explicit gate thresholds from a versioned YAML config."""

    config_path = resolve_project_path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid quality gate config: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("quality gate config must be a mapping")
    thresholds = raw.get("minimum_metrics", {})
    if not isinstance(thresholds, dict):
        raise ValueError("minimum_metrics must be a mapping")
    normalized: dict[str, float] = {}
    for name, value in thresholds.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("quality gate metric names must be non-empty strings")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"quality gate threshold is not numeric: {name}") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"quality gate threshold must be finite: {name}")
        normalized[name] = numeric
    require_complete = raw.get("require_complete", True)
    if not isinstance(require_complete, bool):
        raise ValueError("require_complete must be boolean")
    return {"minimum_metrics": normalized, "require_complete": require_complete}


def evaluate_quality_gate(
    summary: dict[str, Any],
    *,
    minimum_metrics: dict[str, float],
    require_complete: bool = True,
    require_candidate_not_worse: bool = True,
) -> GateResult:
    regression = summary.get("retrieval_regression", {})
    failures: list[str] = []
    for name, minimum in minimum_metrics.items():
        if not math.isfinite(minimum):
            raise ValueError(f"minimum metric threshold must be finite: {name}")
    if require_complete and regression.get("complete") is not True:
        failures.append("retrieval regression dataset is incomplete")
    metrics = regression.get("metrics", {})
    for name, minimum in minimum_metrics.items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)):
            failures.append(f"missing metric: {name}")
        elif float(value) < minimum:
            failures.append(f"{name}={value} is below minimum {minimum}")
    comparison = summary.get("comparison")
    if require_candidate_not_worse and isinstance(comparison, dict):
        baseline = comparison.get("baseline_metrics", {})
        candidate = comparison.get("candidate_metrics", {})
        for metric in ("mrr", "recall@1", "recall@3", "ndcg@3"):
            if metric in baseline and metric in candidate:
                if float(candidate[metric]) < float(baseline[metric]):
                    failures.append(
                        f"candidate {metric} regressed from {baseline[metric]} "
                        f"to {candidate[metric]}"
                    )
    return GateResult(passed=not failures, failures=tuple(failures))


def _parse_metric(value: str) -> tuple[str, float]:
    name, separator, threshold = value.partition("=")
    if not separator or not name.strip():
        raise argparse.ArgumentTypeError("metric threshold must be NAME=VALUE")
    try:
        return name.strip(), float(threshold)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("metric threshold value must be numeric") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--min",
        dest="minimums",
        action="append",
        type=_parse_metric,
        default=[],
        help="minimum metric, e.g. recall@1=0.5; repeatable",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    config = load_quality_gate_config(args.config) if args.config else {}
    minimums = dict(config.get("minimum_metrics", {}))
    minimums.update(dict(args.minimums))
    result = evaluate_quality_gate(
        summary,
        minimum_metrics=minimums,
        require_complete=(
            False
            if args.allow_incomplete
            else bool(config.get("require_complete", True))
        ),
    )
    if result.passed:
        print("quality gate passed")
        return 0
    for failure in result.failures:
        print(f"quality gate failed: {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
