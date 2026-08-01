from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.runner import run_evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run RAG retrieval and answer quality evaluation."
    )
    parser.add_argument(
        "--config", default="config/evaluation.yml", help="Evaluation config path."
    )
    parser.add_argument(
        "--dataset", default=None, help="Evaluation dataset JSONL path."
    )
    parser.add_argument(
        "--output", default=None, help="Directory for evaluation reports."
    )
    parser.add_argument(
        "--artifact-profile",
        choices=["redacted", "full"],
        default=None,
        help="Report artifact profile; redacted is the safe default, full is for controlled local debugging.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only evaluate the first N samples."
    )
    parser.add_argument(
        "--run-ragas", action="store_true", help="Enable optional RAGAS metrics."
    )
    parser.add_argument(
        "--ack-external-judge",
        action="store_true",
        help="Acknowledge that RAGAS sends evaluation content to the configured external judge LLM; full data mode may include retrieved contexts.",
    )
    parser.add_argument(
        "--no-ragas",
        action="store_true",
        help="Disable RAGAS even if enabled in config.",
    )
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Skip LLM answer generation and evaluate retrieval only.",
    )
    parser.add_argument(
        "--answer-mode",
        choices=["llm", "reference", "extractive"],
        default=None,
        help="Answer source for local evaluation. extractive builds cited answers from retrieved evidence without an LLM.",
    )
    parser.add_argument(
        "--retriever",
        choices=["hybrid", "bm25"],
        default=None,
        help="Retriever mode. hybrid uses the project RAG service; bm25 avoids local embedding model loading.",
    )
    parser.add_argument(
        "--ragas-metrics",
        default=None,
        help="Comma-separated RAGAS metric names, for example: answer_relevancy,factual_correctness(mode=f1),context_recall",
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
    parser.add_argument(
        "--disable-rerank",
        action="store_true",
        help="Disable evidence reranking for ablation.",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=None,
        help="Override reranked evidence count.",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=None,
        help="Override first-stage retrieval candidate count.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ack_external_judge:
        os.environ["RAGAS_ACK_EXTERNAL_JUDGE"] = "1"
    run_ragas = None
    if args.run_ragas:
        run_ragas = True
    if args.no_ragas:
        run_ragas = False

    rag_config_overrides = {}
    if args.disable_rerank:
        rag_config_overrides["rerank_enabled"] = False
    if args.rerank_top_k:
        rag_config_overrides["rerank_top_k"] = args.rerank_top_k
    if args.candidate_k:
        rag_config_overrides["candidate_k"] = args.candidate_k

    run_evaluation(
        config_path=args.config,
        dataset_path=args.dataset,
        output_dir=args.output,
        limit=args.limit,
        run_ragas=run_ragas,
        generate_answers=False if args.no_generate else None,
        answer_mode=args.answer_mode,
        retriever_mode=args.retriever,
        ragas_metrics=args.ragas_metrics.split(",") if args.ragas_metrics else None,
        ragas_data_mode=args.ragas_data_mode,
        ragas_eval_mode=args.ragas_eval_mode,
        rag_config_overrides=rag_config_overrides,
        artifact_profile=args.artifact_profile,
    )


if __name__ == "__main__":
    main()
