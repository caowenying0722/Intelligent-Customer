"""Fail-open Redis-compatible cache adapter for model responses."""

from __future__ import annotations

import json
import hashlib
from typing import Any, Callable


class RedisCacheAdapter:
    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "model-cache",
        ttl_seconds: int = 60,
        serializer: Callable[[Any], str] | None = None,
        deserializer: Callable[[str], Any] | None = None,
    ) -> None:
        if not namespace.strip() or ttl_seconds < 1:
            raise ValueError("namespace and ttl_seconds must be valid")
        self.client = client
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self._serialize = serializer or (lambda value: json.dumps(value, ensure_ascii=False))
        self._deserialize = deserializer or json.loads
        self._hits = 0
        self._misses = 0

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    @staticmethod
    def key(*, tenant_id: str, model: str, prompt: str, prompt_version: str = "v1") -> str:
        if not tenant_id.strip() or not model.strip():
            raise ValueError("tenant_id and model must not be empty")
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return f"{tenant_id}:{model}:{prompt_version}:{digest}"

    def get(self, key: str) -> Any | None:
        try:
            raw = self.client.get(self._key(key))
            if raw is None:
                self._misses += 1
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            self._hits += 1
            return self._deserialize(raw)
        except Exception:
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> bool:
        try:
            payload = self._serialize(value)
            self.client.setex(self._key(key), self.ttl_seconds, payload)
            return True
        except Exception:
            return False

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}
