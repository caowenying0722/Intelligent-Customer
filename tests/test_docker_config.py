import json
from pathlib import Path

import yaml


def test_compose_api_baseline_is_health_checked_and_does_not_embed_keys() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]

    assert api["environment"]["API_HOST"] == "0.0.0.0"
    assert api["healthcheck"]["test"][0:2] == ["CMD", "python"]
    assert "API_KEY" not in str(api)
    assert "ANTHROPIC" not in str(api)


def test_dockerfile_uses_python_310_non_root_and_healthcheck() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "python:3.10-slim" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "pip install -r requirements.lock" in dockerfile


def test_observability_profile_is_explicit_and_configured_without_secrets() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["otel-collector"]["profiles"] == ["observability"]
    assert services["prometheus"]["profiles"] == ["observability"]
    assert services["grafana"]["profiles"] == ["observability"]
    assert services["prometheus"]["depends_on"]["api"]["condition"] == (
        "service_healthy"
    )
    assert services["grafana"]["environment"]["GF_AUTH_ANONYMOUS_ORG_ROLE"] == (
        "Viewer"
    )
    assert services["grafana"]["ports"] == ["127.0.0.1:3000:3000"]
    assert "Authorization" not in str(compose)
    assert "API_KEY" not in str(compose)

    collector = Path("deploy/observability/otel-collector.yaml").read_text(
        encoding="utf-8"
    )
    prometheus = Path("deploy/observability/prometheus.yml").read_text(encoding="utf-8")
    assert "health_check" in collector
    assert "metrics_path: /metrics/prometheus" in prometheus
    assert "api:8000" in prometheus


def test_grafana_dashboard_uses_only_existing_bounded_metrics() -> None:
    dashboard = json.loads(
        Path("deploy/observability/grafana/dashboards/api-overview.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(dashboard)

    assert dashboard["uid"] == "intelligent-customer-api"
    assert '"uid": "Prometheus"' in serialized
    assert "http_requests_total" in serialized
    assert "http_request_duration_seconds_bucket" in serialized
    assert "model_gateway_calls_total" in serialized
    assert "tenant_id" not in serialized
    assert "conversation_id" not in serialized
