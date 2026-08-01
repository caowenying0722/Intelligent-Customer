import pytest
import time
from concurrent.futures import ThreadPoolExecutor

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


def test_idempotency_ttl_allows_new_execution_after_expiry():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda prompt: calls.append(prompt) or len(calls)},
        idempotency_store=IdempotencyStore(ttl_seconds=0.01),
    )
    request = ModelRequest(tenant_id="a", provider="fake", model="m", prompt="one")
    assert gateway.invoke_idempotent(request, idempotency_key="k").output == "1"
    time.sleep(0.02)
    assert gateway.invoke_idempotent(request, idempotency_key="k").output == "2"


def test_idempotency_serializes_concurrent_same_key():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda prompt: calls.append(prompt) or "ok"},
        idempotency_store=IdempotencyStore(),
    )
    request = ModelRequest(tenant_id="a", provider="fake", model="m", prompt="one")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: gateway.invoke_idempotent(request, idempotency_key="k").output, range(4)))
    assert results == ["ok"] * 4
    assert calls == ["one"]
