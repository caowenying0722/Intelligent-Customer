import pytest

from model.errors import ModelErrorCode
from model.gateway import ModelGatewayError


@pytest.mark.parametrize(
    ("message", "code", "retryable"),
    [
        ("model request exceeded configured timeout", ModelErrorCode.TIMEOUT, True),
        ("model gateway rate limit reached", ModelErrorCode.RATE_LIMITED, True),
        ("model cost budget exceeded", ModelErrorCode.BUDGET_EXCEEDED, False),
        (
            "model response schema validation failed",
            ModelErrorCode.MALFORMED_OUTPUT,
            False,
        ),
    ],
)
def test_gateway_error_maps_to_stable_contract(message, code, retryable):
    error = ModelGatewayError(message).to_contract(provider="fake")
    assert error.code == code
    assert error.retryable is retryable
    assert error.provider == "fake"
