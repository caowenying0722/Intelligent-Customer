import pytest

from model.gateway import ModelGateway, ModelGatewayError
from model.quota import TenantQuota
from model.cost import CostTracker
from decimal import Decimal


def test_tenant_quota_isolated_and_bounded():
    quota = TenantQuota(max_calls=1, window_seconds=60)
    assert quota.consume("a") is True
    assert quota.consume("a") is False
    assert quota.consume("b") is True


def test_gateway_rejects_quota_before_provider():
    calls = []
    gateway = ModelGateway(
        {"fake": lambda request: calls.append(request) or "ok"},
        quota=TenantQuota(max_calls=1),
    )
    kwargs = dict(provider="fake", model="m", tenant_id="a", prompt="p", request="p")
    assert gateway.invoke_cached(**kwargs) == "ok"
    with pytest.raises(ModelGatewayError, match="quota"):
        gateway.invoke_cached(**kwargs)
    assert calls == ["p"]


def test_gateway_maps_cost_budget_to_stable_error():
    gateway = ModelGateway(
        {"fake": lambda request: "ok"},
        cost_tracker=CostTracker(max_cost_per_tenant=Decimal("0")),
    )
    with pytest.raises(ModelGatewayError, match="cost budget"):
        gateway.record_usage(
            tenant_id="a", provider="fake", model="m", input_tokens=1,
            output_tokens=0, input_cost_per_1k=Decimal("1"),
        )
