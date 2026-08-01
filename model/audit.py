"""Privacy-preserving request fingerprints and audit trace records."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from model.contracts import ModelRequest


def request_fingerprint(request: ModelRequest) -> str:
    material = "|".join(
        [
            request.tenant_id,
            request.provider,
            request.model,
            request.prompt_version,
            request.prompt,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditTrace:
    request_id: str | None
    request_fingerprint: str
    provider: str
    model: str
    started_at: float


def start_trace(request: ModelRequest) -> AuditTrace:
    return AuditTrace(
        request_id=request.request_id,
        request_fingerprint=request_fingerprint(request),
        provider=request.provider,
        model=request.model,
        started_at=time.time(),
    )
