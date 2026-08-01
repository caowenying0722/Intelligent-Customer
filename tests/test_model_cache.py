import time

import pytest

from model.cache import ModelCache


def test_cache_is_tenant_and_prompt_version_scoped():
    cache = ModelCache(ttl_seconds=1)
    first = cache.key(tenant_id="a", model="m", prompt="hello", prompt_version="v1")
    other = cache.key(tenant_id="b", model="m", prompt="hello", prompt_version="v1")
    version = cache.key(tenant_id="a", model="m", prompt="hello", prompt_version="v2")
    cache.set(first, "answer")
    assert cache.get(first) == "answer"
    assert cache.get(other) is None
    assert cache.get(version) is None


def test_cache_expires_and_evicts_oldest():
    cache = ModelCache(max_entries=1, ttl_seconds=0.01)
    cache.set("one", 1)
    cache.set("two", 2)
    assert cache.get("one") is None
    assert cache.get("two") == 2
    time.sleep(0.02)
    assert cache.get("two") is None
    assert cache.stats()["hits"] == 1


@pytest.mark.parametrize("kwargs", [{"max_entries": 0}, {"ttl_seconds": 0}])
def test_cache_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ModelCache(**kwargs)
