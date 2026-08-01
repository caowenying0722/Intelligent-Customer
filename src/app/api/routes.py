"""Chat HTTP routes; business orchestration stays in application services."""

import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.application.chat import ChatApplicationService
from src.app.domain.conversations import (
    ConcurrencyConflict,
    IdempotencyConflict,
    RunStateConflict,
)
from src.app.schemas import (
    AgentRunResponse,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ErrorResponse,
    MessageResponse,
    RunUpdateRequest,
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
            answer, conversation_id, run_id = await chat_service.chat(
                payload.message,
                payload.conversation_id,
                request.headers.get("x-tenant-id", "local"),
                request.headers.get("x-user-id", "local"),
                payload.expected_version,
                request.headers.get("idempotency-key") or payload.idempotency_key,
            )
        except IdempotencyConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "idempotency_reused",
                    "message": "idempotency key was already used",
                    "run_id": str(exc.run_id),
                    "request_id": request.state.request_id,
                },
            )
        except ConcurrencyConflict:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "conversation_conflict",
                    "message": "conversation changed; refresh and retry",
                    "request_id": request.state.request_id,
                },
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
            run_id=str(run_id),
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
            user_id=conversation.user_id,
            status=conversation.status,
            messages=[
                MessageResponse(
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at.isoformat(),
                )
                for message in conversation.messages
            ],
        )

    @router.post(
        "/conversations/{conversation_id}/runs", response_model=AgentRunResponse
    )
    async def create_run(request: Request, conversation_id: str):
        if chat_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "run_unavailable",
                    "message": "run service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            run = chat_service.conversation_repository.create_run(
                request.headers.get("x-tenant-id", "local"), UUID(conversation_id)
            )
        except (KeyError, ValueError):
            return JSONResponse(
                status_code=404,
                content={
                    "code": "conversation_not_found",
                    "message": "conversation not found",
                    "request_id": request.state.request_id,
                },
            )
        return AgentRunResponse(
            run_id=str(run.run_id),
            conversation_id=str(run.conversation_id),
            status=run.status,
            error=run.error,
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            duration_ms=run.duration_ms,
        )

    @router.get("/runs/{run_id}", response_model=AgentRunResponse)
    async def get_run(request: Request, run_id: str):
        if chat_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "run_unavailable",
                    "message": "run service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            run = chat_service.conversation_repository.get_run(
                request.headers.get("x-tenant-id", "local"), UUID(run_id)
            )
        except ValueError:
            run = None
        if run is None:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "run_not_found",
                    "message": "agent run not found",
                    "request_id": request.state.request_id,
                },
            )
        return AgentRunResponse(
            run_id=str(run.run_id),
            conversation_id=str(run.conversation_id),
            status=run.status,
            error=run.error,
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            duration_ms=run.duration_ms,
        )

    @router.patch("/runs/{run_id}", response_model=AgentRunResponse)
    async def update_run(request: Request, run_id: str, payload: RunUpdateRequest):
        if chat_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "run_unavailable",
                    "message": "run service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            run = chat_service.conversation_repository.update_run(
                request.headers.get("x-tenant-id", "local"),
                UUID(run_id),
                payload.status,
                payload.error,
            )
        except RunStateConflict:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "run_state_conflict",
                    "message": "invalid agent run state transition",
                    "request_id": request.state.request_id,
                },
            )
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "invalid_run_status",
                    "message": "invalid agent run status",
                    "request_id": request.state.request_id,
                },
            )
        except (KeyError,):
            return JSONResponse(
                status_code=404,
                content={
                    "code": "run_not_found",
                    "message": "agent run not found",
                    "request_id": request.state.request_id,
                },
            )
        return AgentRunResponse(
            run_id=str(run.run_id),
            conversation_id=str(run.conversation_id),
            status=run.status,
            error=run.error,
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            duration_ms=run.duration_ms,
        )

    return router
