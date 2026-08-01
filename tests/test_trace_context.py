import re

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.observability.tracing import TraceContext


def test_trace_context_generates_server_child_span():
    incoming = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"

    context = TraceContext.from_traceparent(incoming)

    assert context.trace_id == "a" * 32
    assert context.parent_span_id == "b" * 16
    assert context.span_id != "b" * 16
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", context.traceparent)


def test_invalid_or_zero_traceparent_is_replaced():
    for header in ("bad", "00-" + "0" * 32 + "-" + "1" * 16 + "-01"):
        context = TraceContext.from_traceparent(header)
        assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", context.traceparent)
        assert context.parent_span_id is None


def test_api_propagates_traceparent_without_exposing_request_content():
    incoming = "00-" + "c" * 32 + "-" + "d" * 16 + "-01"
    response = TestClient(create_app()).get(
        "/health/live", headers={"traceparent": incoming}
    )

    assert response.status_code == 200
    output = response.headers["traceparent"]
    assert output.startswith("00-" + "c" * 32 + "-")
    assert output.endswith("-01")
    assert output != incoming
    assert "secret" not in output
