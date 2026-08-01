import re

from fastapi.testclient import TestClient

from model.gateway import ModelGateway
from src.app.application.chat import ChatApplicationService
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


def test_api_records_bounded_http_span_summary_without_attributes():
    app = create_app()
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    spans = app.state.trace_exporter.snapshot()
    assert spans
    assert spans[-1]["name"] == "http.request"
    assert len(spans[-1]["trace_id"]) == 32
    assert "http.method" not in spans[-1]
    assert "health/live" not in str(spans[-1])


def test_chat_records_agent_span_with_fake_agent():
    class Agent:
        def run(self, message: str) -> str:
            return "ok"

        def stream(self, message: str) -> list[str]:
            return ["ok"]

    app = create_app(chat_service=ChatApplicationService(Agent()))
    response = TestClient(app).post("/api/v1/chat", json={"message": "secret"})

    assert response.status_code == 200
    names = [span["name"] for span in app.state.trace_exporter.snapshot()]
    assert "agent.run" in names
    assert "secret" not in str(app.state.trace_exporter.snapshot())


def test_chat_records_nested_llm_span_with_fake_gateway():
    class Agent:
        def run(self, message: str) -> str:
            return "unused"

        def stream(self, message: str) -> list[str]:
            return ["unused"]

    gateway = ModelGateway({"fake": lambda request: "answer"})
    service = ChatApplicationService(
        Agent(), model_gateway=gateway, model_provider="fake"
    )
    app = create_app(chat_service=service)
    response = TestClient(app).post("/api/v1/chat", json={"message": "private"})

    assert response.status_code == 200
    spans = app.state.trace_exporter.snapshot()
    names = [span["name"] for span in spans]
    assert "http.request" in names
    assert "agent.run" in names
    assert "llm.generate" in names
    assert "private" not in str(spans)


def test_stream_records_agent_stream_span_without_chunk_content():
    class Agent:
        def run(self, message: str) -> str:
            return "unused"

        def stream(self, message: str) -> list[str]:
            return ["chunk-secret"]

    app = create_app(chat_service=ChatApplicationService(Agent()))
    response = TestClient(app).post(
        "/api/v1/chat/stream", json={"message": "request-secret"}
    )

    assert response.status_code == 200
    spans = app.state.trace_exporter.snapshot()
    assert any(span["name"] == "agent.stream" for span in spans)
    assert "chunk-secret" not in str(spans)
    assert "request-secret" not in str(spans)
