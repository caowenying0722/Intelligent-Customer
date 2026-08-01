from model.factory import build_chat_gateway
from model.runtime_config import ModelRuntimeConfig


class FakeModel:
    def invoke(self, request):
        return {"echo": request}


def test_factory_adapts_explicit_model_without_loading_provider():
    gateway = build_chat_gateway(
        FakeModel(), provider="fake",
        runtime=ModelRuntimeConfig(request_timeout_seconds=0.1, max_retries=0),
    )
    assert gateway.invoke(provider="fake", request="hello") == {"echo": "hello"}
