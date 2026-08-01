import pytest

from model.contracts import ModelRequest
from model.gateway import ModelGateway, ModelGatewayError
from model.idempotency import IdempotencyStore


def test_gateway_idempotency_reuses_same_result():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda prompt: calls.append(prompt) or "ok"},
        idempotency_store=IdempotencyStore(),
    )
    request = ModelRequest(tenant_id="a", provider="fake", model="m", prompt="hi")
    assert gateway.invoke_idempotent(request, idempotency_key="k").output == "ok"
    assert gateway.invoke_idempotent(request, idempotency_key="k").output == "ok"
    assert calls == ["hi"]


def test_gateway_idempotency_conflict_is_stable_error():
    gateway = ModelGateway(
        {"fake": lambda prompt: "ok"}, idempotency_store=IdempotencyStore()
    )
    gateway.invoke_idempotent(
        ModelRequest(tenant_id="a", provider="fake", model="m", prompt="one"),
        idempotency_key="k",
    )
    with pytest.raises(ModelGatewayError, match="idempotency"):
        gateway.invoke_idempotent(
            ModelRequest(tenant_id="a", provider="fake", model="m", prompt="two"),
            idempotency_key="k",
        )
