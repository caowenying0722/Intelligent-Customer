"""Bounded, tenant-scoped model response cache with safe degradation."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any


class ModelCache:
    def __init__(
        self,
        *,
        max_entries: int = 1024,
        ttl_seconds: float = 60.0,
        max_entries_per_tenant: int | None = None,
    ) -> None:
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("cache limits must be positive")
        if max_entries_per_tenant is not None and max_entries_per_tenant < 1:
            raise ValueError("max_entries_per_tenant must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.max_entries_per_tenant = max_entries_per_tenant
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def key(*, tenant_id: str, model: str, prompt: str, prompt_version: str = "v1") -> str:
        if not tenant_id.strip() or not model.strip():
            raise ValueError("tenant_id and model must not be empty")
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return f"{tenant_id}:{model}:{prompt_version}:{digest}"

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self._misses += 1
                return None
            expires, value = item
            if expires <= now:
                self._items.pop(key, None)
                self._misses += 1
                return None
            self._items.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            if self.max_entries_per_tenant is not None:
                tenant = key.split(":", 1)[0]
                tenant_keys = [item_key for item_key in self._items if item_key.split(":", 1)[0] == tenant]
                while len(tenant_keys) > self.max_entries_per_tenant:
                    oldest = tenant_keys.pop(0)
                    self._items.pop(oldest, None)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._items),
                "hits": self._hits,
                "misses": self._misses,
                "max_entries_per_tenant": self.max_entries_per_tenant or 0,
            }
