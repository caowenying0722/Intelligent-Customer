"""Structured security audit events with privacy-preserving actor identity."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from typing import Protocol


@dataclass(frozen=True)
class SecurityAuditEvent:
    """A bounded, non-sensitive security event suitable for structured logging."""

    event_type: str
    outcome: str
    request_id: str | None = None
    tenant_id: str | None = None
    subject_hash: str | None = None
    roles: tuple[str, ...] = ()
    reason: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "outcome": self.outcome,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "subject_hash": self.subject_hash,
            "roles": list(self.roles),
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


class AuditSink(Protocol):
    def record(self, event: SecurityAuditEvent) -> None:
        """Persist or forward one already-sanitized event."""


class LoggingAuditSink:
    """Emit sanitized events through the standard logging pipeline."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("security.audit")

    def record(self, event: SecurityAuditEvent) -> None:
        self._logger.info(
            "security_audit %s",
            json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True),
        )


class InMemoryAuditSink:
    """Bounded sink for tests and local diagnostics; never grows without limit."""

    def __init__(self, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._events: deque[SecurityAuditEvent] = deque(maxlen=max_events)

    def record(self, event: SecurityAuditEvent) -> None:
        self._events.append(event)

    def snapshot(self) -> tuple[SecurityAuditEvent, ...]:
        return tuple(self._events)


def actor_hash(subject: str | None) -> str | None:
    """Return a stable short hash instead of storing a potentially identifying subject."""

    if not subject:
        return None
    return sha256(subject.encode("utf-8")).hexdigest()[:16]


def record_safely(sink: AuditSink, event: SecurityAuditEvent) -> None:
    """Keep an audit backend outage from turning a request into an auth bypass."""

    try:
        sink.record(event)
    except Exception:  # noqa: BLE001 - audit failure must not alter auth semantics.
        logging.getLogger("security.audit").warning(
            "security audit sink unavailable; event was not persisted"
        )
