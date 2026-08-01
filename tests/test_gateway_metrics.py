from fastapi.testclient import TestClient

from model.gateway import ModelGateway
from model.cache import ModelCache
from model.cost import CostTracker
from decimal import Decimal
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
    assert body["cache"]["entries"] == 1
    assert body["cache"]["hits"] == 0
    assert body["cache"]["misses"] == 1
    assert "secret-input" not in response.text
    assert response.json()["model_gateway_health"]["healthy"] is True


def test_metrics_without_gateway_returns_zero_counters():
    response = TestClient(create_app()).get("/metrics")
    assert response.json()["model_gateway"]["calls"] == 0


def test_metrics_exposes_aggregate_usage_without_tenant_details():
    tracker = CostTracker()
    gateway = ModelGateway({"fake": lambda _: "ok"}, cost_tracker=tracker)
    gateway.record_usage(
        tenant_id="tenant-secret", provider="fake", model="m", input_tokens=10,
        output_tokens=5, input_cost_per_1k=Decimal("1"), output_cost_per_1k=Decimal("2"),
    )
    service = ChatApplicationService(Agent(), model_gateway=gateway, model_provider="fake")
    response = TestClient(create_app(chat_service=service)).get("/metrics")
    body = response.json()["model_gateway"]["usage"]
    assert body["records"] == 1
    assert body["input_tokens"] == 10
    assert body["output_tokens"] == 5
    assert body["tenants"] == 1
    assert "tenant-secret" not in response.text
