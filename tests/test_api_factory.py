import asyncio

from fastapi.testclient import TestClient

from src.app.application.chat import ChatApplicationService
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


class FakeAgent:
    def run(self, message: str) -> str:
        return f"echo:{message}"

    def stream(self, message: str) -> list[str]:
        return ["echo:", message]


def test_chat_route_uses_injected_agent_and_stable_response() -> None:
    service = ChatApplicationService(FakeAgent())
    client = TestClient(create_app(chat_service=service))

    response = client.post(
        "/api/v1/chat",
        json={"message": "你好"},
        headers={"x-request-id": "req-chat"},
    )

    assert response.status_code == 200
    assert response.json() == {"request_id": "req-chat", "answer": "echo:你好"}


def test_chat_route_rejects_extra_fields_without_calling_agent() -> None:
    client = TestClient(create_app(chat_service=ChatApplicationService(FakeAgent())))

    response = client.post("/api/v1/chat", json={"message": "hi", "secret": "x"})

    assert response.status_code == 422


def test_chat_route_maps_timeout_without_traceback() -> None:
    async def never_finishes(_agent: object, _message: str):
        await asyncio.sleep(1)

    service = ChatApplicationService(
        FakeAgent(), timeout_seconds=0.01, run_in_thread=never_finishes
    )
    client = TestClient(create_app(chat_service=service))

    response = client.post("/api/v1/chat", json={"message": "slow"})

    assert response.status_code == 504
    assert response.json()["code"] == "chat_timeout"
    assert "Traceback" not in response.text


def test_chat_sse_emits_metadata_tokens_and_single_completed_event() -> None:
    client = TestClient(create_app(chat_service=ChatApplicationService(FakeAgent())))

    response = client.post("/api/v1/chat/stream", json={"message": "你好"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count('"type": "metadata"') == 1
    assert response.text.count('"type": "token"') == 2
    assert response.text.count('"type": "completed"') == 1
