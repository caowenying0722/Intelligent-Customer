from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml
from langchain_core.documents import Document

from evaluation.dataset import (
    EvaluationSample,
    file_sha256,
    load_jsonl_dataset,
    resolve_project_path,
)
from evaluation.extractive_answer import build_extractive_answer
from evaluation.local_metrics import (
    calculate_local_metrics,
    source_name,
    summarize_metric_rows,
)
from evaluation.ragas_runner import (
    RAGAS_DEFAULT_METRICS,
    RagasEvaluationError,
    evaluate_with_ragas,
    resolve_ragas_eval_mode,
)
from evaluation.regression_report import (
    build_retrieval_regression_summary,
    repository_snapshot,
)
from utils.config_handler import chroma_conf, rag_conf
from utils.judge_llm import judge_llm_status

DEFAULT_CONFIG: dict[str, Any] = {
    "dataset_path": "data/evaluation/rag_eval_dataset.jsonl",
    "output_dir": "output/evaluation",
    "generate_answers": True,
    "answer_mode": "llm",
    "retriever_mode": "hybrid",
    "retrieval_regression_path": "data/evaluation/retrieval_regression_v1.json",
    "artifact_profile": "redacted",
    "ragas": {
        "enabled": False,
        "metrics": RAGAS_DEFAULT_METRICS,
    },
}


class EvaluationRagService(Protocol):
    def retriever_docs(self, query: str) -> list[Document]: ...

    def summarize_with_docs(self, query: str, context_docs: list[Document]) -> str: ...


def classify_evaluation_error(error: BaseException) -> str:
    """Map runtime failures to bounded, non-sensitive evaluation categories."""

    error_name = type(error).__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return "timeout"
    if isinstance(error, (ConnectionError, OSError)) or any(
        marker in error_name for marker in ("connection", "network", "transport")
    ):
        return "upstream"
    if isinstance(error, (TypeError, ValueError, KeyError, AttributeError)):
        return "invalid_output"
    return "unknown"


def load_evaluation_config(config_path: str | Path | None = None) -> dict[str, Any]:
    if not config_path:
        config_path = "config/evaluation.yml"

    path = resolve_project_path(config_path)
    if not path.exists():
        return DEFAULT_CONFIG.copy()

    with path.open("r", encoding="utf-8") as f:
        loaded_config = yaml.safe_load(f) or {}

    config = DEFAULT_CONFIG.copy()
    config.update(loaded_config)
    config["ragas"] = DEFAULT_CONFIG["ragas"].copy() | dict(
        loaded_config.get("ragas", {})
    )
    return config


def document_payload(doc, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "source": source_name(doc),
        "metadata": doc.metadata,
        "content": doc.page_content,
    }


def evaluate_samples(
    samples: list[EvaluationSample],
    generate_answers: bool = True,
    answer_mode: str = "llm",
    run_ragas: bool = False,
    ragas_metrics: list[str] | None = None,
    ragas_data_mode: str | None = None,
    ragas_eval_mode: str | None = None,
    retriever_mode: str = "hybrid",
) -> tuple[list[dict[str, Any]], str | None]:
    rag_service: EvaluationRagService
    if retriever_mode == "bm25":
        from evaluation.bm25_rag_service import BM25RagEvaluationService

        rag_service = BM25RagEvaluationService()
    else:
        from rag.rag_service import RagSummarizeService

        rag_service = RagSummarizeService(print_prompts=False)
    rows: list[dict[str, Any]] = []

    for index, sample in enumerate(samples, start=1):
        print(f"[RAG评测] {index}/{len(samples)} {sample.id}: {sample.question}")
        started = time.perf_counter()
        docs: list[Document] = []
        answer = ""
        error_type: str | None = None
        try:
            docs = rag_service.retriever_docs(sample.question)
            if answer_mode == "extractive":
                answer = build_extractive_answer(sample.question, docs)
            elif generate_answers:
                answer = rag_service.summarize_with_docs(sample.question, docs)
            else:
                answer = sample.reference_answer
            metrics = calculate_local_metrics(sample, answer, docs)
        except Exception as exc:  # noqa: BLE001 - isolate one sample by category.
            error_type = classify_evaluation_error(exc)
            metrics = {}
        contexts = [doc.page_content for doc in docs]

        rows.append(
            {
                "id": sample.id,
                "question": sample.question,
                "answer": answer,
                "reference_answer": sample.reference_answer,
                "contexts": contexts,
                "retrieved_sources": [source_name(doc) for doc in docs],
                "retrieved_documents": [
                    document_payload(doc, rank)
                    for rank, doc in enumerate(docs, start=1)
                ],
                "metrics": metrics,
                "metadata": sample.metadata,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "error_type": error_type,
            }
        )

    ragas_error = None
    if run_ragas:
        try:
            ragas_result = evaluate_with_ragas(
                samples,
                rows,
                ragas_metrics,
                data_mode=ragas_data_mode,
                eval_mode=ragas_eval_mode,
            )
            finite_ragas_values = 0
            for row, ragas_metrics_for_sample in zip(rows, ragas_result.metrics):
                row["ragas_metrics"] = ragas_metrics_for_sample
                finite_ragas_values += sum(
                    1
                    for value in ragas_metrics_for_sample.values()
                    if isinstance(value, (int, float)) and math.isfinite(float(value))
                )
            if ragas_result.errors:
                ragas_error = (
                    f"RAGAS partial failures in {ragas_result.eval_mode} mode: "
                    + " | ".join(ragas_result.errors[:3])
                )
                if len(ragas_result.errors) > 3:
                    ragas_error += f" | ... {len(ragas_result.errors) - 3} more"
            if finite_ragas_values == 0:
                ragas_error = (
                    "RAGAS returned no finite metric values. Check judge LLM API key, "
                    "base URL, network access, and metric compatibility."
                )
        except RagasEvaluationError as exc:
            ragas_error = str(exc)
            for row in rows:
                row["ragas_metrics"] = {}

    return rows, ragas_error


