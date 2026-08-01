"""Executable local API entrypoint."""

import uvicorn
from fastapi import FastAPI

from src.app.application.chat import ChatAgent
from src.app.main import create_app
from utils.settings import get_settings


def build_server_app(agent: ChatAgent | None = None) -> FastAPI:
    """Build the runnable API composition root without import-time model loading."""

    if agent is None:
        from agent.react_agent import ReactAgent

        agent = ReactAgent()
    return create_app(chat_agent=agent)


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
