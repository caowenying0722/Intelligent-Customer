import asyncio

from fastapi.routing import APIRoute
from starlette.requests import Request

from src.app.application.chat import ChatApplicationService
from src.app.main import create_app
from src.app.schemas import ChatRequest


class RecordingAgent:
    def __init__(self) -> None:
        self.stream_calls = 0

    def run(self, _message: str) -> str:
        return "ok"

    def stream(self, _message: str) -> list[str]:
        self.stream_calls += 1
        return ["first", "second"]


def test_sse_disconnect_after_metadata_stops_without_terminal_event() -> None:
    agent = RecordingAgent()
    app = create_app(chat_service=ChatApplicationService(agent))
    included_router = next(
        route for route in app.routes if hasattr(route, "original_router")
    )
    route = next(
        route
        for route in included_router.original_router.routes
        if isinstance(route, APIRoute) and route.path == "/api/v1/chat/stream"
    )

    async def exercise() -> str:
        async def receive() -> dict[str, object]:
            return {"type": "http.disconnect"}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/chat/stream",
                "raw_path": b"/api/v1/chat/stream",
                "query_string": b"",
                "headers": [],
                "client": ("testclient", 123),
                "server": ("testserver", 80),
            },
            receive,
        )
        request.state.request_id = "request-1"
        disconnect_checks = 0

        async def is_disconnected() -> bool:
            nonlocal disconnect_checks
            disconnect_checks += 1
            return disconnect_checks >= 2

        request.is_disconnected = is_disconnected  # type: ignore[method-assign]
        response = await route.endpoint(request, ChatRequest(message="hello"))
        chunks = [chunk async for chunk in response.body_iterator]
        return "".join(chunks)

    body = asyncio.run(exercise())
    assert '"type": "metadata"' in body
    assert '"type": "token"' not in body
    assert '"type": "completed"' not in body
    assert '"type": "error"' not in body
    assert agent.stream_calls == 1
