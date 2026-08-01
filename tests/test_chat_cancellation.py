import asyncio
import threading

import pytest

from src.app.application.chat import ChatApplicationError, ChatApplicationService


class Agent:
    def run(self, _message: str) -> str:
        return "ok"

    def stream(self, _message: str) -> list[str]:
        return ["ok"]


def test_sync_agent_timeout_marks_request_failed_without_waiting_for_thread() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingAgent(Agent):
        def run(self, _message: str) -> str:
            started.set()
            release.wait(1)
            finished.set()
            return "late"

    service = ChatApplicationService(BlockingAgent(), timeout_seconds=0.01)

    async def exercise() -> None:
        with pytest.raises(ChatApplicationError, match="timed out"):
            await service.chat("slow")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(exercise())
        assert started.wait(1)
        assert not finished.is_set()
        release.set()
        loop.run_until_complete(asyncio.sleep(0.01))
        assert finished.is_set()
    finally:
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


def test_async_stream_cancellation_propagates_to_runner() -> None:
    cancelled = asyncio.Event()

    async def blocking_runner(_agent: object, _message: str) -> list[str]:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ["never"]

    async def exercise() -> None:
        service = ChatApplicationService(Agent(), async_stream_runner=blocking_runner)
        task = asyncio.create_task(service.stream("cancel"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert cancelled.is_set()
