from fastapi.testclient import TestClient

from model.gateway import ModelGateway
from model.cache import ModelCache
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_metrics_exposes_only_gateway_counters():
    gateway = ModelGateway({"fake": lambda request: request}, cache=ModelCache())
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    client = TestClient(create_app(chat_service=service))
    client.post("/api/v1/chat", json={"message": "secret-input"})
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()["model_gateway"]
    assert body["calls"] == 1
    assert body["provider_calls"] == {"fake": 1}
    assert body["cache"]["entries"] == 0
    assert body["cache"]["hits"] == 0
    assert body["cache"]["misses"] == 0
    assert "secret-input" not in response.text
    assert response.json()["model_gateway_health"]["healthy"] is True


def test_metrics_without_gateway_returns_zero_counters():
    response = TestClient(create_app()).get("/metrics")
    assert response.json()["model_gateway"]["calls"] == 0
