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

    def provider(request):
        calls.append(request)
        return "cached-answer"

    gateway = ModelGateway(
        {"fake": provider},
        cache=ModelCache(),
    )
    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    client = TestClient(create_app(chat_service=service))
    for tenant in ("a", "a", "b"):
        response = client.post(
            "/api/v1/chat", headers={"x-tenant-id": tenant}, json={"message": "same"}
        )
        assert response.status_code == 200
    assert calls == ["same", "same"]


def test_chat_cache_hit_is_visible_in_metrics():
    gateway = ModelGateway({"fake": lambda request: "answer"}, cache=ModelCache())
    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    client = TestClient(create_app(chat_service=service))
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/chat", headers={"x-tenant-id": "a"}, json={"message": "same"}
            ).status_code
            == 200
        )
    metrics = client.get("/metrics").json()
    assert metrics["model_gateway"]["cache"]["hits"] == 1
    assert metrics["model_gateway"]["provider_calls"] == {"fake": 1}


def test_chat_idempotency_still_rejects_duplicate_business_run():
    gateway = ModelGateway({"fake": lambda request: "answer"}, cache=ModelCache())
    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    client = TestClient(create_app(chat_service=service))
    payload = {"message": "same", "idempotency_key": "request-1"}
    assert client.post("/api/v1/chat", json=payload).status_code == 200
    duplicate = client.post("/api/v1/chat", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "idempotency_reused"
