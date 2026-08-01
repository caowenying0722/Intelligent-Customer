"""Chat orchestration boundary with an injectable agent and deadline."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import Any, Protocol
from uuid import UUID

from model.errors import ModelError
from model.gateway import ModelGateway, ModelGatewayError
from src.app.domain.conversations import (
    ConcurrencyConflict,
    ConversationRepository,
    ConversationRepositoryProtocol,
)


def _null_span():
    return nullcontext(None)


class ChatAgent(Protocol):
    def run(self, message: str) -> str: ...

    def stream(self, message: str) -> list[str]: ...


class ChatApplicationError(RuntimeError):
    """Safe application-level error that can be mapped to a stable API code."""

    def __init__(self, message: str, *, model_error: ModelError | None = None):
        super().__init__(message)
        self.model_error = model_error


class ChatApplicationService:
    def __init__(
        self,
        agent: ChatAgent,
        *,
        timeout_seconds: float = 30.0,
        run_in_thread: Callable[[ChatAgent, str], Awaitable[str]] | None = None,
        async_runner: Callable[[ChatAgent, str], Awaitable[str]] | None = None,
        async_stream_runner: Callable[[ChatAgent, str], Awaitable[list[str]]]
        | None = None,
        conversation_repository: ConversationRepositoryProtocol | None = None,
        model_gateway: ModelGateway | None = None,
        model_provider: str = "default",
        stream_gateway: ModelGateway | None = None,
        model_name: str = "default",
        prompt_version: str = "v1",
        tracer: Any | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.agent = agent
        self.timeout_seconds = timeout_seconds
        self._run_in_thread = run_in_thread
        self._async_runner = async_runner
        self._async_stream_runner = async_stream_runner
        self.conversation_repository = (
            conversation_repository or ConversationRepository()
        )
        self.model_gateway = model_gateway
        self.model_provider = model_provider
        self.stream_gateway = stream_gateway
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.tracer = tracer

    def _conversation_id(
        self, tenant_id: str, conversation_id: str | None, user_id: str
    ) -> UUID:
        if conversation_id is None:
            return self.conversation_repository.create(
                tenant_id, user_id
            ).conversation_id
        try:
            parsed = UUID(conversation_id)
        except ValueError as exc:
            raise ChatApplicationError("invalid conversation_id") from exc
        if self.conversation_repository.get(tenant_id, parsed) is None:
            raise ChatApplicationError("conversation not found")
        return parsed

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
        tenant_id: str = "local",
        user_id: str = "local",
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[str, UUID, UUID]:
        resolved_id = self._conversation_id(tenant_id, conversation_id, user_id)
        run = self.conversation_repository.create_run(
            tenant_id, resolved_id, idempotency_key
        )
        self.conversation_repository.update_run(tenant_id, run.run_id, "running")
        try:
            self.conversation_repository.append(
                tenant_id,
                resolved_id,
                "user",
                message,
                expected_version=expected_version,
            )
            if self._async_runner is not None:
                result = self._async_runner(self.agent, message)
            elif self._run_in_thread is not None:
                result = self._run_in_thread(self.agent, message)
            else:
                if self.model_gateway is not None:
                    if self.model_gateway.cache is not None:
                        result = asyncio.to_thread(
                            self.model_gateway.invoke_cached,
                            provider=self.model_provider,
                            model=self.model_name,
                            tenant_id=tenant_id,
                            prompt=message,
                            prompt_version=self.prompt_version,
                            request=message,
                        )
                    else:
                        result = asyncio.to_thread(
                            self.model_gateway.invoke,
                            provider=self.model_provider,
                            request=message,
                        )
                else:
                    result = asyncio.to_thread(self.agent.run, message)
            span_context = (
                self.tracer.start_span("agent.run")
                if self.tracer is not None
                else _null_span()
            )
            with span_context as span:
                answer = await asyncio.wait_for(result, timeout=self.timeout_seconds)
                if span is not None:
                    span.set_attribute("agent.status", "completed")
            self.conversation_repository.append(
                tenant_id, resolved_id, "assistant", answer
            )
            self.conversation_repository.update_run(tenant_id, run.run_id, "completed")
            return answer, resolved_id, run.run_id
        except ConcurrencyConflict:
            self.conversation_repository.update_run(
                tenant_id, run.run_id, "failed", "conversation conflict"
            )
            raise
        except asyncio.CancelledError:
            self.conversation_repository.update_run(tenant_id, run.run_id, "cancelled")
            raise
        except (TimeoutError, asyncio.TimeoutError) as exc:
            self.conversation_repository.update_run(
                tenant_id, run.run_id, "failed", str(exc)
            )
            raise ChatApplicationError("chat execution timed out") from exc
        except Exception as exc:  # noqa: BLE001 - map provider details to safe error.
            self.conversation_repository.update_run(
                tenant_id, run.run_id, "failed", str(exc)
            )
            model_error = (
                exc.to_contract() if isinstance(exc, ModelGatewayError) else None
            )
            raise ChatApplicationError(
                "chat execution failed", model_error=model_error
            ) from exc

    async def stream(self, message: str) -> list[str]:
        """Return bounded fake/provider chunks for the transport SSE adapter."""
        try:
            if self._async_stream_runner is not None:
                chunks = await asyncio.wait_for(
                    self._async_stream_runner(self.agent, message),
                    timeout=self.timeout_seconds,
                )
            elif self.stream_gateway is not None:
                chunks = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.stream_gateway.invoke,
                        provider=self.model_provider,
                        request=message,
                    ),
                    timeout=self.timeout_seconds,
                )
                if isinstance(chunks, str):
                    chunks = [chunks]
            else:
                chunks = await asyncio.wait_for(
                    asyncio.to_thread(self.agent.stream, message),
                    timeout=self.timeout_seconds,
                )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise ChatApplicationError("chat execution timed out") from exc
        except Exception as exc:  # noqa: BLE001 - map provider details to safe error.
            model_error = (
                exc.to_contract() if isinstance(exc, ModelGatewayError) else None
            )
            raise ChatApplicationError(
                "chat execution failed", model_error=model_error
            ) from exc
        return chunks
