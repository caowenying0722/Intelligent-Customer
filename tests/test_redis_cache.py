import pytest

from model.gateway import ModelGateway
from model.redis_cache import RedisCacheAdapter


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.calls.append(("setex", key, ttl))
        self.values[key] = value


def test_redis_cache_namespaces_and_serializes_with_ttl():
    client = FakeRedis()
    cache = RedisCacheAdapter(client, namespace="test", ttl_seconds=12)
    assert cache.set("k", {"answer": "ok"}) is True
    assert cache.get("k") == {"answer": "ok"}
    assert client.calls == [("setex", "test:k", 12), ("get", "test:k")]


def test_redis_errors_fail_open_as_misses():
    class Broken:
        def get(self, _):
            raise RuntimeError("down")

        def setex(self, *_):
            raise RuntimeError("down")

    cache = RedisCacheAdapter(Broken())
    assert cache.get("k") is None
    assert cache.set("k", "value") is False
    assert cache.stats() == {"hits": 0, "misses": 1}


@pytest.mark.parametrize("kwargs", [{"namespace": ""}, {"ttl_seconds": 0}])
def test_redis_cache_validates_configuration(kwargs):
    with pytest.raises(ValueError):
        RedisCacheAdapter(FakeRedis(), **kwargs)


def test_gateway_uses_redis_cache_and_falls_back_when_redis_is_down():
    client = FakeRedis()
    calls = []
    gateway = ModelGateway(
        {"fake": lambda request: calls.append(request) or "ok"},
        cache=RedisCacheAdapter(client, namespace="gateway"),
    )
    kwargs = dict(
        provider="fake",
        model="m",
        tenant_id="tenant-a",
        prompt="hello",
        request="hello",
    )
    assert gateway.invoke_cached(**kwargs) == "ok"
    assert gateway.invoke_cached(**kwargs) == "ok"
    assert calls == ["hello"]

    class Down:
        def get(self, _):
            raise RuntimeError("redis unavailable")

        def setex(self, *_):
            raise RuntimeError("redis unavailable")

    degraded = ModelGateway(
        {"fake": lambda request: calls.append(request) or "degraded"},
        cache=RedisCacheAdapter(Down()),
    )
    assert degraded.invoke_cached(**kwargs) == "degraded"
    assert calls[-1] == "hello"
