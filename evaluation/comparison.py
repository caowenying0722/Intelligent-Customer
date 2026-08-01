from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from evaluation.dataset import resolve_project_path


def _load_summary(report_dir: str | Path) -> dict[str, Any]:
    summary_path = resolve_project_path(report_dir) / "summary.json"
    with summary_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_sample_rows(report_dir: str | Path) -> list[dict[str, Any]]:
    samples_path = resolve_project_path(report_dir) / "samples.jsonl"
    if not samples_path.exists():
        return []

    rows = []
    with samples_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _metric_value(row: dict[str, Any], metric_name: str) -> float | None:
    metrics = row.get("metrics", {})
    ragas_metrics = row.get("ragas_metrics", {})
    value = metrics.get(metric_name, ragas_metrics.get(metric_name))
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _metric_delta(
    baseline_value: float,
    improved_value: float,
    paired_sample_count: int | None = None,
    aggregation: str = "summary",
) -> dict[str, float | int | str]:
    absolute_delta = round(improved_value - baseline_value, 6)
    relative_delta = 0.0
    if baseline_value != 0:
        relative_delta = round(absolute_delta / baseline_value, 6)
    payload: dict[str, float | int | str] = {
        "baseline": baseline_value,
        "improved": improved_value,
        "absolute_delta": absolute_delta,
        "percentage_point_delta": round(absolute_delta * 100, 2),
        "relative_delta": relative_delta,
        "relative_percent_delta": round(relative_delta * 100, 2),
        "aggregation": aggregation,
    }
    if paired_sample_count is not None:
        payload["paired_sample_count"] = paired_sample_count
    return payload


def _summary_metric_deltas(
    baseline_metrics: dict[str, Any],
    improved_metrics: dict[str, Any],
    metric_names: list[str],
) -> dict[str, dict[str, float | int | str]]:
    return {
        metric_name: _metric_delta(
            float(baseline_metrics[metric_name]),
            float(improved_metrics[metric_name]),
            aggregation="summary",
        )
        for metric_name in metric_names
        if isinstance(baseline_metrics.get(metric_name), (int, float))
        and isinstance(improved_metrics.get(metric_name), (int, float))
        and math.isfinite(float(baseline_metrics[metric_name]))
        and math.isfinite(float(improved_metrics[metric_name]))
    }


def _paired_metric_deltas(
    baseline_rows: list[dict[str, Any]],
    improved_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int | str]]:
    baseline_by_id = {
        str(row.get("id")): row for row in baseline_rows if row.get("id") is not None
    }
    improved_by_id = {
        str(row.get("id")): row for row in improved_rows if row.get("id") is not None
    }
    paired_ids = sorted(set(baseline_by_id) & set(improved_by_id))

    metric_names: set[str] = set()
    for sample_id in paired_ids:
        for row in (baseline_by_id[sample_id], improved_by_id[sample_id]):
            metric_names.update(row.get("metrics", {}).keys())
            metric_names.update(row.get("ragas_metrics", {}).keys())

    deltas: dict[str, dict[str, float | int | str]] = {}
    for metric_name in sorted(metric_names):
        baseline_values = []
        improved_values = []
        for sample_id in paired_ids:
            baseline_value = _metric_value(baseline_by_id[sample_id], metric_name)
            improved_value = _metric_value(improved_by_id[sample_id], metric_name)
            if baseline_value is None or improved_value is None:
                continue
            baseline_values.append(baseline_value)
            improved_values.append(improved_value)

        if not baseline_values:
            continue

        baseline_average = round(sum(baseline_values) / len(baseline_values), 6)
        improved_average = round(sum(improved_values) / len(improved_values), 6)
        deltas[metric_name] = _metric_delta(
            baseline_average,
            improved_average,
            paired_sample_count=len(baseline_values),
            aggregation="paired_samples",
        )

    return deltas


def _ordered_metrics(
    metrics: dict[str, dict[str, float | int | str]],
    focus_metrics: list[str] | None,
) -> dict[str, dict[str, float | int | str]]:
    metric_names = sorted(metrics)
    if focus_metrics:
        focused_names = [name for name in focus_metrics if name in metrics]
        remaining_names = [name for name in metric_names if name not in focused_names]
        metric_names = focused_names + remaining_names
    return {metric_name: metrics[metric_name] for metric_name in metric_names}


