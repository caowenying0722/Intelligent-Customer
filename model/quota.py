"""Tenant-scoped bounded model call quota."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class TenantQuota:
    @classmethod
    def from_settings(cls, settings):
        if settings.model_quota_max_calls is None:
            return None
        return cls(
            max_calls=settings.model_quota_max_calls,
            window_seconds=settings.model_quota_window_seconds,
        )

    def __init__(self, *, max_calls: int, window_seconds: float = 60.0) -> None:
        if max_calls < 1 or window_seconds <= 0:
            raise ValueError("quota limits must be positive")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(self, tenant_id: str) -> bool:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        now = time.monotonic()
        with self._lock:
            calls = self._calls[tenant_id]
            while calls and now - calls[0] >= self.window_seconds:
                calls.popleft()
            if len(calls) >= self.max_calls:
                return False
            calls.append(now)
            return True

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"tenants": len(self._calls), "max_calls": self.max_calls}
