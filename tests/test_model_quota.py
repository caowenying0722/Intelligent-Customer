import pytest

from model.gateway import ModelGateway, ModelGatewayError
from model.quota import TenantQuota


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
