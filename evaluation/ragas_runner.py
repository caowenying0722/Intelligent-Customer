from __future__ import annotations

import math
import os
import re
import warnings
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from evaluation.dataset import EvaluationSample
from evaluation.hash_embeddings import HashNgramEmbeddings

RAGAS_DEFAULT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "factual_correctness(mode=f1)",
]

RAGAS_DATA_COLUMNS = {
    "user_input",
    "retrieved_contexts",
    "response",
    "reference",
    "question",
    "contexts",
    "answer",
    "ground_truth",
}

CONTEXT_REQUIRED_METRICS = {
    "faithfulness",
    "context_recall",
    "context_precision",
}

RAGAS_EVAL_MODES = {"per_sample", "batch"}


class RagasEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RagasMetricSpec:
    raw_name: str
    name: str
    params: dict[str, str]
    output_name: str


@dataclass(frozen=True)
class RagasEvaluationResult:
    metrics: list[dict[str, float]]
    errors: list[str]
    eval_mode: str


def parse_ragas_metric_spec(metric_name: str) -> RagasMetricSpec:
    cleaned = metric_name.strip()
    match = re.fullmatch(r"(?P<name>[a-zA-Z_][\w_]*)(?:\((?P<params>.*)\))?", cleaned)
    if not match:
        raise RagasEvaluationError(f"Invalid RAGAS metric name: {metric_name}")

    name = match.group("name")
    params: dict[str, str] = {}
    params_text = match.group("params")
    if params_text:
        for item in params_text.split(","):
            key, sep, value = item.partition("=")
            if not sep:
                raise RagasEvaluationError(f"Invalid RAGAS metric parameter: {item}")
            params[key.strip()] = value.strip()

    output_name = name
    if name == "factual_correctness" and params.get("mode"):
        output_name = f"factual_correctness(mode={params['mode']})"

    return RagasMetricSpec(
        raw_name=cleaned, name=name, params=params, output_name=output_name
    )


def _build_wrappers() -> tuple[Any, Any]:
    from model.factory import get_chat_model

    chat_model = get_chat_model()

    if os.environ.get("RAGAS_USE_PROJECT_EMBEDDINGS") == "1":
        from model.factory import get_embedding_model

        embeddings_model = get_embedding_model()
    else:
        embeddings_model = HashNgramEmbeddings()

    try:
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper

        return LangchainLLMWrapper(chat_model), LangchainEmbeddingsWrapper(
            embeddings_model
        )
    except (ImportError, TypeError):
        return chat_model, embeddings_model


def _metric_names_without_params(metric_names: list[str]) -> set[str]:
    return {parse_ragas_metric_spec(metric_name).name for metric_name in metric_names}


def should_include_contexts(metric_names: list[str], data_mode: str) -> bool:
    if data_mode == "full":
        return True
    if data_mode == "minimal":
        return bool(
            _metric_names_without_params(metric_names) & CONTEXT_REQUIRED_METRICS
        )
    raise RagasEvaluationError(f"Unsupported RAGAS data mode: {data_mode}")


def resolve_ragas_eval_mode(eval_mode: str | None = None) -> str:
    mode = (eval_mode or os.environ.get("RAGAS_EVAL_MODE", "per_sample")).strip()
    if mode not in RAGAS_EVAL_MODES:
        raise RagasEvaluationError(f"Unsupported RAGAS eval mode: {mode}")
    return mode


def _new_ragas_row(row: dict[str, Any], include_contexts: bool) -> dict[str, Any]:
    payload = {
        "user_input": row["question"],
        "response": row["answer"],
        "reference": row["reference_answer"],
    }
    if include_contexts:
        payload["retrieved_contexts"] = row["contexts"]
    return payload


def _legacy_ragas_row(row: dict[str, Any], include_contexts: bool) -> dict[str, Any]:
    payload = {
        "question": row["question"],
        "answer": row["answer"],
        "ground_truth": row["reference_answer"],
    }
    if include_contexts:
        payload["contexts"] = row["contexts"]
    return payload


def _new_ragas_dataset(rows: list[dict[str, Any]], include_contexts: bool) -> Any:
    from ragas import EvaluationDataset

    return EvaluationDataset.from_list(
        [_new_ragas_row(row, include_contexts) for row in rows]
    )


def _legacy_ragas_dataset(rows: list[dict[str, Any]], include_contexts: bool) -> Any:
    from datasets import Dataset

    return Dataset.from_list([_legacy_ragas_row(row, include_contexts) for row in rows])


