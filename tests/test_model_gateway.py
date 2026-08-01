import time

import pytest

from model.gateway import (
    ModelGateway,
    ModelGatewayError,
    PermanentModelError,
    RetryableModelError,
)
from model.cache import ModelCache


def test_gateway_routes_to_provider_and_retries_bounded_failure():
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) < 2:
            raise RetryableModelError("temporary")
        return {"answer": request}

    gateway = ModelGateway({"fake": provider}, timeout_seconds=0.1, max_retries=2)
    assert gateway.invoke(provider="fake", request="hello") == {"answer": "hello"}
    assert len(calls) == 2


def test_gateway_does_not_retry_permanent_failure():
    calls = []

    def provider(_):
        calls.append(1)
        raise PermanentModelError("bad request")

    with pytest.raises(ModelGatewayError, match="rejected"):
        ModelGateway({"fake": provider}, max_retries=3).invoke(provider="fake", request={})
    assert len(calls) == 1


def test_gateway_times_out_and_caps_retries():
    with pytest.raises(ModelGatewayError, match="timeout"):
        ModelGateway({"fake": lambda _: time.sleep(0.1)}, timeout_seconds=0.01, max_retries=1).invoke(provider="fake", request={})


def test_gateway_rejects_unknown_provider():
    with pytest.raises(ModelGatewayError, match="not configured"):
        ModelGateway({}).invoke(provider="missing", request={})


def test_gateway_opens_circuit_after_consecutive_failures():
    def provider(_):
        raise PermanentModelError("down")

    gateway = ModelGateway({"fake": provider}, failure_threshold=2, cooldown_seconds=1)
    for _ in range(2):
        with pytest.raises(ModelGatewayError, match="rejected"):
            gateway.invoke(provider="fake", request={})
    with pytest.raises(ModelGatewayError, match="circuit is open"):
        gateway.invoke(provider="fake", request={})
    assert gateway.stats == {"calls": 2, "failures": 2}


def test_gateway_success_resets_consecutive_failures():
    state = {"fail": True}

    def provider(_):
        if state["fail"]:
            raise PermanentModelError("down")
        return "ok"

    gateway = ModelGateway({"fake": provider}, failure_threshold=2)
    with pytest.raises(ModelGatewayError):
        gateway.invoke(provider="fake", request={})
    state["fail"] = False
    assert gateway.invoke(provider="fake", request={}) == "ok"
    state["fail"] = True
    with pytest.raises(ModelGatewayError, match="rejected"):
        gateway.invoke(provider="fake", request={})


def test_gateway_routes_alias_to_fallback_provider():
    gateway = ModelGateway({
        "primary": lambda _: (_ for _ in ()).throw(PermanentModelError("down")),
        "backup": lambda request: "backup:" + request,
    })
    assert gateway.invoke_routed(
        route="chat", request="hello", routes={"chat": "primary"},
        fallbacks={"chat": ["backup"]},
    ) == "backup:hello"


def test_gateway_rejects_unknown_model_route():
    with pytest.raises(ModelGatewayError, match="route is not configured"):
        ModelGateway({}).invoke_routed(route="missing", request={}, routes={})


def test_gateway_audit_snapshot_contains_counts_only():
    gateway = ModelGateway({"fake": lambda request: request})
    gateway.invoke(provider="fake", request={"api_key": "secret"})
    snapshot = gateway.audit_snapshot()
    assert snapshot["provider_calls"] == {"fake": 1}
    assert "secret" not in repr(snapshot)
    assert "api_key" not in repr(snapshot)


def test_gateway_rate_limit_rejects_excess_calls_before_provider():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda request: calls.append(request) or "ok"},
        rate_limit_per_second=1,
    )
    assert gateway.invoke(provider="fake", request="first") == "ok"
    with pytest.raises(ModelGatewayError, match="rate limit"):
        gateway.invoke(provider="fake", request="second")
    assert calls == ["first"]


def test_gateway_cache_hit_skips_provider_and_scopes_tenant():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda request: calls.append(request) or "answer"},
        cache=ModelCache(),
    )
    kwargs = dict(provider="fake", model="m", tenant_id="tenant-a", prompt="hello", request="hello")
    assert gateway.invoke_cached(**kwargs) == "answer"
    assert gateway.invoke_cached(**kwargs) == "answer"
    assert gateway.invoke_cached(**{**kwargs, "tenant_id": "tenant-b"}) == "answer"
    assert calls == ["hello", "hello"]
