"""Safe, bounded Prometheus rendering for aggregate gateway metrics."""

from __future__ import annotations

from collections.abc import Mapping
from hmac import compare_digest
from math import isfinite
from threading import Lock
from time import perf_counter
from typing import Any, cast

MAX_PROVIDER_SERIES = 32
HTTP_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
WORKER_DURATION_BUCKETS = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    300.0,
)


def metrics_token_matches(expected: str | None, supplied: str | None) -> bool:
    """Check an optional metrics token without leaking timing information."""
    if expected is None:
        return True
    return supplied is not None and compare_digest(expected, supplied)


class HttpMetrics:
    """Bounded process-local HTTP counters; no request or identity data is retained."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests = 0
        self._errors = 0
        self._active = 0
        self._duration_sum = 0.0
        self._duration_count = 0
        self._duration_buckets = {bucket: 0 for bucket in HTTP_DURATION_BUCKETS}
        self._responses = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        self._sse_disconnects = 0

    def begin(self) -> float:
        with self._lock:
            self._active += 1
        return perf_counter()

    def end(
        self,
        started: float,
        *,
        status_code: int,
        path: str,
        client_disconnected: bool = False,
    ) -> None:
        duration = max(0.0, perf_counter() - started)
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._requests += 1
            self._errors += int(status_code >= 400)
            self._active = max(0, self._active - 1)
            self._duration_sum += duration
            self._duration_count += 1
            self._responses[status_class] = self._responses.get(status_class, 0) + 1
            for bucket in HTTP_DURATION_BUCKETS:
                if duration <= bucket:
                    self._duration_buckets[bucket] += 1
            if client_disconnected and path.endswith("/stream"):
                self._sse_disconnects += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "requests": self._requests,
                "errors": self._errors,
                "active": self._active,
                "duration_sum_seconds": self._duration_sum,
                "duration_count": self._duration_count,
                "duration_buckets": dict(self._duration_buckets),
                "responses": dict(self._responses),
                "sse_disconnects": self._sse_disconnects,
            }


class WorkerMetrics:
    """Bounded process-local ingestion worker metrics without identity labels."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._queue_depth = 0
        self._active = 0
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._retries = 0
        self._queue_wait_sum = 0.0
        self._queue_wait_count = 0
        self._queue_wait_buckets = {bucket: 0 for bucket in WORKER_DURATION_BUCKETS}
        self._processing_sum = 0.0
        self._processing_count = 0
        self._processing_buckets = {bucket: 0 for bucket in WORKER_DURATION_BUCKETS}

    def submitted(self) -> None:
        with self._lock:
            self._queue_depth += 1
            self._submitted += 1

    def submission_failed(self) -> None:
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)

    def started(self, queue_wait_seconds: float) -> None:
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)
            self._active += 1
            self._record_duration(
                queue_wait_seconds,
                target_sum="queue_wait_sum",
                target_count="queue_wait_count",
                target_buckets=self._queue_wait_buckets,
            )

    def retry(self) -> None:
        with self._lock:
            self._retries += 1

    def finished(self, status: str, processing_seconds: float) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            if status == "completed":
                self._completed += 1
            elif status == "cancelled":
                self._cancelled += 1
            else:
                self._failed += 1
            self._record_duration(
                processing_seconds,
                target_sum="processing_sum",
                target_count="processing_count",
                target_buckets=self._processing_buckets,
            )

    def cancelled_queued(self) -> None:
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)
            self._cancelled += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "queue_depth": self._queue_depth,
                "active": self._active,
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "cancelled": self._cancelled,
                "retries": self._retries,
                "queue_wait_sum_seconds": self._queue_wait_sum,
                "queue_wait_count": self._queue_wait_count,
                "queue_wait_buckets": dict(self._queue_wait_buckets),
                "processing_sum_seconds": self._processing_sum,
                "processing_count": self._processing_count,
                "processing_buckets": dict(self._processing_buckets),
            }

    def _record_duration(
        self,
        duration: float,
        *,
        target_sum: str,
        target_count: str,
        target_buckets: dict[float, int],
    ) -> None:
        bounded = max(0.0, duration)
        setattr(self, f"_{target_sum}", getattr(self, f"_{target_sum}") + bounded)
        setattr(
            self,
            f"_{target_count}",
            getattr(self, f"_{target_count}") + 1,
        )
        for bucket in WORKER_DURATION_BUCKETS:
            if bounded <= bucket:
                target_buckets[bucket] += 1


