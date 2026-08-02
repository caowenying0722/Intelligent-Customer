"""Cooperative deadline and cancellation boundary for synchronous Agent work."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from typing import Any


class ExecutionCancelled(RuntimeError):
    pass


class ExecutionDeadlineExceeded(TimeoutError):
    pass


@dataclass
class ExecutionGuard:
    deadline: float
    cancelled: Event = field(default_factory=Event)

    @classmethod
    def after(cls, timeout_seconds: float) -> ExecutionGuard:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return cls(deadline=monotonic() + timeout_seconds)

    def cancel(self) -> None:
        self.cancelled.set()

    def check(self) -> None:
        if self.cancelled.is_set():
            raise ExecutionCancelled("execution cancelled")
        if monotonic() >= self.deadline:
            raise ExecutionDeadlineExceeded("execution deadline exceeded")


_CURRENT_EXECUTION_GUARD: ContextVar[ExecutionGuard | None] = ContextVar(
    "current_execution_guard", default=None
)


def set_execution_guard(guard: ExecutionGuard) -> Token[ExecutionGuard | None]:
    return _CURRENT_EXECUTION_GUARD.set(guard)


def reset_execution_guard(token: Token[ExecutionGuard | None]) -> None:
    _CURRENT_EXECUTION_GUARD.reset(token)


def check_execution_guard() -> None:
    guard = _CURRENT_EXECUTION_GUARD.get()
    if guard is not None:
        guard.check()


def run_with_execution_guard(
    guard: ExecutionGuard, operation: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    token = set_execution_guard(guard)
    try:
        guard.check()
        return operation(*args, **kwargs)
    finally:
        reset_execution_guard(token)
