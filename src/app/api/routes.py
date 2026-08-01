"""Chat HTTP routes; business orchestration stays in application services."""

import json
import base64
import binascii
from datetime import datetime
from uuid import UUID
from collections.abc import Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.application.chat import ChatApplicationService
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.domain.conversations import (
    ConcurrencyConflict,
    IdempotencyConflict,
    RunStateConflict,
)
from src.app.schemas import (
    AgentRunListResponse,
    AgentRunResponse,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ErrorResponse,
    MessageResponse,
    RunUpdateRequest,
    DocumentUploadRequest,
    DocumentUploadResponse,
    DocumentStatusResponse,
    IngestionJobResponse,
)


def build_router(
    chat_service: ChatApplicationService | None,
    ingestion_service: DocumentIngestionService | None = None,
    ingestion_operation: Callable | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/documents", response_model=DocumentUploadResponse)
    async def upload_document(request: Request, payload: DocumentUploadRequest):
        if ingestion_service is None or ingestion_operation is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "document ingestion processor is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
            submission = ingestion_service.submit_document(
                tenant_id=request.headers.get("x-tenant-id", "local"),
                idempotency_key=request.headers.get("idempotency-key")
                or payload.idempotency_key
                or "",
                filename=payload.filename,
                content=content,
                content_type=payload.content_type,
                parser_version=payload.parser_version,
                chunker_version=payload.chunker_version,
                embedding_model=payload.embedding_model,
                embedding_dimension=payload.embedding_dimension,
                index_version=payload.index_version,
                operation=ingestion_operation,
            )
        except (binascii.Error, ValueError) as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "invalid_upload",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        return DocumentUploadResponse(
            document_id=str(submission.document.document_id),
            job_id=str(submission.job.job_id) if submission.job else None,
            status=submission.document.status.value,
            created=submission.created,
        )

    @router.get("/documents/{document_id}", response_model=DocumentStatusResponse)
    async def get_document(request: Request, document_id: str):
        if ingestion_service is None:
            return JSONResponse(status_code=503, content={"code": "ingestion_unavailable", "message": "document ingestion is not configured", "request_id": request.state.request_id})
        try:
            document = ingestion_service.metadata.get(
                tenant_id=request.headers.get("x-tenant-id", "local"),
                document_id=UUID(document_id),
            )
        except ValueError:
            document = None
        if document is None:
            return JSONResponse(status_code=404, content={"code": "document_not_found", "message": "document not found", "request_id": request.state.request_id})
        return DocumentStatusResponse(
            document_id=str(document.document_id), tenant_id=document.tenant_id,
            original_name=document.original_name, content_hash=document.content_hash,
            document_version=document.document_version, status=document.status.value,
            index_version=document.index_version,
        )

    @router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
    async def get_ingestion_job(request: Request, job_id: str):
        if ingestion_service is None:
            return JSONResponse(status_code=503, content={"code": "ingestion_unavailable", "message": "ingestion is not configured", "request_id": request.state.request_id})
        try:
            tenant_id = request.headers.get("x-tenant-id", "local")
            parsed_job_id = UUID(job_id)
            job_store = getattr(ingestion_service, "job_store", None)
            job = (
                job_store.get_job(tenant_id=tenant_id, job_id=parsed_job_id)
                if job_store is not None
                else ingestion_service.jobs.get(tenant_id=tenant_id, job_id=parsed_job_id)
            )
        except ValueError:
            job = None
        if job is None:
            return JSONResponse(status_code=404, content={"code": "job_not_found", "message": "ingestion job not found", "request_id": request.state.request_id})
        return IngestionJobResponse(
            job_id=str(job.job_id), tenant_id=job.tenant_id, status=job.status.value,
            error=job.error, created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )

    @router.post("/jobs/{job_id}/cancel", response_model=IngestionJobResponse)
    async def cancel_ingestion_job(request: Request, job_id: str):
        if ingestion_service is None:
            return JSONResponse(status_code=503, content={"code": "ingestion_unavailable", "message": "ingestion is not configured", "request_id": request.state.request_id})
        try:
            parsed_id = UUID(job_id)
        except ValueError:
            parsed_id = None
        tenant_id = request.headers.get("x-tenant-id", "local")
        job_store = getattr(ingestion_service, "job_store", None)
        if job_store is not None:
            try:
                job = job_store.request_cancel(tenant_id=tenant_id, job_id=parsed_id)
            except (KeyError, TypeError):
                job = None
            cancelled = job is not None
        else:
            cancelled = parsed_id is not None and ingestion_service.jobs.cancel(
                tenant_id=tenant_id, job_id=parsed_id
            )
            job = ingestion_service.jobs.get(tenant_id=tenant_id, job_id=parsed_id) if cancelled else None
        if not cancelled or job is None:
            return JSONResponse(status_code=409, content={"code": "job_not_cancellable", "message": "job not found or already running", "request_id": request.state.request_id})
        return IngestionJobResponse(
            job_id=str(job.job_id), tenant_id=job.tenant_id, status=job.status.value,
            error=job.error, created_at=job.created_at.isoformat(),
        )

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

    @router.get("/runs", response_model=AgentRunListResponse)
    async def list_runs(
        request: Request,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
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
            runs = chat_service.conversation_repository.list_runs(
                request.headers.get("x-tenant-id", "local"),
                status,
                created_after,
                created_before,
                limit,
                offset,
            )
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "invalid_pagination",
                    "message": "invalid run pagination",
                    "request_id": request.state.request_id,
                },
            )
        return AgentRunListResponse(
            items=[
                AgentRunResponse(
                    run_id=str(run.run_id),
                    conversation_id=str(run.conversation_id),
                    status=run.status,
                    error=run.error,
                    created_at=run.created_at.isoformat(),
                    started_at=run.started_at.isoformat() if run.started_at else None,
                    completed_at=run.completed_at.isoformat()
                    if run.completed_at
                    else None,
                    duration_ms=run.duration_ms,
                )
                for run in runs
            ],
            limit=limit,
            offset=offset,
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