def _flatten_metric_names(rows: list[dict[str, Any]]) -> list[str]:
    metric_names: set[str] = set()
    for row in rows:
        metric_names.update(row.get("metrics", {}).keys())
        metric_names.update(row.get("ragas_metrics", {}).keys())
    return sorted(metric_names)


def save_evaluation_report(
    rows: list[dict[str, Any]],
    output_dir: str | Path,
    dataset_path: str | Path,
    generate_answers: bool,
    answer_mode: str,
    retriever_mode: str,
    ragas_enabled: bool,
    ragas_error: str | None = None,
    rag_config_snapshot: dict[str, Any] | None = None,
    ragas_metric_names: list[str] | None = None,
    ragas_data_mode: str | None = None,
    ragas_eval_mode: str | None = None,
    judge_llm_snapshot: dict[str, Any] | None = None,
    retrieval_regression_summary: dict[str, Any] | None = None,
    artifact_profile: str = "redacted",
) -> Path:
    if artifact_profile not in {"redacted", "full"}:
        raise ValueError("artifact_profile must be 'redacted' or 'full'")
    generated_at = datetime.now(tz=timezone.utc).astimezone()
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    report_dir = resolve_project_path(output_dir) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    metric_summary = summarize_metric_rows(rows)
    error_types = Counter(row["error_type"] for row in rows if row.get("error_type"))
    regression_summary = dict(retrieval_regression_summary or {})
    dataset_display_path = str(dataset_path)
    if artifact_profile == "full":
        dataset_display_path = str(resolve_project_path(dataset_path))
    if "dataset_path" in regression_summary:
        regression_summary["dataset_path"] = (
            str(regression_summary["dataset_path"])
            if artifact_profile == "full"
            else str(dataset_path)
        )
    summary = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "repository": repository_snapshot(),
        "dataset_path": dataset_display_path,
        "dataset_sha256": file_sha256(dataset_path),
        "sample_count": len(rows),
        "generate_answers": generate_answers,
        "answer_mode": answer_mode,
        "retriever_mode": retriever_mode,
        "ragas_enabled": ragas_enabled,
        "ragas_error": ragas_error,
        "ragas_metric_names": ragas_metric_names or [],
        "ragas_data_mode": ragas_data_mode,
        "ragas_eval_mode": ragas_eval_mode,
        "artifact_profile": artifact_profile,
        "judge_llm": judge_llm_snapshot or {},
        "rag_config": rag_config_snapshot or {},
        "metrics": metric_summary,
        "error_count": sum(error_types.values()),
        "error_types": dict(sorted(error_types.items())),
        "retrieval_regression": regression_summary,
    }

    with (report_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    with (report_dir / "samples.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            if artifact_profile == "redacted":
                row = {
                    "id": row["id"],
                    "metrics": row.get("metrics", {}),
                    "ragas_metrics": row.get("ragas_metrics", {}),
                    "duration_ms": row.get("duration_ms"),
                    "error_type": row.get("error_type"),
                }
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    metric_names = _flatten_metric_names(rows)
    csv_columns = ["id", "duration_ms", "error_type", *metric_names]
    if artifact_profile == "full":
        csv_columns[1:1] = [
            "question",
            "answer",
            "reference_answer",
            "retrieved_sources",
        ]
    with (report_dir / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns)
        writer.writeheader()
        for row in rows:
            csv_row = {
                "id": row["id"],
                "duration_ms": row.get("duration_ms", ""),
                "error_type": row.get("error_type", ""),
            }
            if artifact_profile == "full":
                csv_row.update(
                    {
                        "question": row["question"],
                        "answer": row["answer"],
                        "reference_answer": row["reference_answer"],
                        "retrieved_sources": " | ".join(row["retrieved_sources"]),
                    }
                )
            combined_metrics = {}
            combined_metrics.update(row.get("metrics", {}))
            combined_metrics.update(row.get("ragas_metrics", {}))
            for metric_name in metric_names:
                csv_row[metric_name] = combined_metrics.get(metric_name, "")
            writer.writerow(csv_row)

    return report_dir


def run_evaluation(
    config_path: str | Path | None = None,
    dataset_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    run_ragas: bool | None = None,
    generate_answers: bool | None = None,
    answer_mode: str | None = None,
    retriever_mode: str | None = None,
    ragas_metrics: list[str] | None = None,
    ragas_data_mode: str | None = None,
    ragas_eval_mode: str | None = None,
    rag_config_overrides: dict[str, Any] | None = None,
    artifact_profile: str | None = None,
) -> Path:
    config = load_evaluation_config(config_path)
    if rag_config_overrides:
        chroma_conf.update(rag_config_overrides)

    dataset_path = dataset_path or config["dataset_path"]
    output_dir = output_dir or config["output_dir"]

    samples = load_jsonl_dataset(dataset_path)
    if limit:
        samples = samples[:limit]

    ragas_config = config.get("ragas", {})
    ragas_enabled = bool(
        ragas_config.get("enabled", False) if run_ragas is None else run_ragas
    )
    effective_ragas_data_mode = ragas_data_mode or str(
        ragas_config.get("data_mode", "minimal")
    )
    effective_ragas_eval_mode = resolve_ragas_eval_mode(
        ragas_eval_mode or str(ragas_config.get("eval_mode", "per_sample"))
    )
    generate_answers_enabled = bool(
        config.get("generate_answers", True)
        if generate_answers is None
        else generate_answers
    )
    answer_mode = answer_mode or str(config.get("answer_mode", "llm"))
    if not generate_answers_enabled and answer_mode == "llm":
        answer_mode = "reference"
    retriever_mode = retriever_mode or str(config.get("retriever_mode", "hybrid"))
    artifact_profile = artifact_profile or str(
        config.get("artifact_profile", "redacted")
    )
    rows, ragas_error = evaluate_samples(
        samples=samples,
        generate_answers=generate_answers_enabled,
        answer_mode=answer_mode,
        run_ragas=ragas_enabled,
        ragas_metrics=ragas_metrics
        or list(ragas_config.get("metrics", RAGAS_DEFAULT_METRICS)),
        ragas_data_mode=effective_ragas_data_mode,
        ragas_eval_mode=effective_ragas_eval_mode,
        retriever_mode=retriever_mode,
    )

    report_dir = save_evaluation_report(
        rows=rows,
        output_dir=output_dir,
        dataset_path=dataset_path,
        generate_answers=generate_answers_enabled,
        answer_mode=answer_mode,
        retriever_mode=retriever_mode,
        ragas_enabled=ragas_enabled,
        ragas_error=ragas_error,
        ragas_metric_names=ragas_metrics
        or list(ragas_config.get("metrics", RAGAS_DEFAULT_METRICS)),
        ragas_data_mode=effective_ragas_data_mode,
        ragas_eval_mode=effective_ragas_eval_mode,
        judge_llm_snapshot=judge_llm_status(rag_conf),
        rag_config_snapshot={
            "retrieval_type": chroma_conf.get("retrieval_type"),
            "k": chroma_conf.get("k"),
            "candidate_k": chroma_conf.get("candidate_k"),
            "rerank_enabled": chroma_conf.get("rerank_enabled"),
            "rerank_top_k": chroma_conf.get("rerank_top_k"),
            "low_confidence_threshold": chroma_conf.get("low_confidence_threshold"),
        },
        retrieval_regression_summary=build_retrieval_regression_summary(
            rows,
            config.get(
                "retrieval_regression_path",
                "data/evaluation/retrieval_regression_v1.json",
            ),
        ),
        artifact_profile=artifact_profile,
    )
    print(f"[RAG评测] 报告已生成: {report_dir}")
    return report_dir
