from __future__ import annotations

import asyncio

from src.app.application.chat import ChatApplicationService


class ThreadAwareAgent:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str, str]] = []
        self.stream_calls: list[tuple[str, str]] = []

    def run(self, _message: str) -> str:
        raise AssertionError("durable conversations must use run_in_thread")

    def stream(self, _message: str) -> list[str]:
        raise AssertionError("durable conversations must use stream_in_thread")

    def run_in_thread(self, message: str, thread_id: str) -> str:
        self.run_calls.append((message, thread_id))
        return f"answer:{message}"

    def stream_in_thread(self, message: str, thread_id: str) -> list[str]:
        self.stream_calls.append((message, thread_id))
        return [f"answer:{message}"]


def test_chat_routes_same_conversation_to_stable_tenant_scoped_thread() -> None:
    agent = ThreadAwareAgent()
    service = ChatApplicationService(agent)

    async def exercise() -> None:
        _, conversation_id, _ = await service.chat("one", tenant_id="tenant-a")
        await service.chat(
            "two", conversation_id=str(conversation_id), tenant_id="tenant-a"
        )
        await service.stream(
            "three", conversation_id=str(conversation_id), tenant_id="tenant-a"
        )

    asyncio.run(exercise())

    thread_ids = [thread_id for _, thread_id in agent.run_calls]
    assert len(set(thread_ids)) == 1
    assert agent.stream_calls[0][1] == thread_ids[0]
    assert "tenant-a" not in thread_ids[0]
    assert len(thread_ids[0]) == 64


def test_checkpoint_thread_id_is_tenant_scoped() -> None:
    agent = ThreadAwareAgent()
    service = ChatApplicationService(agent)

    async def exercise() -> None:
        await service.chat("a", tenant_id="tenant-a")
        await service.chat("b", tenant_id="tenant-b")

    asyncio.run(exercise())

    assert agent.run_calls[0][1] != agent.run_calls[1][1]