def empty_worker_snapshot() -> dict[str, object]:
    """Return a stable zero snapshot when no ingestion worker is configured."""
    return WorkerMetrics().snapshot()


def empty_gateway_snapshot() -> dict[str, object]:
    """Return the stable zero snapshot used when no model gateway is configured."""
    return {
        "calls": 0,
        "failures": 0,
        "provider_calls": {},
        "provider_failures": {},
    }


def _metric_number(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        number = float(value)
        if isfinite(number):
            return str(value)
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return "0"
        if isfinite(number):
            return value
    return "0"


def _label_value(value: object) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _line(name: str, value: object) -> str:
    return f"{name} {_metric_number(value)}"


def _provider_lines(name: str, values: object) -> list[str]:
    """Render bounded provider series; provider names are configuration, not input."""
    items = sorted(_mapping(values).items())[:MAX_PROVIDER_SERIES]
    return [
        f'{name}{{provider="{_label_value(provider)}"}} {_metric_number(count)}'
        for provider, count in items
    ]


def render_prometheus(
    gateway_snapshot: Mapping[str, object],
    health_snapshot: Mapping[str, object],
    http_snapshot: Mapping[str, object] | None = None,
    worker_snapshot: Mapping[str, object] | None = None,
) -> str:
    """Render aggregate metrics without tenant, user, request, or prompt labels."""
    lines = [
        "# HELP model_gateway_calls_total Total model gateway calls.",
        "# TYPE model_gateway_calls_total counter",
        _line("model_gateway_calls_total", gateway_snapshot.get("calls", 0)),
        "# HELP model_gateway_failures_total Total model gateway failures.",
        "# TYPE model_gateway_failures_total counter",
        _line("model_gateway_failures_total", gateway_snapshot.get("failures", 0)),
        "# HELP model_gateway_provider_calls_total Calls grouped by configured provider.",
        "# TYPE model_gateway_provider_calls_total counter",
        *_provider_lines(
            "model_gateway_provider_calls_total",
            gateway_snapshot.get("provider_calls", {}),
        ),
        "# HELP model_gateway_provider_failures_total Failures grouped by configured provider.",
        "# TYPE model_gateway_provider_failures_total counter",
        *_provider_lines(
            "model_gateway_provider_failures_total",
            gateway_snapshot.get("provider_failures", {}),
        ),
    ]

    cache = _mapping(gateway_snapshot.get("cache"))
    if cache:
        lines.extend(
            [
                "# HELP model_gateway_cache_entries Current cached responses.",
                "# TYPE model_gateway_cache_entries gauge",
                _line("model_gateway_cache_entries", cache.get("entries", 0)),
                "# HELP model_gateway_cache_hits_total Cache hits.",
                "# TYPE model_gateway_cache_hits_total counter",
                _line("model_gateway_cache_hits_total", cache.get("hits", 0)),
                "# HELP model_gateway_cache_misses_total Cache misses.",
                "# TYPE model_gateway_cache_misses_total counter",
                _line("model_gateway_cache_misses_total", cache.get("misses", 0)),
            ]
        )

    usage = _mapping(gateway_snapshot.get("usage"))
    if usage:
        lines.extend(
            [
                "# HELP model_gateway_usage_records_total Recorded usage records.",
                "# TYPE model_gateway_usage_records_total counter",
                _line("model_gateway_usage_records_total", usage.get("records", 0)),
                "# HELP model_gateway_usage_input_tokens_total Input tokens recorded.",
                "# TYPE model_gateway_usage_input_tokens_total counter",
                _line(
                    "model_gateway_usage_input_tokens_total",
                    usage.get("input_tokens", 0),
                ),
                "# HELP model_gateway_usage_output_tokens_total Output tokens recorded.",
                "# TYPE model_gateway_usage_output_tokens_total counter",
                _line(
                    "model_gateway_usage_output_tokens_total",
                    usage.get("output_tokens", 0),
                ),
                "# HELP model_gateway_usage_estimated_cost Estimated aggregate model cost.",
                "# TYPE model_gateway_usage_estimated_cost gauge",
                _line(
                    "model_gateway_usage_estimated_cost",
                    usage.get("estimated_cost", 0),
                ),
                "# HELP model_gateway_usage_tenants Tenants with recorded usage.",
                "# TYPE model_gateway_usage_tenants gauge",
                _line("model_gateway_usage_tenants", usage.get("tenants", 0)),
            ]
        )

    configured_providers = health_snapshot.get("configured_providers", [])
    configured_count = (
        len(configured_providers)
        if isinstance(configured_providers, (list, tuple, set, frozenset))
        else 0
    )
    if http_snapshot is not None:
        lines.extend(
            [
                "# HELP http_requests_total Total HTTP requests.",
                "# TYPE http_requests_total counter",
                _line("http_requests_total", http_snapshot.get("requests", 0)),
                "# HELP http_errors_total HTTP responses with status 400 or higher.",
                "# TYPE http_errors_total counter",
                _line("http_errors_total", http_snapshot.get("errors", 0)),
                "# HELP http_active_requests Current in-flight HTTP requests.",
                "# TYPE http_active_requests gauge",
                _line("http_active_requests", http_snapshot.get("active", 0)),
                "# HELP http_request_duration_seconds HTTP request duration histogram.",
                "# TYPE http_request_duration_seconds histogram",
            ]
        )
        duration_buckets = cast(
            Mapping[float, object], _mapping(http_snapshot.get("duration_buckets"))
        )
        for bucket in HTTP_DURATION_BUCKETS:
            count = duration_buckets.get(bucket, 0)
            lines.append(
                f'http_request_duration_seconds_bucket{{le="{bucket:g}"}} '
                f"{_metric_number(count)}"
            )
        duration_count = http_snapshot.get("duration_count", 0)
        lines.extend(
            [
                f'http_request_duration_seconds_bucket{{le="+Inf"}} '
                f"{_metric_number(duration_count)}",
                _line(
                    "http_request_duration_seconds_sum",
                    http_snapshot.get("duration_sum_seconds", 0),
                ),
                _line("http_request_duration_seconds_count", duration_count),
                "# HELP http_responses_total HTTP responses grouped by fixed status class.",
                "# TYPE http_responses_total counter",
            ]
        )
        responses = _mapping(http_snapshot.get("responses"))
        for status_class in ("2xx", "3xx", "4xx", "5xx"):
            lines.append(
                f'http_responses_total{{status_class="{status_class}"}} '
                f"{_metric_number(responses.get(status_class, 0))}"
            )
        lines.extend(
            [
                "# HELP http_sse_disconnects_total SSE client disconnects observed.",
                "# TYPE http_sse_disconnects_total counter",
                _line(
                    "http_sse_disconnects_total",
                    http_snapshot.get("sse_disconnects", 0),
                ),
            ]
        )

    if worker_snapshot is not None:
        lines.extend(
            [
                "# HELP worker_queue_depth Current queued ingestion jobs.",
                "# TYPE worker_queue_depth gauge",
                _line("worker_queue_depth", worker_snapshot.get("queue_depth", 0)),
                "# HELP worker_active_jobs Current running ingestion jobs.",
                "# TYPE worker_active_jobs gauge",
                _line("worker_active_jobs", worker_snapshot.get("active", 0)),
                "# HELP worker_jobs_submitted_total Ingestion jobs submitted.",
                "# TYPE worker_jobs_submitted_total counter",
                _line(
                    "worker_jobs_submitted_total", worker_snapshot.get("submitted", 0)
                ),
                "# HELP worker_jobs_completed_total Ingestion jobs completed.",
                "# TYPE worker_jobs_completed_total counter",
                _line(
                    "worker_jobs_completed_total", worker_snapshot.get("completed", 0)
                ),
                "# HELP worker_jobs_failed_total Ingestion jobs failed.",
                "# TYPE worker_jobs_failed_total counter",
                _line("worker_jobs_failed_total", worker_snapshot.get("failed", 0)),
                "# HELP worker_jobs_cancelled_total Ingestion jobs cancelled.",
                "# TYPE worker_jobs_cancelled_total counter",
                _line(
                    "worker_jobs_cancelled_total", worker_snapshot.get("cancelled", 0)
                ),
                "# HELP worker_retries_total Ingestion job retries.",
                "# TYPE worker_retries_total counter",
                _line("worker_retries_total", worker_snapshot.get("retries", 0)),
                "# HELP worker_queue_wait_seconds Ingestion queue wait duration.",
                "# TYPE worker_queue_wait_seconds histogram",
            ]
        )
        queue_wait_buckets = cast(
            Mapping[float, object], _mapping(worker_snapshot.get("queue_wait_buckets"))
        )
        for bucket in WORKER_DURATION_BUCKETS:
            lines.append(
                f'worker_queue_wait_seconds_bucket{{le="{bucket:g}"}} '
                f"{_metric_number(queue_wait_buckets.get(bucket, 0))}"
            )
        queue_wait_count = worker_snapshot.get("queue_wait_count", 0)
        lines.extend(
            [
                f'worker_queue_wait_seconds_bucket{{le="+Inf"}} '
                f"{_metric_number(queue_wait_count)}",
                _line(
                    "worker_queue_wait_seconds_sum",
                    worker_snapshot.get("queue_wait_sum_seconds", 0),
                ),
                _line("worker_queue_wait_seconds_count", queue_wait_count),
                "# HELP worker_processing_seconds Ingestion processing duration.",
                "# TYPE worker_processing_seconds histogram",
            ]
        )
        processing_buckets = cast(
            Mapping[float, object], _mapping(worker_snapshot.get("processing_buckets"))
        )
        for bucket in WORKER_DURATION_BUCKETS:
            lines.append(
                f'worker_processing_seconds_bucket{{le="{bucket:g}"}} '
                f"{_metric_number(processing_buckets.get(bucket, 0))}"
            )
        processing_count = worker_snapshot.get("processing_count", 0)
        lines.extend(
            [
                f'worker_processing_seconds_bucket{{le="+Inf"}} '
                f"{_metric_number(processing_count)}",
                _line(
                    "worker_processing_seconds_sum",
                    worker_snapshot.get("processing_sum_seconds", 0),
                ),
                _line("worker_processing_seconds_count", processing_count),
            ]
        )
    lines.extend(
        [
            "# HELP model_gateway_circuit_open Whether the model gateway circuit is open.",
            "# TYPE model_gateway_circuit_open gauge",
            _line(
                "model_gateway_circuit_open", health_snapshot.get("circuit_open", False)
            ),
            "# HELP model_gateway_healthy Whether at least one provider is available.",
            "# TYPE model_gateway_healthy gauge",
            _line("model_gateway_healthy", health_snapshot.get("healthy", False)),
            "# HELP model_gateway_configured_providers Number of configured providers.",
            "# TYPE model_gateway_configured_providers gauge",
            _line(
                "model_gateway_configured_providers",
                configured_count,
            ),
            "",
        ]
    )
    return "\n".join(lines)
