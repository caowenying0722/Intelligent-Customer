"""Executable local API entrypoint."""

import uvicorn

from utils.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "src.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
