from fastapi.testclient import TestClient

from src.app.main import create_app


def test_liveness_is_side_effect_free() -> None:
    called = False

    def readiness_check() -> bool:
        nonlocal called
        called = True
        return True

    response = TestClient(create_app(readiness_check=readiness_check)).get(
        "/health/live"
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not called


def test_readiness_returns_stable_failure_and_request_id() -> None:
    client = TestClient(create_app(readiness_check=lambda: False))

    response = client.get("/health/ready", headers={"x-request-id": "req-123"})

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert response.headers["x-request-id"] == "req-123"


def test_default_readiness_is_ready() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["x-request-id"]