def _metric_modules() -> list[Any]:
    modules = []
    with suppress(ImportError):
        import ragas.metrics.collections as collections_module

        modules.append(collections_module)
    import ragas.metrics as metrics_module

    modules.append(metrics_module)
    return modules


def _iter_metric_attrs(attr_names: list[str]):
    for module in _metric_modules():
        for attr_name in attr_names:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                metric_attr = getattr(module, attr_name, None)
            if metric_attr is not None:
                yield metric_attr


def _instantiate_metric(metric_attr: Any, params: dict[str, str]) -> Any:
    if not isinstance(metric_attr, type):
        return metric_attr
    return metric_attr(**params)


def _build_new_metrics(metric_names: list[str]) -> list[Any]:
    metric_aliases = {
        "faithfulness": ["Faithfulness"],
        "context_recall": ["LLMContextRecall", "ContextRecall"],
        "context_precision": ["LLMContextPrecisionWithReference", "ContextPrecision"],
        "answer_correctness": ["AnswerCorrectness", "FactualCorrectness"],
        "factual_correctness": ["FactualCorrectness"],
        "answer_relevancy": ["AnswerRelevancy", "ResponseRelevancy"],
        "response_relevancy": ["ResponseRelevancy", "AnswerRelevancy"],
    }

    selected_metrics = []
    missing_metrics = []
    for metric_name in metric_names:
        spec = parse_ragas_metric_spec(metric_name)
        attr_names = metric_aliases.get(spec.name, [spec.name])
        params = spec.params
        if spec.name == "factual_correctness" and "mode" not in params:
            params = {"mode": "f1"}

        metric = None
        instantiation_errors = []
        for metric_attr in _iter_metric_attrs(attr_names):
            try:
                metric = _instantiate_metric(metric_attr, params)
                break
            except TypeError as exc:
                instantiation_errors.append(str(exc))

        if metric is None:
            missing_metrics.append(metric_name)
            continue
        selected_metrics.append(metric)

    if not selected_metrics:
        raise RagasEvaluationError(
            f"No supported RAGAS metrics found: {', '.join(missing_metrics)}"
        )

    return selected_metrics


def _build_legacy_metrics(metric_names: list[str]) -> list[Any]:
    import ragas.metrics as metrics_module

    metric_aliases = {
        "faithfulness": "faithfulness",
        "context_recall": "context_recall",
        "context_precision": "context_precision",
        "answer_correctness": "answer_correctness",
        "factual_correctness": "answer_correctness",
        "answer_relevancy": "answer_relevancy",
        "response_relevancy": "answer_relevancy",
    }

    selected_metrics = []
    missing_metrics = []
    for metric_name in metric_names:
        spec = parse_ragas_metric_spec(metric_name)
        attr_name = metric_aliases.get(spec.name, spec.name)
        metric = getattr(metrics_module, attr_name, None)
        if metric is None:
            missing_metrics.append(metric_name)
            continue
        selected_metrics.append(metric)

    if not selected_metrics:
        raise RagasEvaluationError(
            f"No supported RAGAS metrics found: {', '.join(missing_metrics)}"
        )

    return selected_metrics


def _records_from_result(result: Any) -> list[dict[str, Any]]:
    if hasattr(result, "to_pandas"):
        return result.to_pandas().to_dict(orient="records")

    if hasattr(result, "scores"):
        return list(result.scores)

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        return [result]

    return []


def _run_ragas_evaluate(
    evaluate: Any,
    dataset: Any,
    metrics: list[Any],
    llm: Any,
    embeddings: Any,
    run_config: Any,
) -> list[dict[str, Any]]:
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        batch_size=1,
    )
    return _records_from_result(result)


