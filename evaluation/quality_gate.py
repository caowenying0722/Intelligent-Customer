"""Deterministic quality gate for previously generated evaluation reports."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]


def evaluate_quality_gate(
    summary: dict[str, Any],
    *,
    minimum_metrics: dict[str, float],
    require_complete: bool = True,
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
    result = evaluate_quality_gate(
        summary,
        minimum_metrics=dict(args.minimums),
        require_complete=not args.allow_incomplete,
    )
    if result.passed:
        print("quality gate passed")
        return 0
    for failure in result.failures:
        print(f"quality gate failed: {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
