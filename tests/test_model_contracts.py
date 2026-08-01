import pytest

from model.contracts import ModelRequest, ModelResponse
from model.gateway import ModelGateway


def test_gateway_returns_provider_neutral_contract():
    gateway = ModelGateway({"fake": lambda prompt: "answer:" + prompt})
    response = gateway.invoke_contract(
        ModelRequest(tenant_id="t", provider="fake", model="m", prompt="hello", request_id="r1")
    )
    assert isinstance(response, ModelResponse)
    assert response.output == "answer:hello"
    assert response.provider == "fake"
    assert response.trace_metadata == {"request_id": "r1"}
    assert response.usage.latency_ms >= 0


def test_request_contract_rejects_extra_fields():
    with pytest.raises(ValueError):
        ModelRequest(tenant_id="t", provider="fake", model="m", prompt="x", secret="bad")
