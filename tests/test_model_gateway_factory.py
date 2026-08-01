from model.factory import build_chat_gateway
from model.runtime_config import ModelRuntimeConfig
from utils.settings import Settings


class FakeModel:
    def invoke(self, request):
        return {"echo": request}


def test_factory_adapts_explicit_model_without_loading_provider():
    gateway = build_chat_gateway(
        FakeModel(), provider="fake",
        runtime=ModelRuntimeConfig(request_timeout_seconds=0.1, max_retries=0),
    )
    assert gateway.invoke(provider="fake", request="hello") == {"echo": "hello"}


def test_factory_injects_configured_memory_cache():
    gateway = build_chat_gateway(
        FakeModel(), provider="fake",
        settings=Settings.model_validate({"model_cache_max_entries": 2}),
    )
    assert gateway.cache is not None
    assert gateway.invoke_cached(
        provider="fake", model="m", tenant_id="t", prompt="p", request="p"
    ) == {"echo": "p"}


def test_factory_injects_configured_tenant_quota():
    gateway = build_chat_gateway(
        FakeModel(), provider="fake",
        settings=Settings.model_validate({"model_quota_max_calls": 1}),
    )
    assert gateway.quota is not None
