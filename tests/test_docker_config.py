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
    assert services["prometheus"]["depends_on"]["api"]["condition"] == (
        "service_healthy"
    )
    assert "Authorization" not in str(compose)
    assert "API_KEY" not in str(compose)

    collector = Path("deploy/observability/otel-collector.yaml").read_text(
        encoding="utf-8"
    )
    prometheus = Path("deploy/observability/prometheus.yml").read_text(encoding="utf-8")
    assert "health_check" in collector
    assert "metrics_path: /metrics/prometheus" in prometheus
    assert "api:8000" in prometheus
