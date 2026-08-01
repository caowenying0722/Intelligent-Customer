"""Chat orchestration boundary with an injectable agent and deadline."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from src.app.domain.conversations import ConversationRepository


class ChatAgent(Protocol):
    def run(self, message: str) -> str: ...

    def stream(self, message: str) -> list[str]: ...


class ChatApplicationError(RuntimeError):
    """Safe application-level error that can be mapped to a stable API code."""


class ChatApplicationService:
    def __init__(
        self,
        agent: ChatAgent,
        *,
        timeout_seconds: float = 30.0,
        run_in_thread: Callable[[ChatAgent, str], Awaitable[str]] | None = None,
        conversation_repository: ConversationRepository | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.agent = agent
        self.timeout_seconds = timeout_seconds
        self._run_in_thread = run_in_thread
        self.conversation_repository = (
            conversation_repository or ConversationRepository()
        )

    def _conversation_id(self, conversation_id: str | None) -> UUID:
        if conversation_id is None:
            return self.conversation_repository.create().conversation_id
        try:
            parsed = UUID(conversation_id)
        except ValueError as exc:
            raise ChatApplicationError("invalid conversation_id") from exc
        if self.conversation_repository.get(parsed) is None:
            raise ChatApplicationError("conversation not found")
        return parsed

    async def chat(
        self, message: str, conversation_id: str | None = None
    ) -> tuple[str, UUID]:
        resolved_id = self._conversation_id(conversation_id)
        self.conversation_repository.append(resolved_id, "user", message)
        try:
            if self._run_in_thread is not None:
                result = self._run_in_thread(self.agent, message)
            else:
                result = asyncio.to_thread(self.agent.run, message)
            answer = await asyncio.wait_for(result, timeout=self.timeout_seconds)
            self.conversation_repository.append(resolved_id, "assistant", answer)
            return answer, resolved_id
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ChatApplicationError("chat execution timed out") from exc
        except Exception as exc:  # noqa: BLE001 - map provider details to safe error.
            raise ChatApplicationError("chat execution failed") from exc

    async def stream(self, message: str) -> list[str]:
        """Return bounded fake/provider chunks for the transport SSE adapter."""
        try:
            chunks = await asyncio.wait_for(
                asyncio.to_thread(self.agent.stream, message),
                timeout=self.timeout_seconds,
            )
            return chunks
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ChatApplicationError("chat execution timed out") from exc
        except Exception as exc:  # noqa: BLE001 - map provider details to safe error.
            raise ChatApplicationError("chat execution failed") from exc
