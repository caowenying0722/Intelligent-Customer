"""Small, deterministic redaction helpers for logs and audit metadata."""

from __future__ import annotations

import re
from hashlib import sha256

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_API_KEY = re.compile(r"\b(?:sk|key|token)[-_][A-Za-z0-9._=-]{12,}\b", re.IGNORECASE)


def redact_text(value: str, *, max_length: int = 512) -> str:
    """Redact common PII/credential forms and cap output length."""

    if max_length < 1:
        raise ValueError("max_length must be positive")
    redacted = _EMAIL.sub("<redacted-email>", value)
    redacted = _PHONE.sub("<redacted-phone>", redacted)
    redacted = _BEARER.sub(r"\1 <redacted-token>", redacted)
    redacted = _API_KEY.sub("<redacted-secret>", redacted)
    if len(redacted) <= max_length:
        return redacted
    return redacted[: max_length - 14] + "...<truncated>"


def text_metadata(value: str) -> dict[str, int | str]:
    """Return safe length/fingerprint metadata without retaining text content."""

    return {
        "length": len(value),
        "fingerprint": sha256(value.encode("utf-8")).hexdigest()[:16],
    }
