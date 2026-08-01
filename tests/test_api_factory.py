import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
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
    body = response.json()
    assert body["request_id"] == "req-chat"
    assert body["answer"] == "echo:你好"
    assert body["conversation_id"]


def test_chat_route_reuses_conversation_id() -> None:
    service = ChatApplicationService(FakeAgent())
    client = TestClient(create_app(chat_service=service))

    first = client.post("/api/v1/chat", json={"message": "one"}).json()
    second = client.post(
        "/api/v1/chat",
        json={"message": "two", "conversation_id": first["conversation_id"]},
    )

    assert second.status_code == 200
    conversation = service.conversation_repository.get(UUID(first["conversation_id"]))
    assert conversation is not None
    assert [message.content for message in conversation.messages] == [
        "one",
        "echo:one",
        "two",
        "echo:two",
    ]


def test_conversation_query_returns_messages_and_stable_404() -> None:
    service = ChatApplicationService(FakeAgent())
    client = TestClient(create_app(chat_service=service))
    created = client.post("/api/v1/chat", json={"message": "hello"}).json()

    response = client.get(f"/api/v1/conversations/{created['conversation_id']}")
    missing = client.get("/api/v1/conversations/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["messages"]] == [
        "hello",
        "echo:hello",
    ]
    assert missing.status_code == 404
    assert missing.json()["code"] == "conversation_not_found"


def test_chat_route_rejects_extra_fields_without_calling_agent() -> None:
    client = TestClient(create_app(chat_service=ChatApplicationService(FakeAgent())))

    response = client.post("/api/v1/chat", json={"message": "hi", "secret": "x"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["request_id"]


def test_http_exception_uses_stable_error_contract() -> None:
    app = create_app()

    @app.get("/test-http-error")
    async def test_http_error() -> None:
        raise HTTPException(status_code=409, detail="conflict")

    response = TestClient(app).get(
        "/test-http-error", headers={"x-request-id": "req-error"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "http_error",
        "message": "conflict",
        "request_id": "req-error",
    }


def test_unhandled_exception_does_not_leak_details() -> None:
    app = create_app()

    @app.get("/test-internal-error")
    async def test_internal_error() -> None:
        raise RuntimeError("secret provider response")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-internal-error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "secret provider" not in response.text


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


def test_async_runner_cancellation_is_not_mapped_to_chat_failure() -> None:
    cancelled = asyncio.Event()

    async def blocking_runner(_agent: object, _message: str) -> str:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    async def exercise() -> None:
        service = ChatApplicationService(FakeAgent(), async_runner=blocking_runner)
        task = asyncio.create_task(service.chat("cancel"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert cancelled.is_set()


def test_application_lifespan_closes_resources_on_shutdown() -> None:
    class Resource:
        closed = False

        def close(self) -> None:
            self.closed = True

    resource = Resource()
    with TestClient(create_app(lifecycle_resources=(resource,))) as client:
        assert client.get("/health/live").status_code == 200
    assert resource.closed
