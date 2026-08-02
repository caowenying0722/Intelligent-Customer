"""Bounded synthetic multi-tenant model simulation.

The default mode is dry-run. ``--live`` is an explicit opt-in for the configured
Anthropic-compatible provider and never sends real customer data: every prompt is
generated from deterministic ``.test`` tenant fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model.anthropic_compatible import AnthropicCompatibleChatModel
from model.contracts import ModelRequest
from model.factory import build_chat_gateway
from model.gateway import CacheBackend, ModelGateway
from model.runtime_config import ModelRuntimeConfig
from rag.tokenization import cjk_bm25_tokenizer
from utils.settings import get_settings


@dataclass(frozen=True)
class SimulationConfig:
    tenants: int = 3
    documents_per_tenant: int = 8
    queries_per_tenant: int = 10
    max_calls: int = 30
    max_workers: int = 4
    timeout_seconds: float = 60.0
    max_retries: int = 1
    max_output_tokens: int = 256
    max_context_chars: int = 8_000
    seed: int = 20260802

    def __post_init__(self) -> None:
        if not 1 <= self.tenants <= 100:
            raise ValueError("tenants must be between 1 and 100")
        if not 1 <= self.documents_per_tenant <= 1_000:
            raise ValueError("documents_per_tenant must be between 1 and 1000")
        if not 1 <= self.queries_per_tenant <= 1_000:
            raise ValueError("queries_per_tenant must be between 1 and 1000")
        if not 1 <= self.max_calls <= 10_000:
            raise ValueError("max_calls must be between 1 and 10000")
        if not 1 <= self.max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        if not 0 <= self.max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        if self.timeout_seconds <= 0 or self.max_output_tokens < 1:
            raise ValueError("timeout and output token limits must be positive")
        if not 500 <= self.max_context_chars <= 50_000:
            raise ValueError("max_context_chars must be between 500 and 50000")


@dataclass(frozen=True)
class SyntheticDocument:
    tenant_id: str
    document_id: str
    content: str
    answer_terms: tuple[str, ...]


@dataclass(frozen=True)
class SyntheticQuery:
    tenant_id: str
    query_id: str
    question: str
    expected_terms: tuple[str, ...]


class _NoCache(CacheBackend):
    """Disable response reuse so live runs measure actual provider calls."""

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def key(
        *, tenant_id: str, model: str, prompt: str, prompt_version: str = "v1"
    ) -> str:
        del tenant_id, model, prompt, prompt_version
        return "disabled"

    def get(self, _key: str) -> Any | None:
        return None

    def set(self, _key: str, _value: Any) -> object:
        return None

    def stats(self) -> dict[str, int]:
        return {"entries": 0, "hits": 0, "misses": self.calls}


class _CallBudget:
    def __init__(self, *, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0
        self._lock = threading.Lock()

    def reserve(self) -> bool:
        with self._lock:
            if self.used >= self.max_calls:
                return False
            self.used += 1
            return True


def build_synthetic_fixtures(
    config: SimulationConfig,
) -> tuple[list[SyntheticDocument], list[SyntheticQuery]]:
    rng = random.Random(config.seed)
    documents: list[SyntheticDocument] = []
    queries: list[SyntheticQuery] = []
    templates = (
        ("returns", "What is the return period?", "30 days"),
        ("support", "What is the support email?", "support-{number}@example.test"),
        ("shipping", "How long does standard shipping take?", "3 business days"),
        ("warranty", "How long is the warranty?", "24 months"),
        ("maintenance", "How often should the filter be changed?", "every 90 days"),
    )
    for tenant_number in range(1, config.tenants + 1):
        tenant_id = f"tenant-{tenant_number:03d}"
        marker = f"SYNTHETIC-{tenant_number:03d}"
        for document_number in range(1, config.documents_per_tenant + 1):
            topic, question, answer_template = templates[
                (document_number - 1) % len(templates)
            ]
            answer = answer_template.format(number=f"{tenant_number:03d}")
            content = (
                f"Tenant {tenant_id} uses fixture marker {marker}. "
                f"Knowledge topic: {topic}. Question cue: {question} "
                f"Policy answer: {answer}. "
                f"Document revision {document_number}; seed noise {rng.randrange(10_000)}."
            )
            documents.append(
                SyntheticDocument(
                    tenant_id=tenant_id,
                    document_id=f"{tenant_id}-doc-{document_number:04d}",
                    content=content,
                    answer_terms=(answer,),
                )
            )
        for query_number in range(1, config.queries_per_tenant + 1):
            topic, question, answer_template = templates[
                (query_number - 1) % len(templates)
            ]
            answer = answer_template.format(number=f"{tenant_number:03d}")
            queries.append(
                SyntheticQuery(
                    tenant_id=tenant_id,
                    query_id=f"{tenant_id}-query-{query_number:04d}",
                    question=f"For {tenant_id}, {question}",
                    expected_terms=(answer,),
                )
            )
    return documents, queries


def retrieve(
    documents: list[SyntheticDocument], query: SyntheticQuery, *, limit: int = 3
) -> list[SyntheticDocument]:
    query_tokens = set(cjk_bm25_tokenizer(query.question))
    scoped = [doc for doc in documents if doc.tenant_id == query.tenant_id]
    ranked = sorted(
        scoped,
        key=lambda doc: (
            len(query_tokens & set(cjk_bm25_tokenizer(doc.content))),
            doc.document_id,
        ),
        reverse=True,
    )
    return ranked[:limit]


def build_prompt(
    query: SyntheticQuery, context: list[SyntheticDocument], *, max_chars: int
) -> str:
    context_text = "\n".join(f"[{doc.document_id}] {doc.content}" for doc in context)
    context_text = context_text[:max_chars]
    return (
        "You are a customer-support evaluator. Answer only from the supplied context. "
        "Do not invent tenant data. Return one concise sentence.\n"
        f"Requested tenant: {query.tenant_id}\n"
        f"Question: {query.question}\n"
        f"Context:\n{context_text}"
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 3)


def _build_live_gateway(config: SimulationConfig) -> tuple[ModelGateway, str, str]:
    settings = get_settings()
    if settings.resolved_model_provider != "anthropic":
        raise RuntimeError(
            "tenant simulation requires the configured Anthropic provider"
        )
    api_key = settings.anthropic_api_key_value
    model_name = settings.anthropic_model or settings.anthropic_default_sonnet_model
    if not api_key or not model_name:
        raise RuntimeError("Anthropic model credentials/configuration are unavailable")
    model = AnthropicCompatibleChatModel(
        model_name=model_name,
        base_url=settings.anthropic_base_url,
        api_key=api_key,
        max_tokens=config.max_output_tokens,
        timeout=config.timeout_seconds,
        verify=ModelRuntimeConfig.from_settings(settings).requests_verify,
    )
    gateway = build_chat_gateway(
        model=cast_model(model),
        provider="anthropic",
        runtime=ModelRuntimeConfig(
            request_timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        ),
        settings=settings,
        max_concurrency=config.max_workers,
        cache=_NoCache(),
    )
    return gateway, model_name, settings.anthropic_base_url


def cast_model(model: AnthropicCompatibleChatModel) -> BaseChatModel:
    return model


def run_simulation(
    config: SimulationConfig,
    *,
    live: bool,
    include_responses: bool = False,
) -> dict[str, Any]:
    documents, queries = build_synthetic_fixtures(config)
    started = time.monotonic()
    budget = _CallBudget(max_calls=config.max_calls)
    gateway: ModelGateway | None = None
    model_name = "dry-run"
    base_url = "not-called"
    if live:
        gateway, model_name, base_url = _build_live_gateway(config)

    rows: list[dict[str, Any]] = []

    def execute(query: SyntheticQuery) -> dict[str, Any]:
        retrieved = retrieve(documents, query)
        prompt = build_prompt(query, retrieved, max_chars=config.max_context_chars)
        base_row: dict[str, Any] = {
            "query_id": query.query_id,
            "tenant_id": query.tenant_id,
            "retrieved_document_ids": [doc.document_id for doc in retrieved],
            "prompt_sha256": _hash_text(prompt),
        }
        if not live:
            return {**base_row, "status": "dry_run", "passed": None, "leakage": False}
        if gateway is None or not budget.reserve():
            return {
                **base_row,
                "status": "budget_exhausted",
                "passed": None,
                "leakage": False,
            }
        request = ModelRequest(
            tenant_id=query.tenant_id,
            provider="anthropic",
            model=model_name,
            prompt=prompt,
            request_id=str(uuid4()),
            prompt_version="tenant-simulation-v1",
        )
        call_started = time.monotonic()
        try:
            response = gateway.invoke_contract(request)
            output = response.output
            other_markers = [
                f"SYNTHETIC-{number:03d}"
                for number in range(1, config.tenants + 1)
                if f"tenant-{number:03d}" != query.tenant_id
            ]
            other_tenants = [
                f"tenant-{number:03d}"
                for number in range(1, config.tenants + 1)
                if f"tenant-{number:03d}" != query.tenant_id
            ]
            lowered_output = output.casefold()
            leakage = any(
                marker.casefold() in lowered_output for marker in other_markers
            ) or any(tenant.casefold() in lowered_output for tenant in other_tenants)
            output_tokens = set(cjk_bm25_tokenizer(output))
            passed = all(
                set(cjk_bm25_tokenizer(term)) <= output_tokens
                or re.sub(r"[*_`]", "", term.casefold())
                in re.sub(r"[*_`]", "", lowered_output)
                for term in query.expected_terms
            )
            result = {
                **base_row,
                "status": "completed",
                "passed": passed,
                "leakage": leakage,
                "latency_ms": round((time.monotonic() - call_started) * 1000, 3),
                "input_chars": len(prompt),
                "output_chars": len(output),
            }
            if include_responses:
                result["response"] = output
            return result
        except Exception as exc:  # noqa: BLE001 - isolate one tenant query.
            return {
                **base_row,
                "status": "error",
                "error_type": type(exc).__name__,
                "latency_ms": round((time.monotonic() - call_started) * 1000, 3),
            }

    with ThreadPoolExecutor(
        max_workers=config.max_workers, thread_name_prefix="tenant-sim"
    ) as executor:
        futures: list[Future[dict[str, Any]]] = [
            executor.submit(execute, query) for query in queries
        ]
        for future in as_completed(futures):
            rows.append(future.result())

    completed = [row for row in rows if row["status"] == "completed"]
    latency_values = [
        float(row["latency_ms"]) for row in completed if "latency_ms" in row
    ]
    report: dict[str, Any] = {
        "schema_version": "tenant-simulation-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live": live,
        "provider": "anthropic" if live else None,
        "model": model_name,
        "base_url": base_url if live else None,
        "config": {
            "tenants": config.tenants,
            "documents_per_tenant": config.documents_per_tenant,
            "queries_per_tenant": config.queries_per_tenant,
            "max_calls": config.max_calls,
            "max_workers": config.max_workers,
            "timeout_seconds": config.timeout_seconds,
            "max_retries": config.max_retries,
            "seed": config.seed,
        },
        "summary": {
            "fixture_documents": len(documents),
            "fixture_queries": len(queries),
            "rows": len(rows),
            "completed": len(completed),
            "passed": sum(1 for row in completed if row.get("passed")),
            "leakage": sum(1 for row in completed if row.get("leakage")),
            "errors": sum(1 for row in rows if row["status"] == "error"),
            "budget_exhausted": sum(
                1 for row in rows if row["status"] == "budget_exhausted"
            ),
            "provider_calls": budget.used,
            "p50_latency_ms": _percentile(latency_values, 0.50),
            "p95_latency_ms": _percentile(latency_values, 0.95),
            "cost_measured": False,
            "cost_note": "Provider usage metadata is not exposed by the compatible adapter; cost must be reconciled from provider billing.",
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        },
        "rows": rows,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="call the configured Anthropic-compatible provider",
    )
    parser.add_argument("--tenants", type=int, default=3)
    parser.add_argument("--documents-per-tenant", type=int, default=8)
    parser.add_argument("--queries-per-tenant", type=int, default=10)
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--max-context-chars", type=int, default=8_000)
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument(
        "--output", type=Path, default=Path("output/tenant-simulation/report.json")
    )
    parser.add_argument(
        "--include-responses",
        action="store_true",
        help="include synthetic model responses in the local report",
    )
    args = parser.parse_args()
    config = SimulationConfig(
        tenants=args.tenants,
        documents_per_tenant=args.documents_per_tenant,
        queries_per_tenant=args.queries_per_tenant,
        max_calls=args.max_calls,
        max_workers=args.max_workers,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        max_output_tokens=args.max_output_tokens,
        max_context_chars=args.max_context_chars,
        seed=args.seed,
    )
    report = run_simulation(
        config, live=args.live, include_responses=args.include_responses
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
