"""Dependency-free W3C trace-context propagation for the API boundary."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


def _non_zero(value: str) -> bool:
    return any(character != "0" for character in value)


@dataclass(frozen=True)
class TraceContext:
    """A validated trace id and fresh server span id."""

    trace_id: str
    span_id: str
    trace_flags: str = "01"
    parent_span_id: str | None = None

    @classmethod
    def from_traceparent(cls, header: str | None) -> TraceContext:
        if header is None:
            return cls(trace_id=secrets.token_hex(16), span_id=secrets.token_hex(8))
        match = _TRACEPARENT.fullmatch(header.strip())
        if (
            match is None
            or match.group("version") == "ff"
            or not _non_zero(match.group("trace_id"))
            or not _non_zero(match.group("span_id"))
        ):
            return cls(trace_id=secrets.token_hex(16), span_id=secrets.token_hex(8))
        return cls(
            trace_id=match.group("trace_id"),
            span_id=secrets.token_hex(8),
            trace_flags=match.group("flags"),
            parent_span_id=match.group("span_id"),
        )

    @property
    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"
