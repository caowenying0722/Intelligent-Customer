"""Chat HTTP routes; business orchestration stays in application services."""

import base64
import binascii
import json
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.app.application.chat import (
    ChatApplicationError,
    ChatApplicationService,
    ChatApprovalRequired,
)
from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.domain.approvals import (
    ApprovalNotFound,
    ApprovalStateConflict,
    HumanApproval,
)
from src.app.domain.conversations import (
    ConcurrencyConflict,
    IdempotencyConflict,
    RunStateConflict,
)
from src.app.schemas import (
    AgentRunListResponse,
    AgentRunResponse,
    ApprovalDecisionRequest,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    DocumentStatusResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
    ErrorResponse,
    HumanApprovalResponse,
    IndexRebuildRequest,
    IngestionJobResponse,
    MessageResponse,
    RunUpdateRequest,
)
from src.app.security.audit import AuditSink
from src.app.security.auth import JWTAuthenticator
from src.app.security.dependencies import auth_dependency, role_dependency, role_guard


def build_router(
    chat_service: ChatApplicationService | None,
    ingestion_service: DocumentIngestionService | None = None,
    ingestion_operation: Callable | None = None,
    index_rebuild_operation: Callable | None = None,
    authenticator: JWTAuthenticator | None = None,
    audit_sink: AuditSink | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(auth_dependency(authenticator, audit_sink))]
        if authenticator
        else [],
    )
    operator_dependencies = (
        [Depends(role_guard({"admin", "service_agent"}, audit_sink))]
        if authenticator is not None
        else []
    )

    def request_tenant_id(request: Request) -> str:
        return getattr(
            request.state, "tenant_id", request.headers.get("x-tenant-id", "local")
        )

    def ingestion_job_response(job: IngestionJob) -> IngestionJobResponse:
        return IngestionJobResponse(
            job_id=str(job.job_id),
            tenant_id=job.tenant_id,
            status=job.status.value,
            error=job.error,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            progress=job.progress,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            cancel_requested=job.cancel_requested,
        )

    def approval_response(
        approval: HumanApproval, *, answer: str | None = None
    ) -> HumanApprovalResponse:
        return HumanApprovalResponse(
            approval_id=str(approval.approval_id),
            conversation_id=str(approval.conversation_id),
            run_id=str(approval.run_id),
            tool_name=approval.tool_name,
            arguments=approval.arguments,
            risk_level=approval.risk_level,
            status=approval.status,
            execution_status=approval.execution_status,
            requested_at=approval.requested_at.isoformat(),
            expires_at=approval.expires_at.isoformat(),
            decided_at=(
                approval.decided_at.isoformat() if approval.decided_at else None
            ),
            decided_by=approval.decided_by,
            answer=answer,
        )

    @router.post(
        "/indexes/rebuild",
        response_model=IngestionJobResponse,
        dependencies=operator_dependencies,
    )
    async def rebuild_index(request: Request, payload: IndexRebuildRequest):
        if ingestion_service is None or index_rebuild_operation is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "index_rebuild_unavailable",
                    "message": "index rebuild processor is not configured",
                    "request_id": request.state.request_id,
                },
            )
        tenant_id = request_tenant_id(request)
        idempotency_key = (
            request.headers.get("idempotency-key") or payload.idempotency_key or ""
        )
        if not idempotency_key:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "missing_idempotency_key",
                    "message": "idempotency key is required",
                    "request_id": request.state.request_id,
                },
            )
        job_store = getattr(ingestion_service, "job_store", None)
        try:
            if job_store is not None:
                pending = IngestionJob(
                    job_id=uuid4(),
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    status=IngestionJobStatus.QUEUED,
                    created_at=datetime.now(timezone.utc),
                    task_type="index_rebuild",
                    task_payload=payload.index_version,
                )
                persisted = job_store.create_job(job=pending)
                if persisted.job_id != pending.job_id:
                    return ingestion_job_response(persisted)
                job = ingestion_service.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=lambda: index_rebuild_operation(
                        tenant_id, payload.index_version
                    ),
                    job_id=pending.job_id,
                    task_type="index_rebuild",
                    task_payload=payload.index_version,
                    defer_dispatch=ingestion_service.jobs.has_dispatcher,
                )
                current = (
                    ingestion_service.jobs.get(tenant_id=tenant_id, job_id=job.job_id)
                    or job
                )
                if current.status in {
                    IngestionJobStatus.RUNNING,
                    IngestionJobStatus.COMPLETED,
                    IngestionJobStatus.FAILED,
                    IngestionJobStatus.CANCELLED,
                }:
                    job_store.update_job_status(
                        tenant_id=tenant_id,
                        job_id=job.job_id,
                        status=current.status,
                        error=current.error,
                    )
                ingestion_service.jobs.dispatch(job)
            else:
                job = ingestion_service.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=lambda: index_rebuild_operation(
                        tenant_id, payload.index_version
                    ),
                    task_type="index_rebuild",
                    task_payload=payload.index_version,
                )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "invalid_rebuild",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        return ingestion_job_response(job)

    @router.post(
        "/documents",
        response_model=DocumentUploadResponse,
        dependencies=operator_dependencies,
    )
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
                tenant_id=request_tenant_id(request),
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
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "document ingestion is not configured",
                    "request_id": request.state.request_id,
                },
            )
        if ingestion_service.metadata is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "document metadata is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            document = ingestion_service.metadata.get(
                tenant_id=request_tenant_id(request),
                document_id=UUID(document_id),
            )
        except ValueError:
            document = None
        if document is None:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "document_not_found",
                    "message": "document not found",
                    "request_id": request.state.request_id,
                },
            )
        return DocumentStatusResponse(
            document_id=str(document.document_id),
            tenant_id=document.tenant_id,
            original_name=document.original_name,
            content_hash=document.content_hash,
            document_version=document.document_version,
            status=document.status.value,
            index_version=document.index_version,
        )

    @router.delete(
        "/documents/{document_id}",
        response_model=DocumentStatusResponse,
        dependencies=operator_dependencies,
    )
    async def delete_document(request: Request, document_id: str):
        if ingestion_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "document ingestion is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            document = ingestion_service.delete_document(
                tenant_id=request_tenant_id(request),
                document_id=UUID(document_id),
            )
        except (ValueError, KeyError):
            return JSONResponse(
                status_code=404,
                content={
                    "code": "document_not_found",
                    "message": "document not found",
                    "request_id": request.state.request_id,
                },
            )
        return DocumentStatusResponse(
            document_id=str(document.document_id),
            tenant_id=document.tenant_id,
            original_name=document.original_name,
            content_hash=document.content_hash,
            document_version=document.document_version,
            status=document.status.value,
            index_version=document.index_version,
        )

    @router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
    async def get_ingestion_job(request: Request, job_id: str):
        if ingestion_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "ingestion is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            tenant_id = request_tenant_id(request)
            parsed_job_id = UUID(job_id)
            job_store = getattr(ingestion_service, "job_store", None)
            job = (
                job_store.get_job(tenant_id=tenant_id, job_id=parsed_job_id)
                if job_store is not None
                else ingestion_service.jobs.get(
                    tenant_id=tenant_id, job_id=parsed_job_id
                )
            )
        except ValueError:
            job = None
        if job is None:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "job_not_found",
                    "message": "ingestion job not found",
                    "request_id": request.state.request_id,
                },
            )
        return IngestionJobResponse(
            job_id=str(job.job_id),
            tenant_id=job.tenant_id,
            status=job.status.value,
            error=job.error,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            progress=job.progress,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            cancel_requested=job.cancel_requested,
        )

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=IngestionJobResponse,
        dependencies=operator_dependencies,
    )
    async def cancel_ingestion_job(request: Request, job_id: str):
        if ingestion_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "ingestion_unavailable",
                    "message": "ingestion is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            parsed_id = UUID(job_id)
        except ValueError:
            parsed_id = None
        tenant_id = request_tenant_id(request)
        job_store = getattr(ingestion_service, "job_store", None)
        if job_store is not None:
            try:
                job = job_store.request_cancel(tenant_id=tenant_id, job_id=parsed_id)
            except (KeyError, TypeError):
                job = None
            cancelled = job is not None
            if (
                cancelled
                and job is not None
                and job.status.value == "running"
                and parsed_id is not None
            ):
                ingestion_service.jobs.cancel(tenant_id=tenant_id, job_id=parsed_id)
        else:
            if parsed_id is None:
                cancelled = False
                job = None
            else:
                cancelled = ingestion_service.jobs.cancel(
                    tenant_id=tenant_id, job_id=parsed_id
                )
                job = (
                    ingestion_service.jobs.get(tenant_id=tenant_id, job_id=parsed_id)
                    if cancelled
                    else None
                )
        if not cancelled or job is None:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "job_not_cancellable",
                    "message": "job not found or already running",
                    "request_id": request.state.request_id,
                },
            )
        return IngestionJobResponse(
            job_id=str(job.job_id),
            tenant_id=job.tenant_id,
            status=job.status.value,
            error=job.error,
            created_at=job.created_at.isoformat(),
            progress=job.progress,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            cancel_requested=job.cancel_requested,
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
                request_tenant_id(request),
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
        except ChatApprovalRequired as exc:
            response = approval_response(exc.approval)
            return JSONResponse(
                status_code=202,
                content={
                    "code": "approval_required",
                    "request_id": request.state.request_id,
                    **response.model_dump(mode="json"),
                },
            )
        except ChatApplicationError as exc:
            model_error = exc.model_error
            raw_code = (
                model_error.code.value
                if model_error is not None
                else ("chat_timeout" if "timed out" in str(exc) else "chat_failed")
            )
            code = "chat_failed" if raw_code == "unknown" else raw_code
            status_code = (
                504
                if code == "chat_timeout"
                else 429
                if code == "rate_limited"
                else 503
                if code == "provider_unavailable"
                else 400
            )
            return JSONResponse(
                status_code=status_code,
                content={
                    "code": code,
                    "message": str(exc),
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

    @router.get("/approvals/{approval_id}", response_model=HumanApprovalResponse)
    async def get_approval(request: Request, approval_id: str):
        approval_service = (
            chat_service.approval_service if chat_service is not None else None
        )
        if approval_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "approval_unavailable",
                    "message": "approval service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            parsed = UUID(approval_id)
        except ValueError:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "approval_not_found",
                    "message": "approval not found",
                    "request_id": request.state.request_id,
                },
            )
        approval = approval_service.get(request_tenant_id(request), parsed)
        if approval is None:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "approval_not_found",
                    "message": "approval not found",
                    "request_id": request.state.request_id,
                },
            )
        return approval_response(approval)

    decision_dependencies = (
        [Depends(role_dependency(authenticator, {"admin", "approver"}, audit_sink))]
        if authenticator is not None
        else []
    )

    @router.post(
        "/approvals/{approval_id}/decision",
        response_model=HumanApprovalResponse,
        dependencies=decision_dependencies,
    )
    async def decide_approval(
        request: Request, approval_id: str, payload: ApprovalDecisionRequest
    ):
        if chat_service is None or chat_service.approval_service is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "approval_unavailable",
                    "message": "approval service is not configured",
                    "request_id": request.state.request_id,
                },
            )
        try:
            parsed = UUID(approval_id)
        except ValueError:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "approval_not_found",
                    "message": "approval not found",
                    "request_id": request.state.request_id,
                },
            )
        claims = getattr(request.state, "auth_claims", None)
        decided_by = (
            claims.subject
            if claims is not None
            else request.headers.get("x-user-id", "local-approver")
        )
        try:
            approval, answer = await chat_service.decide_approval(
                request_tenant_id(request),
                parsed,
                approved=payload.approved,
                decided_by=decided_by,
            )
        except ApprovalNotFound:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "approval_not_found",
                    "message": "approval not found",
                    "request_id": request.state.request_id,
                },
            )
        except ApprovalStateConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "approval_conflict",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        except ChatApprovalRequired as exc:
            response = approval_response(exc.approval)
            return JSONResponse(
                status_code=202,
                content={
                    "code": "approval_required",
                    "request_id": request.state.request_id,
                    **response.model_dump(mode="json"),
                },
            )
        except ChatApplicationError as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "approval_execution_failed",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                },
            )
        return approval_response(approval, answer=answer)

    @router.post("/chat/stream")
    async def chat_stream(request: Request, payload: ChatRequest):
        async def events():
            request_id = request.state.request_id
            if await request.is_disconnected():
                return
            if chat_service is None:
                yield f"data: {json.dumps({'type': 'metadata', 'request_id': request_id}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'error', 'code': 'chat_unavailable', 'request_id': request_id})}\n\n"
                return
            try:
                resolved_conversation_id = payload.conversation_id
                if resolved_conversation_id is None:
                    conversation = chat_service.conversation_repository.create(
                        request_tenant_id(request),
                        request.headers.get("x-user-id", "local"),
                    )
                    resolved_conversation_id = str(conversation.conversation_id)
                yield f"data: {json.dumps({'type': 'metadata', 'request_id': request_id, 'conversation_id': resolved_conversation_id}, ensure_ascii=False)}\n\n"
                chunks = await chat_service.stream(
                    payload.message,
                    resolved_conversation_id,
                    request_tenant_id(request),
                    request.headers.get("x-user-id", "local"),
                )
                for chunk in chunks:
                    if await request.is_disconnected():
                        return
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'completed', 'request_id': request_id})}\n\n"
            except ChatApplicationError as exc:
                model_error = exc.model_error
                code = (
                    model_error.code.value
                    if model_error is not None
                    else ("chat_timeout" if "timed out" in str(exc) else "chat_failed")
                )
                if code == "unknown":
                    code = "chat_failed"
                yield f"data: {json.dumps({'type': 'error', 'code': code, 'message': str(exc), 'request_id': request_id})}\n\n"
            except Exception:  # noqa: BLE001 - SSE boundary emits a stable safe error.
                yield f"data: {json.dumps({'type': 'error', 'code': 'chat_failed', 'message': 'chat execution failed', 'request_id': request_id})}\n\n"

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
            chat_service.conversation_repository.get(request_tenant_id(request), parsed)
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
                request_tenant_id(request), UUID(conversation_id)
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
                request_tenant_id(request), UUID(run_id)
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
                request_tenant_id(request),
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

    @router.patch(
        "/runs/{run_id}",
        response_model=AgentRunResponse,
        dependencies=operator_dependencies,
    )
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
                request_tenant_id(request),
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
    (ApprovalDecisionRequest,)
    (HumanApprovalResponse,)