def _evaluate_ragas_records(
    evaluate: Any,
    rows: list[dict[str, Any]],
    dataset_builder: Any,
    include_contexts: bool,
    metrics: list[Any],
    llm: Any,
    embeddings: Any,
    run_config: Any,
    eval_mode: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if eval_mode == "batch":
        return (
            _run_ragas_evaluate(
                evaluate=evaluate,
                dataset=dataset_builder(rows, include_contexts),
                metrics=metrics,
                llm=llm,
                embeddings=embeddings,
                run_config=run_config,
            ),
            [],
        )

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        try:
            sample_records = _run_ragas_evaluate(
                evaluate=evaluate,
                dataset=dataset_builder([row], include_contexts),
                metrics=metrics,
                llm=llm,
                embeddings=embeddings,
                run_config=run_config,
            )
            records.append(sample_records[0] if sample_records else {})
        except Exception as exc:  # noqa: BLE001 - isolate each external judge sample.
            sample_id = row.get("id", index)
            errors.append(f"{sample_id}: {type(exc).__name__}: {exc}")
            records.append({})
    return records, errors


def _numeric_metric_values(record: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for key, value in record.items():
        if key in RAGAS_DATA_COLUMNS:
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            metrics[key] = round(float(value), 6)
    return metrics


def _normalize_requested_metric_names(
    metrics: dict[str, float],
    metric_specs: list[RagasMetricSpec],
) -> dict[str, float]:
    normalized = dict(metrics)
    aliases = {
        "answer_relevancy": ["answer_relevancy", "response_relevancy"],
        "response_relevancy": ["response_relevancy", "answer_relevancy"],
        "factual_correctness": ["factual_correctness", "answer_correctness"],
        "factual_correctness(mode=f1)": [
            "factual_correctness(mode=f1)",
            "factual_correctness",
            "answer_correctness",
        ],
        "answer_correctness": ["answer_correctness", "factual_correctness"],
    }
    for spec in metric_specs:
        if spec.output_name in normalized:
            continue
        for alias in aliases.get(spec.output_name, [spec.output_name]):
            if alias in normalized:
                normalized[spec.output_name] = normalized[alias]
                break
    return normalized


def evaluate_with_ragas(
    samples: list[EvaluationSample],
    rows: list[dict[str, Any]],
    metric_names: list[str] | None = None,
    data_mode: str | None = None,
    eval_mode: str | None = None,
) -> RagasEvaluationResult:
    metric_names = metric_names or RAGAS_DEFAULT_METRICS
    data_mode = data_mode or os.environ.get("RAGAS_DATA_MODE", "minimal")
    eval_mode = resolve_ragas_eval_mode(eval_mode)
    include_contexts = should_include_contexts(metric_names, data_mode)
    if os.environ.get("RAGAS_ACK_EXTERNAL_JUDGE") != "1":
        payload_description = "questions, answers, and references"
        if include_contexts:
            payload_description += ", plus retrieved contexts"
        raise RagasEvaluationError(
            f"Official RAGAS evaluation sends {payload_description} "
            "to the configured external judge LLM. Set RAGAS_ACK_EXTERNAL_JUDGE=1 or pass "
            "`--ack-external-judge` after confirming this data egress is acceptable."
        )

    try:
        from ragas import evaluate
    except ImportError as exc:
        raise RagasEvaluationError(
            "RAGAS is not installed. Run `pip install ragas datasets`."
        ) from exc

    metric_specs = [parse_ragas_metric_spec(name) for name in metric_names]
    llm, embeddings = _build_wrappers()
    max_workers = int(os.environ.get("RAGAS_MAX_WORKERS", "1"))
    timeout = int(os.environ.get("RAGAS_TIMEOUT", "300"))
    max_retries = int(os.environ.get("RAGAS_MAX_RETRIES", "2"))

    try:
        _new_ragas_dataset(rows[:1], include_contexts)
        dataset_builder = _new_ragas_dataset
        metrics = _build_new_metrics(metric_names)
    except (ImportError, AttributeError, TypeError, ValueError):
        dataset_builder = _legacy_ragas_dataset
        metrics = _build_legacy_metrics(metric_names)

    try:
        from ragas.run_config import RunConfig

        run_config = RunConfig(
            timeout=timeout, max_retries=max_retries, max_workers=max_workers
        )
    except (ImportError, TypeError, ValueError):
        run_config = None

    ragas_records, ragas_errors = _evaluate_ragas_records(
        evaluate=evaluate,
        rows=rows,
        dataset_builder=dataset_builder,
        include_contexts=include_contexts,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        eval_mode=eval_mode,
    )

    per_sample_metrics = []
    for index, _sample in enumerate(samples):
        record = ragas_records[index] if index < len(ragas_records) else {}
        per_sample_metrics.append(
            _normalize_requested_metric_names(
                _numeric_metric_values(record), metric_specs
            )
        )

    return RagasEvaluationResult(
        metrics=per_sample_metrics, errors=ragas_errors, eval_mode=eval_mode
    )
