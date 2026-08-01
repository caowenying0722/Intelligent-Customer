from typing import cast

import pytest
from pydantic import BaseModel

from model.gateway import ModelGateway, ModelGatewayError
from model.structured import validate_structured


class Answer(BaseModel):
    text: str
    confidence: float


def test_gateway_validates_structured_output():
    gateway = ModelGateway({"fake": lambda _: {"text": "ok", "confidence": 0.9}})
    result = gateway.invoke_structured(provider="fake", request="hi", schema=Answer)
    assert result.text == "ok"


def test_gateway_rejects_malformed_output_without_retry():
    calls = []

    def provider(_):
        calls.append(1)
        return {"text": "bad"}

    gateway = ModelGateway({"fake": provider}, max_retries=3)
    with pytest.raises(ModelGatewayError, match="schema validation"):
        gateway.invoke_structured(provider="fake", request="hi", schema=Answer)
    assert len(calls) == 1


def test_structured_validator_rejects_non_schema():
    with pytest.raises(TypeError):
        validate_structured({}, cast(type[BaseModel], dict))
