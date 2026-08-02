"""Check API, Collector, Prometheus, Grafana and persistent Jaeger health."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def _json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError(f"health endpoint returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("health endpoint returned a non-object payload")
    return payload


def check(*, host: str = "127.0.0.1", timeout: float = 5.0) -> dict[str, str]:
    if timeout <= 0 or timeout > 60:
        raise ValueError("timeout must be between 0 and 60 seconds")
    api = _json(f"http://{host}:8000/health/live", timeout)
    collector = _json(f"http://{host}:13133/", timeout)
    prometheus = _json(f"http://{host}:9090/api/v1/targets", timeout)
    grafana = _json(f"http://{host}:3000/api/health", timeout)
    jaeger = _json(f"http://{host}:16686/api/services", timeout)
    active = prometheus.get("data", {}).get("activeTargets", [])
    if not any(
        isinstance(target, dict)
        and target.get("health") == "up"
        and "api:8000/metrics/prometheus" in str(target.get("scrapeUrl", ""))
        for target in active
    ):
        raise RuntimeError("Prometheus has no healthy API scrape target")
    if api.get("status") != "ok" or collector.get("status") != "Server available":
        raise RuntimeError("API or Collector is not ready")
    if grafana.get("database") != "ok":
        raise RuntimeError("Grafana database is not ready")
    if not isinstance(jaeger.get("data"), list):
        raise RuntimeError("Jaeger query API is not ready")
    return {
        "api": "ok",
        "collector": "ok",
        "prometheus": "ok",
        "grafana": "ok",
        "jaeger": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    print(json.dumps(check(host=args.host, timeout=args.timeout), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
