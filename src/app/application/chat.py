"""Chat orchestration boundary with an injectable agent and deadline."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class ChatAgent(Protocol):
    def run(self, message: str) -> str: ...


class ChatApplicationError(RuntimeError):
    """Safe application-level error that can be mapped to a stable API code."""


class ChatApplicationService:
    def __init__(
        self,
        agent: ChatAgent,
        *,
        timeout_seconds: float = 30.0,
        run_in_thread: Callable[[ChatAgent, str], Awaitable[str]] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.agent = agent
        self.timeout_seconds = timeout_seconds
        self._run_in_thread = run_in_thread

    async def chat(self, message: str) -> str:
        try:
            if self._run_in_thread is not None:
                result = self._run_in_thread(self.agent, message)
            else:
                result = asyncio.to_thread(self.agent.run, message)
            return await asyncio.wait_for(result, timeout=self.timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ChatApplicationError("chat execution timed out") from exc
        except Exception as exc:  # noqa: BLE001 - map provider details to safe error.
            raise ChatApplicationError("chat execution failed") from exc
