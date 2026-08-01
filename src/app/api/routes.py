"""Chat HTTP routes; business orchestration stays in application services."""

import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.application.chat import ChatApplicationService
from src.app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ErrorResponse,
    MessageResponse,
)


def build_router(chat_service: ChatApplicationService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post(
        "/chat",
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
                payload.message,
                payload.conversation_id,
                request.headers.get("x-tenant-id", "local"),
            )
        except Exception as exc:  # noqa: BLE001 - stable boundary, no traceback.
            status_code = 504 if "timed out" in str(exc) else 400
            return JSONResponse(
                status_code=status_code,
                content={
                    "code": "chat_timeout" if status_code == 504 else "chat_failed",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        return ChatResponse(
            request_id=request.state.request_id,
            answer=answer,
            conversation_id=str(conversation_id),
        )

    @router.post("/chat/stream")
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

    @router.get(
        "/conversations/{conversation_id}",
        response_model=ConversationResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_conversation(request: Request, conversation_id: str):
        if chat_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "conversation_unavailable",
                    "message": "conversation service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            parsed = UUID(conversation_id)
        except ValueError:
            parsed = None
        conversation = (
            chat_service.conversation_repository.get(
                request.headers.get("x-tenant-id", "local"), parsed
            )
            if parsed
            else None
        )
        if conversation is None:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "conversation_not_found",
                    "message": "conversation not found",
                    "request_id": request.state.request_id,
                },
            )
        return ConversationResponse(
            conversation_id=str(conversation.conversation_id),
            version=conversation.version,
            messages=[
                MessageResponse(
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at.isoformat(),
                )
                for message in conversation.messages
            ],
        )

    return router
