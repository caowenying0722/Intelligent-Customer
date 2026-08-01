import json
import logging

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_access_log_is_structured_and_does_not_capture_request_secrets(caplog) -> None:
    client = TestClient(create_app())
    caplog.set_level(logging.INFO, logger="api.access")

    response = client.post(
        "/api/v1/chat",
        headers={
            "x-request-id": "request-123",
            "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
            "authorization": "Bearer secret-token",
        },
        json={"message": "private prompt body"},
    )

    assert response.status_code == 503
    records = [
        record
        for record in caplog.records
        if record.name == "api.access" and record.getMessage().startswith("{")
    ]
    assert records
    event = json.loads(records[-1].getMessage())
    assert event["event"] == "http.request"
    assert event["method"] == "POST"
    assert event["status_code"] == 503
    assert event["request_id"] == "request-123"
    assert event["trace_id"] == "11111111111111111111111111111111"
    assert event["duration_ms"] >= 0
    serialized = " ".join(record.getMessage() for record in records)
    assert "secret-token" not in serialized
    assert "private prompt body" not in serialized
    assert "authorization" not in serialized.lower()


def test_access_log_replaces_unbounded_request_id_with_safe_marker(caplog) -> None:
    client = TestClient(create_app())
    caplog.set_level(logging.INFO, logger="api.access")

    client.get("/health/live", headers={"x-request-id": "x" * 129})

    records = [
        record
        for record in caplog.records
        if record.name == "api.access" and record.getMessage().startswith("{")
    ]
    assert json.loads(records[-1].getMessage())["request_id"] == "invalid"
