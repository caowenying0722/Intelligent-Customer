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


def test_compose_runs_postgres_migrations_before_api() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["postgres"]["healthcheck"]["test"][0] == "CMD-SHELL"
    assert services["postgres"]["volumes"] == ["postgres-data:/var/lib/postgresql/data"]
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["migrate"]["depends_on"]["postgres"]["condition"] == (
        "service_healthy"
    )
    assert services["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert "postgres-data" in compose["volumes"]


def test_compose_runs_qdrant_with_health_gate_and_persistent_storage() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["qdrant"]["image"] == "qdrant/qdrant:v1.18.3-unprivileged"
    assert services["qdrant"]["ports"] == ["127.0.0.1:${QDRANT_PORT:-6333}:6333"]
    assert services["qdrant"]["volumes"] == ["qdrant-data:/qdrant/storage"]
    assert services["api"]["depends_on"]["qdrant"]["condition"] == "service_healthy"
    assert services["api"]["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert "qdrant-data" in compose["volumes"]


def test_dockerfile_uses_python_310_non_root_and_healthcheck() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "python:3.10-slim" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "pip install -r requirements-api.lock" in dockerfile


def test_api_runtime_lock_contains_server_dependencies_without_rag_heavyweights() -> (
    None
):
    lock = Path("requirements-api.lock").read_text(encoding="utf-8").lower()

    assert "\nlangchain==1.3.9\n" in lock
    assert "\nlanggraph-checkpoint-postgres==3.1.1\n" in lock
    assert "\npsycopg[binary,pool]==3.3.4\n" in lock
    assert "\ntorch==" not in lock
    assert "\nchromadb==" not in lock
    assert "\nsentence-transformers==" not in lock


def test_observability_profile_is_explicit_and_configured_without_secrets() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["otel-collector"]["profiles"] == ["observability"]
    assert services["jaeger"]["profiles"] == ["observability"]
    assert services["jaeger"]["volumes"] == ["jaeger-data:/badger"]
    assert services["otel-collector"]["depends_on"]["jaeger"]["condition"] == (
        "service_healthy"
    )
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
    assert services["otel-collector"]["healthcheck"]["test"] == [
        "CMD",
        "/otelcol-contrib",
        "components",
    ]
    assert "metrics_path: /metrics/prometheus" in prometheus
    assert "api:8000" in prometheus
    assert "otlp/jaeger" in collector
    assert "timeout: 5s" in collector
    assert "queue_size: 128" in collector


def test_worker_profile_is_optional_and_has_broker_health_gate() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["redis"]["profiles"] == ["workers"]
    assert services["redis"]["healthcheck"]["test"] == [
        "CMD",
        "redis-cli",
        "ping",
    ]
    assert services["worker"]["profiles"] == ["workers"]
    assert services["worker"]["depends_on"]["redis"]["condition"] == ("service_healthy")
    assert services["worker"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["worker"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert services["worker"]["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert services["worker"]["volumes"] == ["uploads-data:/app/output/uploads"]
    assert services["api"]["volumes"] == ["uploads-data:/app/output/uploads"]
    assert services["upload-init"]["user"] == "0:0"
    assert services["upload-init"]["restart"] == "no"
    assert services["api"]["depends_on"]["upload-init"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["worker"]["depends_on"]["upload-init"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["api"]["environment"]["INGESTION_WORKER_BACKEND"] == (
        "${INGESTION_WORKER_BACKEND:-local}"
    )
    assert "uploads-data" in compose["volumes"]
    assert "USER app" in Path("Dockerfile.worker").read_text(encoding="utf-8")
    assert "celery" in Path("requirements-worker.lock").read_text(encoding="utf-8")


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
