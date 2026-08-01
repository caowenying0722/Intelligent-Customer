"""Privacy-preserving structured HTTP access events."""

from __future__ import annotations

import json
import logging
import re
from typing import Final

_LOGGER: Final = logging.getLogger("api.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _safe_identifier(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if _SAFE_ID.fullmatch(text) else "invalid"


def log_http_request(
    *,
    method: str,
    status_code: int,
    duration_ms: float,
    request_id: object | None,
    trace_id: object | None,
) -> None:
    """Emit only bounded request metadata; never include headers or payloads."""
    event = {
        "event": "http.request",
        "method": method.upper()[:16],
        "status_code": int(status_code),
        "duration_ms": round(max(0.0, duration_ms), 3),
        "request_id": _safe_identifier(request_id),
        "trace_id": _safe_identifier(trace_id),
    }
    _LOGGER.info(json.dumps(event, ensure_ascii=False, sort_keys=True))