def compare_summaries(
    baseline_report_dir: str | Path,
    improved_report_dir: str | Path,
    output_dir: str | Path,
    focus_metrics: list[str] | None = None,
) -> Path:
    baseline_summary = _load_summary(baseline_report_dir)
    improved_summary = _load_summary(improved_report_dir)
    baseline_metrics = baseline_summary.get("metrics", {})
    improved_metrics = improved_summary.get("metrics", {})
    baseline_rows = _load_sample_rows(baseline_report_dir)
    improved_rows = _load_sample_rows(improved_report_dir)
    paired_metrics = _paired_metric_deltas(baseline_rows, improved_rows)
    if paired_metrics:
        metrics = _ordered_metrics(paired_metrics, focus_metrics)
    else:
        metric_names = sorted(set(baseline_metrics) & set(improved_metrics))
        metrics = _ordered_metrics(
            _summary_metric_deltas(baseline_metrics, improved_metrics, metric_names),
            focus_metrics,
        )

    comparison = {
        "baseline_report_dir": str(resolve_project_path(baseline_report_dir)),
        "improved_report_dir": str(resolve_project_path(improved_report_dir)),
        "baseline_config": baseline_summary.get("rag_config", {}),
        "improved_config": improved_summary.get("rag_config", {}),
        "sample_count": improved_summary.get("sample_count"),
        "generate_answers": improved_summary.get("generate_answers"),
        "ragas_enabled": improved_summary.get("ragas_enabled"),
        "baseline_ragas_data_mode": baseline_summary.get("ragas_data_mode"),
        "improved_ragas_data_mode": improved_summary.get("ragas_data_mode"),
        "baseline_ragas_eval_mode": baseline_summary.get("ragas_eval_mode"),
        "improved_ragas_eval_mode": improved_summary.get("ragas_eval_mode"),
        "baseline_ragas_error": baseline_summary.get("ragas_error"),
        "improved_ragas_error": improved_summary.get("ragas_error"),
        "baseline_judge_llm": baseline_summary.get("judge_llm", {}),
        "improved_judge_llm": improved_summary.get("judge_llm", {}),
        "metric_aggregation": "paired_samples" if paired_metrics else "summary",
        "metrics": metrics,
    }

    comparison_dir = resolve_project_path(output_dir)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    with (comparison_dir / "comparison.json").open("w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    _write_markdown_report(comparison, comparison_dir / "comparison.md")
    return comparison_dir


def _write_markdown_report(comparison: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# RAG 消融实验对比",
        "",
        f"- 样本数：{comparison.get('sample_count')}",
        f"- 是否生成答案：{comparison.get('generate_answers')}",
        f"- 是否启用 RAGAS：{comparison.get('ragas_enabled')}",
        f"- 指标聚合方式：{comparison.get('metric_aggregation') or '未记录'}",
        f"- RAGAS 数据模式：{comparison.get('improved_ragas_data_mode') or '未记录'}",
        f"- RAGAS 运行模式：{comparison.get('improved_ragas_eval_mode') or '未记录'}",
        f"- Baseline RAGAS 错误：{comparison.get('baseline_ragas_error') or '无'}",
        f"- Improved RAGAS 错误：{comparison.get('improved_ragas_error') or '无'}",
        f"- Baseline：`{comparison.get('baseline_report_dir')}`",
        f"- Improved：`{comparison.get('improved_report_dir')}`",
        "",
        "| 指标 | Baseline | Improved | 提升百分点 | 相对提升 | 成对样本 |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for metric_name, values in comparison.get("metrics", {}).items():
        lines.append(
            "| {name} | {baseline:.6f} | {improved:.6f} | {pp:+.2f} | {rel:+.2f}% | {paired} |".format(
                name=metric_name,
                baseline=values["baseline"],
                improved=values["improved"],
                pp=values["percentage_point_delta"],
                rel=values["relative_percent_delta"],
                paired=values.get("paired_sample_count", "n/a"),
            )
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
