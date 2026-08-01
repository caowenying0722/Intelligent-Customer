from fastapi.testclient import TestClient

from model.gateway import ModelGateway, PermanentModelError
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return "agent:" + message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_chat_service_can_use_gateway_instead_of_direct_provider():
    gateway = ModelGateway({"fake": lambda request: "gateway:" + request})
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    response = TestClient(create_app(chat_service=service)).post(
        "/api/v1/chat", json={"message": "hello"}
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "gateway:hello"


def test_gateway_provider_error_maps_to_stable_chat_error():
    gateway = ModelGateway({"fake": lambda _: (_ for _ in ()).throw(PermanentModelError("secret"))})
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    response = TestClient(create_app(chat_service=service)).post(
        "/api/v1/chat", json={"message": "hello"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "chat_failed"
    assert response.json()["message"] == "chat execution failed"
