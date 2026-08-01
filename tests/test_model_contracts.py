import pytest

from model.contracts import ModelRequest, ModelResponse
from model.gateway import ModelGateway
from model.cache import ModelCache


def test_gateway_returns_provider_neutral_contract():
    gateway = ModelGateway({"fake": lambda prompt: "answer:" + prompt})
    response = gateway.invoke_contract(
        ModelRequest(tenant_id="t", provider="fake", model="m", prompt="hello", request_id="r1")
    )
    assert isinstance(response, ModelResponse)
    assert response.output == "answer:hello"
    assert response.provider == "fake"
    assert response.trace_metadata["request_id"] == "r1"
    assert len(response.trace_metadata["request_fingerprint"]) == 64
    assert "hello" not in response.trace_metadata["request_fingerprint"]
    assert response.fallback_chain == []
    assert response.retry_count == 0
    assert response.usage.latency_ms >= 0


def test_request_contract_rejects_extra_fields():
    with pytest.raises(ValueError):
        ModelRequest(tenant_id="t", provider="fake", model="m", prompt="x", secret="bad")


def test_contract_reports_cache_hit_without_provider_call():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda prompt: calls.append(prompt) or "answer"}, cache=ModelCache()
    )
    request = ModelRequest(tenant_id="t", provider="fake", model="m", prompt="hello")
    first = gateway.invoke_contract(request)
    second = gateway.invoke_contract(request)
    assert first.usage.cache_hit is False
    assert second.usage.cache_hit is True
    assert calls == ["hello"]


def test_contract_accepts_explicit_routing_metadata():
    gateway = ModelGateway({"fake": lambda _: "ok"})
    response = gateway.invoke_contract(
        ModelRequest(tenant_id="t", provider="fake", model="m", prompt="x"),
        finish_reason="length", retry_count=1, fallback_chain=["primary", "fake"],
    )
    assert response.finish_reason == "length"
    assert response.retry_count == 1
    assert response.fallback_chain == ["primary", "fake"]
