"""Application factory and health endpoints."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.app.api.routes import build_router
from src.app.application.chat import ChatAgent, ChatApplicationService
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.ingestion_worker import IngestionWorker
from src.app.infrastructure.factory import (
    build_conversation_repository,
    build_document_ingestion_service,
)
from src.app.security.auth import JWTAuthenticator
from src.app.security.audit import AuditSink
from utils.settings import get_settings

ReadinessCheck = Callable[[], bool]


def create_app(
    *,
    readiness_check: ReadinessCheck | None = None,
    chat_service: ChatApplicationService | None = None,
    chat_agent: ChatAgent | None = None,
    database_url: str | None = None,
    lifecycle_resources: tuple[object, ...] = (),
    ingestion_service: DocumentIngestionService | None = None,
    ingestion_operation: Callable | None = None,
    index_rebuild_operation: Callable | None = None,
    model_health_token: str | None = None,
    authenticator: JWTAuthenticator | None = None,
    audit_sink: AuditSink | None = None,
) -> FastAPI:
    settings = get_settings()
    if model_health_token is None:
        model_health_token = settings.model_health_token_value
    if settings.application_env == "production" and not model_health_token:
        raise ValueError("MODEL_HEALTH_TOKEN is required in production")
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if (
            ingestion_service is not None
            and ingestion_service.job_store is not None
            and index_rebuild_operation is not None
        ):
            IngestionWorker(
                ingestion_service.jobs, ingestion_service.job_store
            ).recover_queued(
                tenant_id=None,
                task_type="index_rebuild",
                operation_for=lambda job: lambda: index_rebuild_operation(
                    job.task_payload or ""
                ),
            )
        yield
        for resource in reversed(lifecycle_resources):
            close = getattr(resource, "close", None)
            if close is not None:
                close()
                continue
            async_close = getattr(resource, "aclose", None)
            if async_close is not None:
                await async_close()

    if chat_service is None and chat_agent is not None:
        repository = build_conversation_repository(database_url)
        chat_service = ChatApplicationService(
            chat_agent,
            conversation_repository=repository,
        )
        lifecycle_resources = (*lifecycle_resources, repository)

    if ingestion_service is None and database_url:
        ingestion_service = build_document_ingestion_service(
            database_url=database_url
        )
        lifecycle_resources = (*lifecycle_resources, ingestion_service)

    if readiness_check is None and chat_service is not None:
        candidate = getattr(chat_service.conversation_repository, "check_ready", None)
        if callable(candidate):
            readiness_check = candidate

    app = FastAPI(
        title="Intelligent Customer Service", version="0.1.0", lifespan=lifespan
    )

    def error_payload(request: Request, code: str, message: str) -> dict[str, str]:
        return {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
        }

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                request, "validation_error", "request validation failed"
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, "http_error", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, _exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_payload(request, "internal_error", "internal server error"),
        )

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
        if not (readiness_check or (lambda: True))():
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    @app.get("/metrics")
    async def metrics() -> dict[str, object]:
        gateway = getattr(chat_service, "model_gateway", None)
        if gateway is None or not hasattr(gateway, "audit_snapshot"):
            return {
                "model_gateway": {"calls": 0, "failures": 0, "provider_calls": {}, "provider_failures": {}},
                "model_gateway_health": {"configured_providers": [], "circuit_open": False, "healthy": False},
            }
        return {
            "model_gateway": gateway.audit_snapshot(),
            "model_gateway_health": gateway.health_snapshot(),
        }

    @app.get("/health/model", response_model=None)
    async def model_health(request: Request) -> JSONResponse | dict[str, object]:
        if model_health_token is not None and request.headers.get("x-model-health-token") != model_health_token:
            return JSONResponse(status_code=401, content={"status": "unauthorized"})
        gateway = getattr(chat_service, "model_gateway", None)
        if gateway is None or not hasattr(gateway, "health_snapshot"):
            return {"status": "unhealthy", "configured_providers": [], "circuit_open": False}
        snapshot = gateway.health_snapshot()
        return {"status": "ok" if snapshot["healthy"] else "unhealthy", **snapshot}

    if ingestion_service is not None and ingestion_service not in lifecycle_resources:
        lifecycle_resources = (*lifecycle_resources, ingestion_service)
    app.include_router(
        build_router(
            chat_service,
            ingestion_service,
            ingestion_operation,
            index_rebuild_operation,
            authenticator,
            audit_sink,
        )
    )
    return app


app = create_app()
