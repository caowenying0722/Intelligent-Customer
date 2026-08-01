from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight and run the official RAGAS ablation report.")
    parser.add_argument("--retriever", choices=["bm25", "hybrid"], default="bm25")
    parser.add_argument("--answer-mode", choices=["llm", "reference", "extractive"], default="extractive")
    parser.add_argument("--output", default="output/evaluation_ablation_ragas")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--ragas-metrics",
        default="answer_relevancy,factual_correctness(mode=f1)",
    )
    parser.add_argument(
        "--ragas-data-mode",
        choices=["minimal", "full"],
        default="minimal",
        help="minimal only sends question/answer/reference for the default metrics; full also sends retrieved contexts.",
    )
    parser.add_argument(
        "--ragas-eval-mode",
        choices=["per_sample", "batch"],
        default="per_sample",
        help="per_sample isolates failures to one sample; batch runs the full dataset in one RAGAS call.",
    )
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Do not print the interview/demo quality summary after the ablation run.",
    )
    parser.add_argument(
        "--ack-external-judge",
        action="store_true",
        help="Acknowledge that official RAGAS sends evaluation content to the external judge LLM; full data mode may include retrieved contexts.",
    )
    args = parser.parse_args()
    if args.ack_external_judge:
        os.environ["RAGAS_ACK_EXTERNAL_JUDGE"] = "1"

    preflight = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "preflight_ragas.py"),
        "--metrics",
        args.ragas_metrics,
        "--strict",
    ]
    preflight_result = subprocess.run(preflight, cwd=PROJECT_ROOT)
    if preflight_result.returncode != 0:
        print("RAGAS ablation stopped because preflight is not ready.")
        print("Run `python scripts/setup_private_env.py` or create a local .env, then retry.")
        raise SystemExit(preflight_result.returncode)

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "compare_rag_ablation.py"),
        "--retriever",
        args.retriever,
        "--answer-mode",
        args.answer_mode,
        "--run-ragas",
        "--ragas-metrics",
        args.ragas_metrics,
        "--ragas-data-mode",
        args.ragas_data_mode,
        "--ragas-eval-mode",
        args.ragas_eval_mode,
        "--output",
        args.output,
    ]
    if args.ack_external_judge:
        command.append("--ack-external-judge")
    if args.limit:
        command.extend(["--limit", str(args.limit)])
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    if not args.skip_summary:
        comparison_path = PROJECT_ROOT / args.output / "comparison" / "comparison.json"
        summary_command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "summarize_quality_report.py"),
            "--comparison",
            str(comparison_path),
        ]
        raise SystemExit(subprocess.run(summary_command, cwd=PROJECT_ROOT).returncode)

    raise SystemExit(0)


if __name__ == "__main__":
    main()
