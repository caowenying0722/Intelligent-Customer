"""Safe, bounded Prometheus rendering for aggregate gateway metrics."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

MAX_PROVIDER_SERIES = 32


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
    gateway_snapshot: Mapping[str, object], health_snapshot: Mapping[str, object]
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
