"""Executable local API entrypoint."""

import uvicorn
from fastapi import FastAPI

from agent.tools.agent_tools import RagService
from src.app.application.chat import ChatAgent
from src.app.main import create_app
from utils.settings import get_settings


def build_server_app(
    agent: ChatAgent | None = None, rag_service: RagService | None = None
) -> FastAPI:
    """Build the runnable API composition root without import-time model loading."""

    if agent is None:
        from agent.react_agent import ReactAgent

        agent = ReactAgent(rag_service=rag_service)
    return create_app(chat_agent=agent, rag_service=rag_service)


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
