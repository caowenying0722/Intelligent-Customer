from __future__ import annotations

import pytest

from src.app.domain.execution import (
    ExecutionCancelled,
    ExecutionDeadlineExceeded,
    ExecutionGuard,
    check_execution_guard,
    run_with_execution_guard,
)


def test_execution_guard_propagates_context_and_cancellation() -> None:
    guard = ExecutionGuard.after(1)
    calls: list[str] = []

    def operation() -> str:
        check_execution_guard()
        calls.append("called")
        return "ok"

    assert run_with_execution_guard(guard, operation) == "ok"
    guard.cancel()
    with pytest.raises(ExecutionCancelled):
        run_with_execution_guard(guard, operation)
    assert calls == ["called"]


def test_execution_guard_rejects_expired_deadline() -> None:
    guard = ExecutionGuard(deadline=0)

    with pytest.raises(ExecutionDeadlineExceeded):
        run_with_execution_guard(guard, lambda: None)
