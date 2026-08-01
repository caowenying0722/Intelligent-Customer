from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.observability.metrics import HttpMetrics, render_prometheus


def test_http_metrics_track_fixed_aggregate_dimensions():
    metrics = HttpMetrics()
    started = metrics.begin()
    metrics.end(started, status_code=200, path="/health/live")
    started = metrics.begin()
    metrics.end(started, status_code=404, path="/api/v1/chat/stream")

    snapshot = metrics.snapshot()
    text = render_prometheus({}, {}, snapshot)

    assert snapshot["requests"] == 2
    assert snapshot["errors"] == 1
    assert snapshot["active"] == 0
    assert snapshot["responses"] == {"2xx": 1, "3xx": 0, "4xx": 1, "5xx": 0}
    assert "http_requests_total 2" in text
    assert 'status_class="4xx"} 1' in text
    assert "http_request_duration_seconds_bucket" in text
    assert "path" not in text
    assert "conversation" not in text


def test_http_middleware_tracks_success_and_error_without_sensitive_labels():
    app = create_app()
    client = TestClient(app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/does-not-exist").status_code == 404

    snapshot = app.state.http_metrics.snapshot()
    assert snapshot["requests"] == 2
    assert snapshot["errors"] == 1
    assert snapshot["active"] == 0

    response = client.get("/metrics/prometheus")
    assert "http_requests_total 2" in response.text
    assert "http_errors_total 1" in response.text
    assert "tenant" not in response.text.lower()
    assert "secret" not in response.text.lower()
