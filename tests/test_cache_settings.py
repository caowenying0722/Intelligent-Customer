from model.cache import ModelCache
from model.redis_cache import RedisCacheAdapter
from utils.settings import Settings


class Client:
    def get(self, _):
        return None

    def setex(self, *_):
        return None


def test_cache_adapters_use_settings():
    settings = Settings.model_validate(
        {
            "model_cache_max_entries": 10,
            "model_cache_ttl_seconds": 12,
            "model_cache_max_entries_per_tenant": 2,
            "model_cache_namespace": "tenant-models",
        }
    )
    memory = ModelCache.from_settings(settings)
    redis = RedisCacheAdapter.from_settings(Client(), settings)
    assert memory.max_entries == 10
    assert memory.max_entries_per_tenant == 2
    assert redis.namespace == "tenant-models"
    assert redis.ttl_seconds == 12
