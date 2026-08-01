"""Stable model error taxonomy independent of provider SDKs."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ModelErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONTENT_BLOCKED = "content_blocked"
    MALFORMED_OUTPUT = "malformed_output"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class ModelError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ModelErrorCode
    message: str
    retryable: bool = False
    provider: str | None = None
