"""Application factory and health endpoints.

The factory deliberately accepts readiness dependencies instead of constructing
models, vector stores, or network clients during import or test startup.
"""

from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

ReadinessCheck = Callable[[], bool]


def create_app(*, readiness_check: ReadinessCheck | None = None) -> FastAPI:
    """Build an API app with injectable, side-effect-free readiness checks."""
    app = FastAPI(title="Intelligent Customer Service", version="0.1.0")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
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

    return app


app = create_app()
