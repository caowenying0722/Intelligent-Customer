"""Application factory and health endpoints."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from src.app.api.routes import build_router
from src.app.application.approvals import ApprovalApplicationService
from src.app.application.chat import ChatAgent, ChatApplicationService
from src.app.application.ingestion_service import DocumentIngestionService
from src.app.application.ingestion_worker import IngestionWorker
from src.app.infrastructure.factory import (
    build_approval_repository,
    build_conversation_repository,
    build_document_ingestion_service,
)
from src.app.observability.access_log import log_http_request
from src.app.observability.metrics import (
    HttpMetrics,
    empty_gateway_snapshot,
    empty_rag_snapshot,
    empty_tool_snapshot,
    empty_worker_snapshot,
    metrics_token_matches,
    render_prometheus,
)
from src.app.observability.tracing import (
    ApiTracer,
    TraceContext,
    reset_current_tracer,
    set_current_tracer,
)
from src.app.security.audit import AuditSink
from src.app.security.auth import JWTAuthenticator
from utils.settings import get_settings

ReadinessCheck = Callable[[], bool]


def create_app(
    *,
    readiness_check: ReadinessCheck | None = None,
    chat_service: ChatApplicationService | None = None,
    chat_agent: ChatAgent | None = None,
    database_url: str | None = None,
    rag_service: object | None = None,
    lifecycle_resources: tuple[object, ...] = (),
    ingestion_service: DocumentIngestionService | None = None,
    ingestion_operation: Callable | None = None,
    index_rebuild_operation: Callable | None = None,
    model_health_token: str | None = None,
    metrics_token: str | None = None,
    authenticator: JWTAuthenticator | None = None,
    audit_sink: AuditSink | None = None,
) -> FastAPI:
    settings = get_settings()
    if model_health_token is None:
        model_health_token = settings.model_health_token_value
    if metrics_token is None:
        metrics_token = settings.metrics_token_value
    if settings.application_env == "production" and not model_health_token:
        raise ValueError("MODEL_HEALTH_TOKEN is required in production")
    if settings.application_env == "production" and not metrics_token:
        raise ValueError("METRICS_TOKEN is required in production")
    http_metrics = HttpMetrics()
    api_tracer = ApiTracer(
        max_spans=settings.trace_max_spans,
        otlp_endpoint=settings.otel_exporter_endpoint,
        otlp_timeout_seconds=settings.otel_exporter_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            for resource in lifecycle_resources:
                start = getattr(resource, "start", None)
                if callable(start):
                    start()
            if rag_service is not None:
                start_loading = getattr(rag_service, "start_document_loading", None)
                if callable(start_loading):
                    start_loading()
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
                    operation_for=lambda job: (
                        lambda: index_rebuild_operation(job.task_payload or "")
                    ),
                )
            yield
        finally:
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
        approval_service = ApprovalApplicationService(
            build_approval_repository(repository)
        )
        chat_service = ChatApplicationService(
            chat_agent,
            timeout_seconds=settings.request_timeout_seconds,
            conversation_repository=repository,
            tracer=api_tracer,
            approval_service=approval_service,
        )
        lifecycle_resources = (*lifecycle_resources, repository, approval_service)

    if ingestion_service is None and database_url:
        ingestion_service = build_document_ingestion_service(database_url=database_url)
        lifecycle_resources = (*lifecycle_resources, ingestion_service)
    if rag_service is not None:
        lifecycle_resources = (*lifecycle_resources, rag_service)
    lifecycle_resources = (api_tracer, *lifecycle_resources)

    readiness_checks: list[ReadinessCheck] = []
    if readiness_check is not None:
        readiness_checks.append(readiness_check)
    if chat_service is not None:
        candidate = getattr(chat_service.conversation_repository, "check_ready", None)
        if callable(candidate):
            readiness_checks.append(candidate)
    if rag_service is not None:
        candidate = getattr(rag_service, "check_ready", None)
        if callable(candidate):
            readiness_checks.append(candidate)

    def combined_readiness() -> bool:
        for check in readiness_checks:
            try:
                if not check():
                    return False
            except Exception:  # noqa: BLE001 - readiness fails closed.
                return False
        return True

    app = FastAPI(
        title="Intelligent Customer Service", version="0.1.0", lifespan=lifespan
    )
    app.state.http_metrics = http_metrics
    app.state.trace_exporter = api_tracer.exporter
    worker_metrics = (
        getattr(ingestion_service.jobs, "metrics", None)
        if ingestion_service is not None
        else None
    )
    app.state.worker_metrics = worker_metrics
    rag_metrics = getattr(rag_service, "metrics", None)
    app.state.rag_metrics = rag_metrics
    tool_metrics = (
        getattr(chat_service.agent, "tool_metrics", None)
        if chat_service is not None
        else None
    )
    app.state.tool_metrics = tool_metrics
    if chat_service is not None:
        chat_service.tracer = api_tracer
    if ingestion_service is not None:
        ingestion_service.jobs.tracer = api_tracer

    @app.middleware("http")
    async def http_metrics_middleware(request: Request, call_next):
        started = http_metrics.begin()
        status_code = 500
        client_disconnected = False
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            client_disconnected = exc.__class__.__name__ == "ClientDisconnect"
            raise
        finally:
            http_metrics.end(
                started,
                status_code=status_code,
                path=request.url.path,
                client_disconnected=client_disconnected,
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
        started = perf_counter()
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            log_http_request(
                method=request.method,
                status_code=status_code,
                duration_ms=(perf_counter() - started) * 1000,
                request_id=request_id,
                trace_id=getattr(request.state, "trace_id", None),
            )

    @app.middleware("http")
    async def trace_context_middleware(request: Request, call_next):
        context = TraceContext.from_traceparent(request.headers.get("traceparent"))
        request.state.trace_context = context
        request.state.trace_id = context.trace_id
        tracer_token = set_current_tracer(api_tracer)
        try:
            with api_tracer.start_http_span(context) as span:
                response = await call_next(request)
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.status_code", response.status_code)
                span_context = span.get_span_context()
                server_context = context.with_span_id(f"{span_context.span_id:016x}")
                request.state.trace_span_id = server_context.span_id
                response.headers["traceparent"] = server_context.traceparent
                return response
        finally:
            reset_current_tracer(tracer_token)

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=None)
    async def readiness() -> dict[str, str] | Response:
        if not combined_readiness():
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    @app.get("/metrics", response_model=None)
    async def metrics(request: Request) -> dict[str, object] | JSONResponse:
        if not metrics_token_matches(
            metrics_token, request.headers.get("x-metrics-token")
        ):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        gateway = getattr(chat_service, "model_gateway", None)
        if gateway is None or not hasattr(gateway, "audit_snapshot"):
            return {
                "model_gateway": empty_gateway_snapshot(),
                "model_gateway_health": {
                    "configured_providers": [],
                    "circuit_open": False,
                    "healthy": False,
                },
                "http": http_metrics.snapshot(),
                "worker": (
                    worker_metrics.snapshot()
                    if worker_metrics is not None
                    else empty_worker_snapshot()
                ),
                "rag": (
                    rag_metrics.snapshot()
                    if rag_metrics is not None
                    else empty_rag_snapshot()
                ),
                "tool": (
                    tool_metrics.snapshot()
                    if tool_metrics is not None
                    else empty_tool_snapshot()
                ),
            }
        return {
            "model_gateway": gateway.audit_snapshot(),
            "model_gateway_health": gateway.health_snapshot(),
            "http": http_metrics.snapshot(),
            "worker": (
                worker_metrics.snapshot()
                if worker_metrics is not None
                else empty_worker_snapshot()
            ),
            "rag": (
                rag_metrics.snapshot()
                if rag_metrics is not None
                else empty_rag_snapshot()
            ),
            "tool": (
                tool_metrics.snapshot()
                if tool_metrics is not None
                else empty_tool_snapshot()
            ),
        }

    @app.get(
        "/metrics/prometheus", response_class=PlainTextResponse, response_model=None
    )
    async def prometheus_metrics(request: Request) -> PlainTextResponse | JSONResponse:
        if not metrics_token_matches(
            metrics_token, request.headers.get("x-metrics-token")
        ):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        gateway = getattr(chat_service, "model_gateway", None)
        if gateway is None or not hasattr(gateway, "audit_snapshot"):
            gateway_snapshot = empty_gateway_snapshot()
            health_snapshot = {
                "configured_providers": [],
                "circuit_open": False,
                "healthy": False,
            }
        else:
            gateway_snapshot = gateway.audit_snapshot()
            health_snapshot = gateway.health_snapshot()
        worker_snapshot = (
            worker_metrics.snapshot()
            if worker_metrics is not None
            else empty_worker_snapshot()
        )
        rag_snapshot = (
            rag_metrics.snapshot() if rag_metrics is not None else empty_rag_snapshot()
        )
        tool_snapshot = (
            tool_metrics.snapshot()
            if tool_metrics is not None
            else empty_tool_snapshot()
        )
        return PlainTextResponse(
            render_prometheus(
                gateway_snapshot,
                health_snapshot,
                http_metrics.snapshot(),
                worker_snapshot,
                rag_snapshot,
                tool_snapshot,
            ),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/health/model", response_model=None)
    async def model_health(request: Request) -> JSONResponse | dict[str, object]:
        if (
            model_health_token is not None
            and request.headers.get("x-model-health-token") != model_health_token
        ):
            return JSONResponse(status_code=401, content={"status": "unauthorized"})
        gateway = getattr(chat_service, "model_gateway", None)
        if gateway is None or not hasattr(gateway, "health_snapshot"):
            return {
                "status": "unhealthy",
                "configured_providers": [],
                "circuit_open": False,
            }
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
