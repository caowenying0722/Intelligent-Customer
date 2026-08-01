"""Redis-compatible cross-process idempotency record adapter."""

from __future__ import annotations

import json
from typing import Any

from model.idempotency import IdempotencyConflictError


class IdempotencyUnavailableError(RuntimeError):
    """The idempotency backend is unavailable; fail closed."""


class RedisIdempotencyStore:
    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "model-idempotency",
        ttl_seconds: int = 300,
    ):
        if not namespace.strip() or ttl_seconds < 1:
            raise ValueError("namespace and ttl_seconds must be valid")
        self.client = client
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds

    def _key(self, tenant_id: str, key: str) -> str:
        return f"{self.namespace}:{tenant_id}:{key}"

    def get(self, *, tenant_id: str, key: str, fingerprint: str) -> object | None:
        try:
            raw = self.client.get(self._key(tenant_id, key))
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if payload["fingerprint"] != fingerprint:
                raise IdempotencyConflictError(
                    "idempotency key reused with different request"
                )
            return payload["result"]
        except IdempotencyConflictError:
            raise
        except Exception as exc:
            raise IdempotencyUnavailableError(
                "idempotency backend unavailable"
            ) from exc

    def set(
        self, *, tenant_id: str, key: str, fingerprint: str, result: object
    ) -> object:
        try:
            self.client.setex(
                self._key(tenant_id, key),
                self.ttl_seconds,
                json.dumps(
                    {"fingerprint": fingerprint, "result": result}, ensure_ascii=False
                ),
            )
            return result
        except Exception as exc:
            raise IdempotencyUnavailableError(
                "idempotency backend unavailable"
            ) from exc

    def get_or_compute(
        self, *, tenant_id: str, key: str, fingerprint: str, producer
    ) -> object:
        existing = self.get(tenant_id=tenant_id, key=key, fingerprint=fingerprint)
        if existing is not None:
            return existing
        return self.set(
            tenant_id=tenant_id, key=key, fingerprint=fingerprint, result=producer()
        )
