"""Deterministic allowlist, argument, and approval checks for Agent tools."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool


class ToolPolicyError(ValueError):
    """Raised when a tool call is not permitted by deterministic policy."""


ApprovalChecker = Callable[[str, Mapping[str, Any]], bool]


@dataclass(frozen=True)
class ToolPolicy:
    """Allow only declared tools and require explicit approval for high-risk ones."""

    allowed_tools: frozenset[str]
    high_risk_tools: frozenset[str] = frozenset()
    approval_checker: ApprovalChecker | None = None
    max_args_bytes: int = 4096

    def __post_init__(self) -> None:
        if not self.allowed_tools:
            return
        if not self.high_risk_tools.issubset(self.allowed_tools):
            raise ValueError("high-risk tools must be included in the allowlist")
        if self.max_args_bytes < 1:
            raise ValueError("max_args_bytes must be positive")

    @classmethod
    def for_tools(cls, tools: Sequence[BaseTool]) -> ToolPolicy:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        return cls(allowed_tools=frozenset(names))

    def check(self, name: str, args: Mapping[str, Any]) -> None:
        if name not in self.allowed_tools:
            raise ToolPolicyError("tool is not allowlisted")
        if not isinstance(args, Mapping):
            raise ToolPolicyError("tool arguments must be an object")
        try:
            encoded = json.dumps(
                dict(args), ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolPolicyError("tool arguments are not serializable") from exc
        if len(encoded) > self.max_args_bytes:
            raise ToolPolicyError("tool arguments exceed the size limit")
        if name in self.high_risk_tools:
            if self.approval_checker is None:
                raise ToolPolicyError("high-risk tool requires approval")
            try:
                approved = self.approval_checker(name, args)
            except Exception as exc:  # noqa: BLE001 - approval failures deny access.
                raise ToolPolicyError("tool approval is unavailable") from exc
            if not approved:
                raise ToolPolicyError("high-risk tool approval denied")

    def guard(self, tools: Sequence[BaseTool]) -> list[BaseTool]:
        """Return schema-preserving wrappers that enforce policy before execution."""

        guarded: list[BaseTool] = []
        for tool in tools:
            if tool.name not in self.allowed_tools:
                raise ToolPolicyError("tool is not allowlisted")

            def call(*, _tool: BaseTool = tool, **kwargs: Any) -> Any:
                self.check(_tool.name, kwargs)
                return _tool.invoke(kwargs)

            async def acall(*, _tool: BaseTool = tool, **kwargs: Any) -> Any:
                self.check(_tool.name, kwargs)
                return await _tool.ainvoke(kwargs)

            guarded.append(
                StructuredTool.from_function(
                    func=call,
                    coroutine=acall,
                    name=tool.name,
                    description=tool.description or "",
                    args_schema=tool.args_schema,
                    return_direct=tool.return_direct,
                    response_format=tool.response_format,
                )
            )
        return guarded


def safe_argument_summary(args: object) -> dict[str, object]:
    """Return metadata only; never place tool argument values in logs."""

    if not isinstance(args, Mapping):
        return {"type": type(args).__name__}
    return {
        "keys": sorted(str(key) for key in args),
        "value_types": sorted({type(value).__name__ for value in args.values()}),
    }
