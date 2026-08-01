"""W3C trace-context propagation and bounded API span recording."""

from __future__ import annotations

import re
import secrets
from collections import deque
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    set_span_in_context,
)

_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
_CURRENT_TRACER: ContextVar[ApiTracer | None] = ContextVar(
    "current_api_tracer", default=None
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

    def with_span_id(self, span_id: str) -> TraceContext:
        return TraceContext(
            trace_id=self.trace_id,
            span_id=span_id,
            trace_flags=self.trace_flags,
            parent_span_id=self.parent_span_id,
        )


class BoundedSpanExporter(SpanExporter):
    """Keep safe span summaries for diagnostics without retaining attributes."""

    def __init__(self, max_spans: int = 1024) -> None:
        self._lock = Lock()
        self._spans: deque[dict[str, str]] = deque(maxlen=max_spans)

    def export(self, spans: Any) -> SpanExportResult:
        with self._lock:
            for span in spans:
                self._spans.append(
                    {
                        "name": span.name,
                        "trace_id": f"{span.context.trace_id:032x}",
                        "span_id": f"{span.context.span_id:016x}",
                    }
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def snapshot(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._spans)


class ApiTracer:
    """Create API spans with a local bounded exporter and no network side effect."""

    def __init__(self, max_spans: int = 1024) -> None:
        self.exporter = BoundedSpanExporter(max_spans=max_spans)
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("intelligent-customer-service")

    def start_http_span(self, context: TraceContext):
        parent_span = NonRecordingSpan(
            SpanContext(
                trace_id=int(context.trace_id, 16),
                span_id=int(context.span_id, 16),
                is_remote=True,
                trace_flags=TraceFlags(int(context.trace_flags, 16)),
            )
        )
        return self.tracer.start_as_current_span(
            "http.request", context=set_span_in_context(parent_span)
        )

    def start_span(self, name: str):
        return self.tracer.start_as_current_span(name)

    def close(self) -> None:
        self.provider.shutdown()


def set_current_tracer(tracer: ApiTracer) -> Token[ApiTracer | None]:
    return _CURRENT_TRACER.set(tracer)


def reset_current_tracer(token: Token[ApiTracer | None]) -> None:
    _CURRENT_TRACER.reset(token)


def get_current_tracer() -> ApiTracer | None:
    return _CURRENT_TRACER.get()
