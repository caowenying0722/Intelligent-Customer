"""Executable local API entrypoint."""

import uvicorn
from fastapi import FastAPI

from agent.tools.agent_tools import RagService
from rag.qdrant_backend import build_qdrant_backend
from src.app.application.approvals import ApprovalApplicationService
from src.app.application.chat import ChatAgent, ChatApplicationService
from src.app.infrastructure.checkpoints import (
    PostgresCheckpointRuntime,
    build_checkpoint_runtime,
)
from src.app.infrastructure.factory import (
    build_approval_repository,
    build_conversation_repository,
    build_document_ingestion_service,
)
from src.app.main import create_app
from src.app.security.auth import JWTAuthenticator
from src.app.workers.operations import WorkerOperationRegistry
from utils.settings import Settings, get_settings


def build_server_app(
    agent: ChatAgent | None = None,
    rag_service: RagService | None = None,
    *,
    settings: Settings | None = None,
    checkpoint_runtime: PostgresCheckpointRuntime | None = None,
    authenticator: JWTAuthenticator | None = None,
) -> FastAPI:
    """Build the runnable API composition root without import-time model loading."""

    runtime_settings = settings or get_settings()
    if authenticator is None and all(
        value is not None
        for value in (
            runtime_settings.jwt_secret,
            runtime_settings.jwt_issuer,
            runtime_settings.jwt_audience,
        )
    ):
        assert runtime_settings.jwt_secret is not None
        assert runtime_settings.jwt_issuer is not None
        assert runtime_settings.jwt_audience is not None
        authenticator = JWTAuthenticator(
            secret=runtime_settings.jwt_secret.get_secret_value(),
            issuer=runtime_settings.jwt_issuer,
            audience=runtime_settings.jwt_audience,
        )
    if runtime_settings.application_env == "production" and authenticator is None:
        raise ValueError(
            "JWT_SECRET, JWT_ISSUER and JWT_AUDIENCE are required in production"
        )
    database_url = runtime_settings.database_url
    if checkpoint_runtime is None:
        checkpoint_runtime = build_checkpoint_runtime(
            database_url,
            pool_size=runtime_settings.database_pool_size,
            connect_timeout=runtime_settings.database_connect_timeout_seconds,
        )
    if agent is None:
        from agent.react_agent import ReactAgent

        agent = ReactAgent(
            rag_service=rag_service,
            checkpointer=(
                checkpoint_runtime.checkpointer
                if checkpoint_runtime is not None
                else None
            ),
        )
    repository = build_conversation_repository(database_url)
    qdrant_backend = build_qdrant_backend(
        runtime_settings.qdrant_url,
        timeout_seconds=runtime_settings.qdrant_timeout_seconds,
    )
    approval_service = ApprovalApplicationService(build_approval_repository(repository))
    ingestion_service = (
        build_document_ingestion_service(database_url=database_url)
        if database_url is not None
        else None
    )
    worker_operations = (
        WorkerOperationRegistry(
            ingestion_service.job_store,
            qdrant_backend.client,
            upload_root=runtime_settings.upload_storage_root,
            timeout_seconds=runtime_settings.qdrant_timeout_seconds,
        )
        if ingestion_service is not None and qdrant_backend is not None
        else None
    )
    chat_service = ChatApplicationService(
        agent,
        timeout_seconds=runtime_settings.request_timeout_seconds,
        conversation_repository=repository,
        approval_service=approval_service,
    )
    resources: tuple[object, ...] = (repository, approval_service)
    if checkpoint_runtime is not None:
        resources = (checkpoint_runtime, *resources)
    if qdrant_backend is not None:
        resources = (*resources, qdrant_backend)
    if ingestion_service is not None:
        # Ingestion may still use Qdrant while draining; reverse-order shutdown
        # must therefore close the ingestion service before the Qdrant client.
        resources = (*resources, ingestion_service)
    ingestion_operation = None
    index_rebuild_operation = None
    if worker_operations is not None:

        def ingestion_operation(_path, _upload, document):
            return worker_operations.ingest_document(
                document.tenant_id, document.document_id
            )

        index_rebuild_operation = worker_operations.rebuild_index
    return create_app(
        chat_service=chat_service,
        database_url=database_url,
        rag_service=rag_service,
        readiness_check=(
            qdrant_backend.check_ready if qdrant_backend is not None else None
        ),
        lifecycle_resources=resources,
        ingestion_service=ingestion_service,
        ingestion_operation=ingestion_operation,
        index_rebuild_operation=index_rebuild_operation,
        authenticator=authenticator,
    )


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        build_server_app(),
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
