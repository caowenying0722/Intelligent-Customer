from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from agent.tools.middleware import monitor_tool, monitor_tool_async
from utils.logger_handler import logger


@tool
def lookup_secret(secret: str) -> str:
    """Return a deterministic test value."""

    return f"ok:{secret}"


def _node() -> ToolNode:
    return ToolNode(
        [lookup_secret],
        wrap_tool_call=monitor_tool.wrap_tool_call,
        awrap_tool_call=monitor_tool_async.awrap_tool_call,
    )


def _input() -> dict[str, list[AIMessage]]:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_secret",
                        "args": {"secret": "do-not-log"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }


def test_sync_tool_middleware_logs_metadata_only() -> None:
    with patch.object(logger, "info") as info:
        result = _node().invoke(
            _input(), config={"configurable": {"__pregel_runtime": Runtime()}}
        )

    assert result["messages"][0].content == "ok:do-not-log"
    logged = " ".join(str(call) for call in info.call_args_list)
    assert "do-not-log" not in logged
    assert "lookup_secret" in logged


@pytest.mark.asyncio
async def test_async_tool_middleware_logs_metadata_only() -> None:
    with patch.object(logger, "info") as info:
        result = await _node().ainvoke(
            _input(), config={"configurable": {"__pregel_runtime": Runtime()}}
        )

    assert result["messages"][0].content == "ok:do-not-log"
    logged = " ".join(str(call) for call in info.call_args_list)
    assert "do-not-log" not in logged
    assert "lookup_secret" in logged
