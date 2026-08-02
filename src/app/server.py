"""Executable local API entrypoint."""

import uvicorn
from fastapi import FastAPI

from agent.tools.agent_tools import RagService
from src.app.application.approvals import ApprovalApplicationService
from src.app.application.chat import ChatAgent, ChatApplicationService
from src.app.infrastructure.checkpoints import (
    PostgresCheckpointRuntime,
    build_checkpoint_runtime,
)
from src.app.infrastructure.factory import (
    build_approval_repository,
    build_conversation_repository,
)
from src.app.main import create_app
from utils.settings import Settings, get_settings


def build_server_app(
    agent: ChatAgent | None = None,
    rag_service: RagService | None = None,
    *,
    settings: Settings | None = None,
    checkpoint_runtime: PostgresCheckpointRuntime | None = None,
) -> FastAPI:
    """Build the runnable API composition root without import-time model loading."""

    runtime_settings = settings or get_settings()
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
    approval_service = ApprovalApplicationService(build_approval_repository(repository))
    chat_service = ChatApplicationService(
        agent,
        timeout_seconds=runtime_settings.request_timeout_seconds,
        conversation_repository=repository,
        approval_service=approval_service,
    )
    resources: tuple[object, ...] = (repository, approval_service)
    if checkpoint_runtime is not None:
        resources = (checkpoint_runtime, *resources)
    return create_app(
        chat_service=chat_service,
        database_url=database_url,
        rag_service=rag_service,
        lifecycle_resources=resources,
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
