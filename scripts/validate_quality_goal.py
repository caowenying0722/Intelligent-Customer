from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = PROJECT_ROOT / ".local_deps"
if LOCAL_DEPS.exists() and str(LOCAL_DEPS) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPS))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


REQUIRED_POSITIVE_METRICS = [
    "answer_keyword_accuracy",
]

OFFICIAL_RAGAS_METRICS = [
    "answer_relevancy",
    "factual_correctness(mode=f1)",
]

PROXY_FALLBACK_METRICS = [
    "answer_relevancy_proxy",
    "factual_correctness_proxy",
]


def read_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader) or {}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def metric_delta(comparison: dict[str, Any], name: str) -> float | None:
    metric = comparison.get("metrics", {}).get(name)
    if not metric:
        return None
    value = metric.get("percentage_point_delta")
    return float(value) if isinstance(value, (int, float)) else None


def metric_present(comparison: dict[str, Any], name: str) -> bool:
    return name in comparison.get("metrics", {})


def metric_has_positive_delta(comparison: dict[str, Any], name: str) -> bool:
    delta = metric_delta(comparison, name)
    return delta is not None and delta > 0


def find_latest_comparison(output_dir: Path) -> Path | None:
    candidates = list(output_dir.glob("**/comparison.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def validate(comparison_path: Path | None) -> list[CheckResult]:
    results: list[CheckResult] = []

    chroma_config = read_yaml(PROJECT_ROOT / "config" / "chroma.yml")
    results.append(
        CheckResult(
            "rerank_config",
            bool(chroma_config.get("rerank_enabled"))
            and int(chroma_config.get("candidate_k", 0)) > int(chroma_config.get("k", 0))
            and int(chroma_config.get("rerank_top_k", 0)) == int(chroma_config.get("k", 0)),
            (
                f"candidate_k={chroma_config.get('candidate_k')}, "
                f"k={chroma_config.get('k')}, "
                f"rerank_enabled={chroma_config.get('rerank_enabled')}, "
                f"rerank_top_k={chroma_config.get('rerank_top_k')}"
            ),
        )
    )

    results.append(
        CheckResult(
            "reranker_module",
            (PROJECT_ROOT / "rag" / "reranker.py").exists(),
            "rag/reranker.py exists",
        )
    )
    results.append(
        CheckResult(
            "guardrails_module",
            (PROJECT_ROOT / "rag" / "guardrails.py").exists(),
            "rag/guardrails.py exists",
        )
    )

    prompt_text = read_text(PROJECT_ROOT / "prompts" / "rag_summarize.txt")
    results.append(
        CheckResult(
            "citation_prompt",
            "【资料" in prompt_text and "每个关键结论" in prompt_text,
            "prompt requires numbered evidence citations",
        )
    )
    results.append(
        CheckResult(
            "low_confidence_prompt",
            "知识库未提供足够依据" in prompt_text,
            "prompt requires low-confidence abstention",
        )
    )

    secret_scan = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "scan_secrets.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    results.append(
        CheckResult(
            "secret_scan",
            secret_scan.returncode == 0,
            secret_scan.stdout.strip() or secret_scan.stderr.strip(),
        )
    )

    dataset_path = PROJECT_ROOT / "data" / "evaluation" / "rag_eval_dataset.jsonl"
    dataset_lines = [line for line in read_text(dataset_path).splitlines() if line.strip()]
    ood_count = sum(1 for line in dataset_lines if json.loads(line).get("metadata", {}).get("expect_low_confidence"))
    results.append(
        CheckResult(
            "evaluation_dataset",
            len(dataset_lines) >= 20 and ood_count >= 4,
            f"samples={len(dataset_lines)}, out_of_scope={ood_count}",
        )
    )

    if comparison_path is None:
        results.append(CheckResult("comparison_report", False, "no comparison.json found"))
        return results

    comparison = read_json(comparison_path)
    results.append(
        CheckResult(
            "comparison_report",
            comparison_path.exists(),
            str(comparison_path),
        )
    )

    improved_config = comparison.get("improved_config", {})
    baseline_config = comparison.get("baseline_config", {})
    results.append(
        CheckResult(
            "ablation_design",
            bool(improved_config.get("rerank_enabled"))
            and not bool(baseline_config.get("rerank_enabled"))
            and int(improved_config.get("candidate_k", 0)) > int(baseline_config.get("candidate_k", 0)),
            f"baseline={baseline_config}, improved={improved_config}",
        )
    )

    for metric_name in REQUIRED_POSITIVE_METRICS:
        delta = metric_delta(comparison, metric_name)
        results.append(
            CheckResult(
                f"positive_{metric_name}",
                delta is not None and delta > 0,
                f"delta={delta}",
            )
        )

    for metric_name in OFFICIAL_RAGAS_METRICS:
        delta = metric_delta(comparison, metric_name)
        results.append(
            CheckResult(
                f"official_{metric_name}",
                delta is not None and delta > 0,
                f"delta={delta}" if delta is not None else "missing",
                required=True,
            )
        )

    for metric_name in PROXY_FALLBACK_METRICS:
        results.append(
            CheckResult(
                f"proxy_{metric_name}",
                metric_present(comparison, metric_name),
                "present" if metric_present(comparison, metric_name) else "missing",
                required=False,
            )
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate whether the RAG quality-engineering goal is fully satisfied.")
    parser.add_argument("--comparison", type=Path, default=None, help="Path to comparison.json.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output", help="Search root for comparison.json.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any required check fails.")
    args = parser.parse_args()

    comparison_path = args.comparison or find_latest_comparison(args.output_dir)
    results = validate(comparison_path)
    payload = {
        "ok": all(result.ok for result in results if result.required),
        "comparison": str(comparison_path) if comparison_path else None,
        "checks": [result.__dict__ for result in results],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Quality goal validation: {'OK' if payload['ok'] else 'INCOMPLETE'}")
        print(f"- comparison: {payload['comparison'] or 'none'}")
        for result in results:
            status = "OK" if result.ok else ("WARN" if not result.required else "FAIL")
            print(f"- [{status}] {result.name}: {result.detail}")

    if args.strict and not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
