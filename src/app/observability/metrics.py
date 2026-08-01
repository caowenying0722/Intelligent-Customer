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
