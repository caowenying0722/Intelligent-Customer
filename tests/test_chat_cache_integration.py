from fastapi.testclient import TestClient

from model.cache import ModelCache
from model.gateway import ModelGateway
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return "agent:" + message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_chat_cache_is_tenant_scoped():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda request: calls.append(request) or "cached-answer"},
        cache=ModelCache(),
    )
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    client = TestClient(create_app(chat_service=service))
    for tenant in ("a", "a", "b"):
        response = client.post(
            "/api/v1/chat", headers={"x-tenant-id": tenant}, json={"message": "same"}
        )
        assert response.status_code == 200
    assert calls == ["same", "same"]
