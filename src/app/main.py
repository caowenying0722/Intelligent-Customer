"""Application factory and health endpoints.

The factory deliberately accepts readiness dependencies instead of constructing
models, vector stores, or network clients during import or test startup.
"""

import json
from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.application.chat import ChatApplicationService
from src.app.schemas import ChatRequest, ChatResponse, ErrorResponse

ReadinessCheck = Callable[[], bool]


def create_app(
    *,
    readiness_check: ReadinessCheck | None = None,
    chat_service: ChatApplicationService | None = None,
) -> FastAPI:
    """Build an API app with injectable, side-effect-free readiness checks."""
    app = FastAPI(title="Intelligent Customer Service", version="0.1.0")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=None)
    async def readiness() -> dict[str, str] | Response:
        check = readiness_check or (lambda: True)
        if not check():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    @app.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={400: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    )
    async def chat(request: Request, payload: ChatRequest):
        if chat_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "chat_unavailable",
                    "message": "chat service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            answer, conversation_id = await chat_service.chat(
                payload.message, payload.conversation_id
            )
        except Exception as exc:  # noqa: BLE001 - stable boundary, no traceback.
            status_code = 504 if "timed out" in str(exc) else 400
            code = "chat_timeout" if status_code == 504 else "chat_failed"
            return JSONResponse(
                status_code=status_code,
                content={
                    "code": code,
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        return ChatResponse(
            request_id=request.state.request_id,
            answer=answer,
            conversation_id=str(conversation_id),
        )

    @app.post("/api/v1/chat/stream")
    async def chat_stream(request: Request, payload: ChatRequest):
        async def events():
            request_id = request.state.request_id
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps({'type': 'metadata', 'request_id': request_id}, ensure_ascii=False)}\n\n"
            if chat_service is None:
                yield f"data: {json.dumps({'type': 'error', 'code': 'chat_unavailable', 'request_id': request_id})}\n\n"
                return
            try:
                chunks = await chat_service.stream(payload.message)
                for chunk in chunks:
                    if await request.is_disconnected():
                        return
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'completed', 'request_id': request_id})}\n\n"
            except Exception as exc:  # noqa: BLE001 - stable SSE error envelope.
                yield f"data: {json.dumps({'type': 'error', 'code': 'chat_failed', 'message': str(exc), 'request_id': request_id})}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()
