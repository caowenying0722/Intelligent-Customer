import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.observability.metrics import metrics_token_matches
from utils.settings import clear_settings_cache


def test_metrics_token_comparison_is_optional_or_exact():
    assert metrics_token_matches(None, None)
    assert metrics_token_matches("secret", "secret")
    assert not metrics_token_matches("secret", None)
    assert not metrics_token_matches("secret", "other")


def test_metrics_routes_require_configured_token():
    app = create_app(metrics_token="m" * 32)
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics/prometheus").status_code == 401
    headers = {"x-metrics-token": "m" * 32}
    assert client.get("/metrics", headers=headers).status_code == 200
    assert client.get("/metrics/prometheus", headers=headers).status_code == 200


def test_production_requires_metrics_token(monkeypatch):
    monkeypatch.setenv("APPLICATION_ENV", "production")
    monkeypatch.setenv("MODEL_HEALTH_TOKEN", "h" * 32)
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    clear_settings_cache()
    try:
        with pytest.raises(ValueError, match="METRICS_TOKEN"):
            create_app()
    finally:
        clear_settings_cache()
