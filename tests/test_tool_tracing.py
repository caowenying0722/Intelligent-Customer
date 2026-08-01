from agent.tools.agent_tools import get_weather
from src.app.observability.tracing import (
    ApiTracer,
    reset_current_tracer,
    set_current_tracer,
)


def test_tool_span_uses_current_context_without_arguments():
    tracer = ApiTracer(max_spans=8)
    token = set_current_tracer(tracer)
    try:
        result = get_weather.invoke({"city": "secret-city"})
    finally:
        reset_current_tracer(token)

    assert "secret-city" in result
    spans = tracer.exporter.snapshot()
    assert any(span["name"] == "tool.get_weather" for span in spans)
    assert "secret-city" not in str(spans)
    tracer.close()
