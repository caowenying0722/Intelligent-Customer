"""Application factory and health endpoints."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.app.api.routes import build_router
from src.app.application.chat import ChatAgent, ChatApplicationService
from src.app.infrastructure.factory import build_conversation_repository

ReadinessCheck = Callable[[], bool]


def create_app(
    *,
    readiness_check: ReadinessCheck | None = None,
    chat_service: ChatApplicationService | None = None,
    chat_agent: ChatAgent | None = None,
    database_url: str | None = None,
    lifecycle_resources: tuple[object, ...] = (),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
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

    app.include_router(build_router(chat_service))
    return app


app = create_app()
