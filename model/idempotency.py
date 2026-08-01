"""Bounded in-process idempotency records for model requests."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class IdempotencyConflictError(RuntimeError):
    """The same key was reused with a different request fingerprint."""


@dataclass(frozen=True)
class IdempotencyRecord:
    fingerprint: str
    result: object
    expires_at: float


class IdempotencyStore:
    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.Lock] = {}

    def get_or_compute(
        self, *, tenant_id: str, key: str, fingerprint: str, producer
    ) -> object:
        identity = (tenant_id, key)
        with self._lock:
            lock = self._key_locks.setdefault(identity, threading.Lock())
        with lock:
            cached = self.get(tenant_id=tenant_id, key=key, fingerprint=fingerprint)
            if cached is not None:
                return cached
            return self.set(
                tenant_id=tenant_id, key=key, fingerprint=fingerprint, result=producer()
            )

    def get_or_set(
        self, *, tenant_id: str, key: str, fingerprint: str, result: object
    ) -> object:
        now = time.monotonic()
        identity = (tenant_id, key)
        with self._lock:
            current = self._records.get(identity)
            if current is not None and current.expires_at > now:
                if current.fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "idempotency key reused with different request"
                    )
                return current.result
            self._records[identity] = IdempotencyRecord(
                fingerprint, result, now + self.ttl_seconds
            )
            return result

    def get(self, *, tenant_id: str, key: str, fingerprint: str) -> object | None:
        now = time.monotonic()
        with self._lock:
            current = self._records.get((tenant_id, key))
            if current is None or current.expires_at <= now:
                return None
            if current.fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "idempotency key reused with different request"
                )
            return current.result

    def set(
        self, *, tenant_id: str, key: str, fingerprint: str, result: object
    ) -> object:
        with self._lock:
            self._records[(tenant_id, key)] = IdempotencyRecord(
                fingerprint, result, time.monotonic() + self.ttl_seconds
            )
            return result
