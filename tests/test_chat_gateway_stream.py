from fastapi.testclient import TestClient

from model.gateway import ModelGateway, PermanentModelError
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_stream_route_uses_gateway_chunks():
    gateway = ModelGateway({"fake": lambda _: ["a", "b"]})
    service = ChatApplicationService(
        Agent(), stream_gateway=gateway, model_provider="fake"
    )
    response = TestClient(create_app(chat_service=service)).post(
        "/api/v1/chat/stream", json={"message": "hello"}
    )
    assert response.status_code == 200
    assert '"text": "a"' in response.text
    assert '"text": "b"' in response.text
    assert '"type": "completed"' in response.text


def test_stream_gateway_error_is_safe():
    gateway = ModelGateway(
        {"fake": lambda _: (_ for _ in ()).throw(PermanentModelError("secret"))}
    )
    service = ChatApplicationService(
        Agent(), stream_gateway=gateway, model_provider="fake"
    )
    response = TestClient(create_app(chat_service=service)).post(
        "/api/v1/chat/stream", json={"message": "hello"}
    )
    assert response.status_code == 200
    assert '"code": "chat_failed"' in response.text
    assert "secret" not in response.text


def test_stream_gateway_timeout_uses_model_error_code():
    gateway = ModelGateway(
        {"fake": lambda _: (_ for _ in ()).throw(TimeoutError("secret timeout"))},
        timeout_seconds=0.1,
    )
    service = ChatApplicationService(
        Agent(), stream_gateway=gateway, model_provider="fake"
    )
    response = TestClient(create_app(chat_service=service)).post(
        "/api/v1/chat/stream", json={"message": "hello"}
    )
    assert '"code": "timeout"' in response.text
    assert "secret timeout" not in response.text
