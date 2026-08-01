from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], allow_failure: bool = False) -> int:
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0 and not allow_failure:
        raise SystemExit(result.returncode)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RAG quality-engineering pipeline.")
    parser.add_argument("--proxy-output", default="output/evaluation_ablation_bm25_proxy_pipeline")
    parser.add_argument("--ragas-output", default="output/evaluation_ablation_ragas")
    parser.add_argument("--retriever", choices=["bm25", "hybrid"], default="bm25")
    parser.add_argument("--answer-mode", choices=["llm", "reference", "extractive"], default="extractive")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-ragas", action="store_true", help="Only run the dependency-light proxy report.")
    parser.add_argument(
        "--ragas-data-mode",
        choices=["minimal", "full"],
        default="minimal",
        help="minimal only sends fields required by selected RAGAS metrics; full also sends retrieved contexts.",
    )
    parser.add_argument(
        "--ragas-eval-mode",
        choices=["per_sample", "batch"],
        default="per_sample",
        help="per_sample isolates failures to one sample; batch runs the full dataset in one RAGAS call.",
    )
    parser.add_argument(
        "--ack-external-judge",
        action="store_true",
        help="Acknowledge that official RAGAS sends evaluation content to the external judge LLM; full data mode may include retrieved contexts.",
    )
    args = parser.parse_args()
    if args.ack_external_judge:
        os.environ["RAGAS_ACK_EXTERNAL_JUDGE"] = "1"

    proxy_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "compare_rag_ablation.py"),
        "--retriever",
        args.retriever,
        "--no-generate",
        "--answer-mode",
        args.answer_mode,
        "--output",
        args.proxy_output,
    ]
    if args.limit:
        proxy_command.extend(["--limit", str(args.limit)])

    print("[quality-pipeline] Running proxy/local ablation report...")
    run(proxy_command)

    proxy_comparison = PROJECT_ROOT / args.proxy_output / "comparison" / "comparison.json"
    print("[quality-pipeline] Proxy summary:")
    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "summarize_quality_report.py"),
            "--comparison",
            str(proxy_comparison),
        ]
    )

    print("[quality-pipeline] Current goal validation against proxy report:")
    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "validate_quality_goal.py"),
            "--comparison",
            str(proxy_comparison),
        ],
        allow_failure=True,
    )

    if args.skip_ragas:
        print("[quality-pipeline] Skipping official RAGAS run by request.")
        return

    print("[quality-pipeline] Checking official RAGAS readiness...")
    preflight_code = run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "preflight_ragas.py"),
            "--strict",
        ],
        allow_failure=True,
    )
    if preflight_code != 0:
        print("[quality-pipeline] Official RAGAS run skipped because preflight is not ready.")
        print("[quality-pipeline] Configure .env, then run: python scripts/run_ragas_ablation.py")
        return

    print("[quality-pipeline] Running official RAGAS ablation report...")
    ragas_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_ragas_ablation.py"),
        "--retriever",
        args.retriever,
        "--answer-mode",
        args.answer_mode,
        "--output",
        args.ragas_output,
        "--ragas-data-mode",
        args.ragas_data_mode,
        "--ragas-eval-mode",
        args.ragas_eval_mode,
    ]
    if args.ack_external_judge:
        ragas_command.append("--ack-external-judge")
    if args.limit:
        ragas_command.extend(["--limit", str(args.limit)])
    run(ragas_command)

    ragas_comparison = PROJECT_ROOT / args.ragas_output / "comparison" / "comparison.json"
    print("[quality-pipeline] Strict goal validation against official RAGAS report:")
    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "validate_quality_goal.py"),
            "--comparison",
            str(ragas_comparison),
            "--strict",
        ]
    )


if __name__ == "__main__":
    main()
