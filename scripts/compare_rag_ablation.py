from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = PROJECT_ROOT / ".local_deps"
if LOCAL_DEPS.exists() and str(LOCAL_DEPS) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPS))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runner import run_evaluation
from evaluation.comparison import compare_summaries
from utils.config_handler import chroma_conf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline vs reranked RAG ablation experiments.")
    parser.add_argument("--config", default="config/evaluation.yml", help="Evaluation config path.")
    parser.add_argument("--dataset", default=None, help="Evaluation dataset JSONL path.")
    parser.add_argument("--output", default="output/evaluation_ablation", help="Directory for ablation reports.")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N samples.")
    parser.add_argument("--run-ragas", action="store_true", help="Enable optional RAGAS metrics.")
    parser.add_argument(
        "--ack-external-judge",
        action="store_true",
        help="Acknowledge that RAGAS sends evaluation content to the configured external judge LLM; full data mode may include retrieved contexts.",
    )
    parser.add_argument(
        "--ragas-metrics",
        default=None,
        help="Comma-separated RAGAS metric names, for example: answer_relevancy,factual_correctness(mode=f1)",
    )
    parser.add_argument(
        "--ragas-data-mode",
        choices=["minimal", "full"],
        default=None,
        help="minimal only sends fields required by selected metrics; full also sends retrieved contexts.",
    )
    parser.add_argument(
        "--ragas-eval-mode",
        choices=["per_sample", "batch"],
        default=None,
        help="per_sample isolates failures to one sample; batch runs the full dataset in one RAGAS call.",
    )
    parser.add_argument("--no-generate", action="store_true", help="Skip LLM answer generation.")
    parser.add_argument(
        "--answer-mode",
        choices=["llm", "reference", "extractive"],
        default=None,
        help="Answer source for local evaluation. Use extractive to measure cited answer quality without an LLM.",
    )
    parser.add_argument(
        "--retriever",
        choices=["hybrid", "bm25"],
        default="hybrid",
        help="Retriever mode for ablation. Use bm25 for dependency-light smoke tests.",
    )
    parser.add_argument(
        "--focus-metrics",
        default=(
            "answer_relevancy,factual_correctness(mode=f1),answer_keyword_accuracy,"
            "answer_relevancy_proxy,factual_correctness_proxy,"
            "answer_citation_coverage,answer_citation_validity,low_confidence_accuracy,"
            "answer_context_overlap,source_recall,retrieval_mrr,retrieval_recall,retrieval_precision"
        ),
        help="Comma-separated metric names to show first in comparison reports.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ack_external_judge:
        os.environ["RAGAS_ACK_EXTERNAL_JUDGE"] = "1"
    baseline_k = chroma_conf.get("k", 3)
    candidate_k = chroma_conf.get("candidate_k", max(baseline_k, 8))
    rerank_top_k = chroma_conf.get("rerank_top_k", max(baseline_k, 5))

    experiments = [
        (
            f"baseline_{args.retriever}",
            {
                "candidate_k": baseline_k,
                "rerank_enabled": False,
                "rerank_top_k": baseline_k,
            },
        ),
        (
            f"{args.retriever}_rerank_evidence",
            {
                "candidate_k": candidate_k,
                "rerank_enabled": True,
                "rerank_top_k": rerank_top_k,
            },
        ),
    ]

    report_dirs: dict[str, Path] = {}
    for name, overrides in experiments:
        print(f"[RAG消融] 开始实验: {name}")
        report_dir = run_evaluation(
            config_path=args.config,
            dataset_path=args.dataset,
            output_dir=str(Path(args.output) / name),
            limit=args.limit,
            run_ragas=args.run_ragas,
            generate_answers=False if args.no_generate else None,
            answer_mode=args.answer_mode,
            retriever_mode=args.retriever,
            ragas_metrics=args.ragas_metrics.split(",") if args.ragas_metrics else None,
            ragas_data_mode=args.ragas_data_mode,
            ragas_eval_mode=args.ragas_eval_mode,
            rag_config_overrides=overrides,
        )
        report_dirs[name] = report_dir
        print(f"[RAG消融] {name} 报告目录: {report_dir}")

    comparison_dir = compare_summaries(
        baseline_report_dir=report_dirs[f"baseline_{args.retriever}"],
        improved_report_dir=report_dirs[f"{args.retriever}_rerank_evidence"],
        output_dir=Path(args.output) / "comparison",
        focus_metrics=[metric.strip() for metric in args.focus_metrics.split(",") if metric.strip()],
    )
    print(f"[RAG消融] 对比报告目录: {comparison_dir}")


if __name__ == "__main__":
    main()
