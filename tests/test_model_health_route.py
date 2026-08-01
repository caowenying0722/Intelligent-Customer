from fastapi.testclient import TestClient

from model.gateway import ModelGateway
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_model_health_route_requires_optional_token():
    gateway = ModelGateway({"fake": lambda _: "ok"})
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    client = TestClient(create_app(chat_service=service, model_health_token="admin"))
    assert client.get("/health/model").status_code == 401
    response = client.get("/health/model", headers={"x-model-health-token": "admin"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["configured_providers"] == ["fake"]


def test_model_health_without_gateway_is_unhealthy():
    response = TestClient(create_app()).get("/health/model")
    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"
