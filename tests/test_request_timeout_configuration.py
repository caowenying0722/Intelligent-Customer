import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app.main import create_app
from utils.settings import Settings


class SlowAgent:
    def run(self, _message: str) -> str:
        time.sleep(0.1)
        return "late"

    def stream(self, _message: str) -> list[str]:
        return ["late"]


def test_auto_built_chat_service_uses_request_timeout_setting() -> None:
    settings = Settings(_env_file=None, request_timeout_seconds=0.01)  # type: ignore[call-arg]
    with patch("src.app.main.get_settings", return_value=settings):
        response = TestClient(create_app(chat_agent=SlowAgent())).post(
            "/api/v1/chat", json={"message": "slow"}
        )

    assert response.status_code == 504
    assert response.json()["code"] == "chat_timeout"
