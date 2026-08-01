import pytest

from model.idempotency import IdempotencyConflictError
from model.redis_idempotency import IdempotencyUnavailableError, RedisIdempotencyStore


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value


def test_redis_idempotency_round_trip_and_conflict():
    store = RedisIdempotencyStore(FakeRedis(), namespace="test", ttl_seconds=10)
    store.set(tenant_id="a", key="k", fingerprint="f", result={"ok": True})
    assert store.get(tenant_id="a", key="k", fingerprint="f") == {"ok": True}
    with pytest.raises(IdempotencyConflictError):
        store.get(tenant_id="a", key="k", fingerprint="other")


def test_redis_idempotency_fails_closed_when_backend_down():
    class Down:
        def get(self, _):
            raise RuntimeError("down")

        def setex(self, *_):
            raise RuntimeError("down")

    store = RedisIdempotencyStore(Down())
    with pytest.raises(IdempotencyUnavailableError):
        store.get(tenant_id="a", key="k", fingerprint="f")
