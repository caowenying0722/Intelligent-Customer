from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_FOCUS_METRICS = [
    "answer_relevancy",
    "factual_correctness(mode=f1)",
    "answer_keyword_accuracy",
    "answer_relevancy_proxy",
    "factual_correctness_proxy",
    "answer_citation_coverage",
    "answer_citation_validity",
    "low_confidence_accuracy",
    "source_recall",
    "retrieval_mrr",
    "retrieval_recall",
    "retrieval_precision",
]

OFFICIAL_RAGAS_METRICS = ["answer_relevancy", "factual_correctness(mode=f1)"]
PROXY_METRICS = ["answer_relevancy_proxy", "factual_correctness_proxy"]


def find_latest_comparison(output_dir: Path) -> Path:
    candidates = list(output_dir.glob("**/comparison.json"))
    if not candidates:
        raise FileNotFoundError(f"No comparison.json found under {output_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_comparison(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def metric_rows(
    comparison: dict[str, Any], focus_metrics: list[str]
) -> list[tuple[str, float, float, float, float, int | None]]:
    metrics = comparison.get("metrics", {})
    rows = []
    for name in focus_metrics:
        item = metrics.get(name)
        if not item:
            continue
        rows.append(
            (
                name,
                float(item.get("baseline", 0.0)),
                float(item.get("improved", 0.0)),
                float(item.get("percentage_point_delta", 0.0)),
                float(item.get("relative_percent_delta", 0.0)),
                item.get("paired_sample_count")
                if isinstance(item.get("paired_sample_count"), int)
                else None,
            )
        )
    return rows


def available_metrics(comparison: dict[str, Any], names: list[str]) -> list[str]:
    metrics = comparison.get("metrics", {})
    return [name for name in names if name in metrics]


def build_markdown(
    comparison_path: Path,
    comparison: dict[str, Any],
    rows: list[tuple[str, float, float, float, float, int | None]],
) -> str:
    baseline_config = comparison.get("baseline_config", {})
    improved_config = comparison.get("improved_config", {})
    sample_count = comparison.get("sample_count", "unknown")
    ragas_enabled = comparison.get("ragas_enabled", False)
    ragas_data_mode = comparison.get("improved_ragas_data_mode")
    ragas_eval_mode = comparison.get("improved_ragas_eval_mode")
    official_metrics = available_metrics(comparison, OFFICIAL_RAGAS_METRICS)
    proxy_metrics = available_metrics(comparison, PROXY_METRICS)
    improved_judge = comparison.get("improved_judge_llm", {})

    lines = [
        "# RAG Quality Showcase",
        "",
        f"- Report: `{comparison_path}`",
        f"- Samples: {sample_count}",
        f"- Metric aggregation: {comparison.get('metric_aggregation', 'not recorded')}",
        f"- RAGAS enabled: {ragas_enabled}",
        f"- RAGAS data mode: {ragas_data_mode or 'not recorded'}",
        f"- RAGAS eval mode: {ragas_eval_mode or 'not recorded'}",
        f"- Official RAGAS metrics: {', '.join(official_metrics) if official_metrics else 'not available'}",
        f"- Proxy metrics: {', '.join(proxy_metrics) if proxy_metrics else 'not available'}",
        f"- Judge LLM: {improved_judge.get('provider', 'unknown')} / {improved_judge.get('chat_model_name', 'unknown')}",
        f"- Judge key present: {', '.join(improved_judge.get('present_keys', [])) if improved_judge.get('present_keys') else 'none'}",
        f"- Baseline: candidate_k={baseline_config.get('candidate_k')}, rerank={baseline_config.get('rerank_enabled')}",
        f"- Improved: candidate_k={improved_config.get('candidate_k')}, rerank={improved_config.get('rerank_enabled')}, rerank_top_k={improved_config.get('rerank_top_k')}",
        "",
        "## Metrics",
        "",
        "| Metric | Baseline | Improved | Delta Points | Relative Delta | Paired Samples |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, baseline, improved, point_delta, relative_delta, paired_count in rows:
        paired_text = str(paired_count) if paired_count is not None else "n/a"
        lines.append(
            f"| {name} | {baseline:.6f} | {improved:.6f} | {point_delta:+.2f} | {relative_delta:+.2f}% | {paired_text} |"
        )

    best_positive = [row for row in rows if row[3] > 0]
    best_positive.sort(key=lambda row: row[3], reverse=True)

    lines.extend(["", "## Interview Bullets", ""])
    if best_positive:
        for (
            name,
            baseline,
            improved,
            point_delta,
            relative_delta,
            paired_count,
        ) in best_positive[:5]:
            paired_note = (
                f", paired n={paired_count}" if paired_count is not None else ""
            )
            lines.append(
                f"- {name}: {baseline:.4f} -> {improved:.4f}, +{point_delta:.2f} pts ({relative_delta:+.2f}%{paired_note})."
            )
    else:
        lines.append("- No positive metric deltas in this comparison slice.")

    if not ragas_enabled:
        lines.extend(
            [
                "",
                "## Caveat",
                "",
                "This report uses local/proxy metrics. Run `python scripts/run_ragas_ablation.py` after configuring `.env` for official RAGAS metrics.",
            ]
        )
    elif len(official_metrics) < len(OFFICIAL_RAGAS_METRICS):
        missing_metrics = [
            name for name in OFFICIAL_RAGAS_METRICS if name not in official_metrics
        ]
        ragas_error = comparison.get("improved_ragas_error") or comparison.get(
            "baseline_ragas_error"
        )
        lines.extend(
            [
                "",
                "## Caveat",
                "",
                "RAGAS was enabled, but these official metrics were not present with finite values: "
                + ", ".join(missing_metrics)
                + ". Check the report `ragas_error` fields and rerun `python scripts/run_ragas_ablation.py`.",
            ]
        )
        if ragas_error:
            lines.append(f"Latest RAGAS error: {ragas_error}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize a RAG comparison report for interview/demo use."
    )
    parser.add_argument(
        "--comparison", type=Path, default=None, help="Path to comparison.json."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory used to auto-discover comparison.json.",
    )
    parser.add_argument(
        "--markdown-out", type=Path, default=None, help="Optional markdown output path."
    )
    parser.add_argument(
        "--focus-metric",
        action="append",
        default=None,
        help="Metric to include. Can be repeated.",
    )
    args = parser.parse_args()

    comparison_path = args.comparison or find_latest_comparison(args.output_dir)
    comparison = load_comparison(comparison_path)
    focus_metrics = args.focus_metric or DEFAULT_FOCUS_METRICS
    rows = metric_rows(comparison, focus_metrics)
    markdown = build_markdown(comparison_path, comparison, rows)

    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")

    print(markdown)


if __name__ == "__main__":
    main()
