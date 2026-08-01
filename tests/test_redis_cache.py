import pytest

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
