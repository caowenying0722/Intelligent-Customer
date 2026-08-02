from __future__ import annotations

from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from agent.tools.policy import ToolPolicy


class State(TypedDict, total=False):
    value: str
    result: str


def _approval_graph(calls: list[str]):
    @tool
    def mutate(value: str) -> str:
        """Perform a high-risk mutation."""

        calls.append(value)
        return f"changed:{value}"

    guarded = ToolPolicy(
        allowed_tools=frozenset({"mutate"}),
        high_risk_tools=frozenset({"mutate"}),
        interrupt_on_high_risk=True,
    ).guard([mutate])[0]

    def execute(state: State):
        return {"result": guarded.invoke({"value": state["value"]})}

    builder = StateGraph(State)
    builder.add_node("execute", execute)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_high_risk_tool_interrupts_before_side_effect_and_resumes_once() -> None:
    calls: list[str] = []
    graph = _approval_graph(calls)
    config = {"configurable": {"thread_id": "approval-thread"}}

    first = list(graph.stream({"value": "x"}, config, stream_mode="updates"))

    assert calls == []
    payload = first[0]["__interrupt__"][0].value
    assert payload == {
        "type": "tool_approval",
        "tool_name": "mutate",
        "arguments": {"value": "x"},
        "risk_level": "high",
    }

    list(
        graph.stream(
            Command(resume={"approved": True, "approval_id": "approval-1"}),
            config,
            stream_mode="updates",
        )
    )

    assert calls == ["x"]
    assert graph.get_state(config).values["result"] == "changed:x"


def test_rejected_high_risk_tool_never_executes() -> None:
    calls: list[str] = []
    graph = _approval_graph(calls)
    config = {"configurable": {"thread_id": "rejected-thread"}}
    list(graph.stream({"value": "x"}, config, stream_mode="updates"))

    try:
        list(
            graph.stream(
                Command(resume={"approved": False}),
                config,
                stream_mode="updates",
            )
        )
    except Exception as exc:  # noqa: BLE001 - assert the safe policy boundary.
        assert "approval denied" in str(exc)
    else:
        raise AssertionError("rejected approval must stop the tool")

    assert calls == []
