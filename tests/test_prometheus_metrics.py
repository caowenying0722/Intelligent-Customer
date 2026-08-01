from decimal import Decimal

from fastapi.testclient import TestClient

from model.cost import CostTracker
from model.gateway import ModelGateway
from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_prometheus_metrics_are_scrapable_and_aggregate_only():
    gateway = ModelGateway(
        {"fake": lambda request: request}, cost_tracker=CostTracker()
    )
    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    client = TestClient(create_app(chat_service=service))
    client.post("/api/v1/chat", json={"message": "secret-input"})

    response = client.get("/metrics/prometheus")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "model_gateway_calls_total 1" in response.text
    assert 'model_gateway_provider_calls_total{provider="fake"} 1' in response.text
    assert "secret-input" not in response.text
    assert "conversation" not in response.text.lower()


def test_prometheus_metrics_without_gateway_are_zero_valued():
    response = TestClient(create_app()).get("/metrics/prometheus")

    assert response.status_code == 200
    assert "model_gateway_calls_total 0" in response.text
    assert "model_gateway_healthy 0" in response.text


def test_prometheus_metrics_expose_cost_without_tenant_identity():
    tracker = CostTracker()
    gateway = ModelGateway({"fake": lambda _: "ok"}, cost_tracker=tracker)
    gateway.record_usage(
        tenant_id="tenant-secret",
        provider="fake",
        model="m",
        input_tokens=10,
        output_tokens=5,
        input_cost_per_1k=Decimal("1"),
        output_cost_per_1k=Decimal("2"),
    )

    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    response = TestClient(create_app(chat_service=service)).get("/metrics/prometheus")

    assert "model_gateway_usage_records_total 1" in response.text
    assert "model_gateway_usage_tenants 1" in response.text
    assert "tenant-secret" not in response.text
