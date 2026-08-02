from __future__ import annotations

from typing import cast
from unittest.mock import Mock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.react_agent import ReactAgent
from agent.tools.policy import ToolPolicy, ToolPolicyError
from src.app.domain.approvals import ApprovalRequired
from utils.settings import Settings


def test_react_agent_checkpoint_interrupt_and_resume_executes_tool_once() -> None:
    calls: list[str] = []

    @tool
    def mutate(value: str) -> str:
        """Perform a high-risk mutation."""

        calls.append(value)
        return f"changed:{value}"

    class BoundModel:
        def invoke(self, messages):
            if any(isinstance(message, ToolMessage) for message in messages):
                return AIMessage(content="done")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "mutate",
                        "args": {"value": "x"},
                        "id": "call-1",
                    }
                ],
            )

    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = BoundModel()
    policy = ToolPolicy(
        allowed_tools=frozenset({"mutate"}),
        high_risk_tools=frozenset({"mutate"}),
        interrupt_on_high_risk=True,
    )
    with patch("agent.react_agent.load_system_prompts", return_value="prompt"):
        agent = ReactAgent(
            model=cast(BaseChatModel, model),
            tools=[mutate],
            settings=Settings.model_validate({"agent_max_steps": 8}),
            tool_policy=policy,
            checkpointer=InMemorySaver(),
        )

    with pytest.raises(ApprovalRequired) as caught:
        agent.run_in_thread("change", "thread-1")

    assert caught.value.tool_name == "mutate"
    assert caught.value.arguments == {"value": "x"}
    assert calls == []

    answer = agent.resume_in_thread("thread-1", approved=True, approval_id="approval-1")

    assert calls == ["x"]
    assert answer.endswith("done")


def test_react_agent_rejected_resume_never_executes_tool() -> None:
    calls: list[str] = []

    @tool
    def mutate(value: str) -> str:
        """Perform a high-risk mutation."""

        calls.append(value)
        return value

    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value.invoke.return_value = AIMessage(
        content="",
        tool_calls=[{"name": "mutate", "args": {"value": "x"}, "id": "call-1"}],
    )
    with patch("agent.react_agent.load_system_prompts", return_value="prompt"):
        agent = ReactAgent(
            model=cast(BaseChatModel, model),
            tools=[mutate],
            tool_policy=ToolPolicy(
                allowed_tools=frozenset({"mutate"}),
                high_risk_tools=frozenset({"mutate"}),
                interrupt_on_high_risk=True,
            ),
            checkpointer=InMemorySaver(),
        )
    with pytest.raises(ApprovalRequired):
        agent.run_in_thread("change", "thread-rejected")

    with pytest.raises(ToolPolicyError, match="approval denied"):
        agent.resume_in_thread(
            "thread-rejected", approved=False, approval_id="approval-2"
        )

    assert calls == []
