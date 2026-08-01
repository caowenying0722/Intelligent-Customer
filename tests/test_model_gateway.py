import time

import pytest

from model.gateway import (
    ModelGateway,
    ModelGatewayError,
    PermanentModelError,
    RetryableModelError,
)


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
