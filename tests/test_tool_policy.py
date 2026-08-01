from typing import Any

import pytest
from langchain_core.tools import tool

from agent.tools.policy import (
    ToolPolicy,
    ToolPolicyError,
    safe_argument_summary,
)


@tool
def lookup(value: str) -> str:
    """Look up a deterministic test value."""

    return value.upper()


@tool
def mutate(value: str) -> str:
    """Represent a high-risk test operation."""

    return value


def test_allowlist_wrapper_preserves_schema_and_checks_size() -> None:
    policy = ToolPolicy.for_tools([lookup])
    guarded = policy.guard([lookup])[0]

    assert guarded.invoke({"value": "ok"}) == "OK"
    with pytest.raises(ToolPolicyError, match="size limit"):
        ToolPolicy(allowed_tools=frozenset({"lookup"}), max_args_bytes=4).guard(
            [lookup]
        )[0].invoke({"value": "too long"})


def test_high_risk_tool_requires_explicit_approval() -> None:
    denied = ToolPolicy(
        allowed_tools=frozenset({"mutate"}), high_risk_tools=frozenset({"mutate"})
    ).guard([mutate])[0]
    with pytest.raises(ToolPolicyError, match="requires approval"):
        denied.invoke({"value": "x"})

    approved = ToolPolicy(
        allowed_tools=frozenset({"mutate"}),
        high_risk_tools=frozenset({"mutate"}),
        approval_checker=lambda name, args: name == "mutate" and args["value"] == "x",
    ).guard([mutate])[0]
    assert approved.invoke({"value": "x"}) == "x"


def test_tool_monitor_summary_contains_metadata_only() -> None:
    args: dict[str, Any] = {"secret": "do-not-log", "count": 1}

    summary = safe_argument_summary(args)

    assert summary == {"keys": ["count", "secret"], "value_types": ["int", "str"]}
    assert "do-not-log" not in str(summary)
