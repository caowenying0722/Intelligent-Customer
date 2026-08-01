from types import SimpleNamespace
from unittest.mock import patch

from src.app import server


def test_server_entrypoint_uses_configured_bind_address_and_port() -> None:
    settings = SimpleNamespace(api_host="0.0.0.0", api_port=8123)
    fake_app = object()

    with (
        patch.object(server, "get_settings", return_value=settings),
        patch.object(server, "build_server_app", return_value=fake_app),
        patch.object(server.uvicorn, "run") as run,
    ):
        server.main()

    run.assert_called_once_with(fake_app, host="0.0.0.0", port=8123, reload=False)
