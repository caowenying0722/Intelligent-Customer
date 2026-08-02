from datetime import datetime, timedelta, timezone
from typing import cast

import jwt
from fastapi.testclient import TestClient

from agent.tools.agent_tools import RagService
from src.app.server import build_server_app
from utils.settings import Settings


class FakeAgent:
    def run(self, message: str) -> str:
        return f"answer:{message}"

    def stream(self, message: str) -> list[str]:
        return [f"answer:{message}"]


def test_server_composition_root_injects_agent_without_real_provider() -> None:
    client = TestClient(build_server_app(FakeAgent()))

    response = client.post("/api/v1/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["answer"] == "answer:hello"


def test_server_composition_root_passes_rag_service_to_readiness() -> None:
    class FakeRag:
        def check_ready(self) -> bool:
            return False

        def close(self) -> None:
            return None

    client = TestClient(
        build_server_app(FakeAgent(), rag_service=cast(RagService, FakeRag()))
    )

    assert client.get("/health/ready").status_code == 503


def test_production_server_wires_jwt_authentication_from_settings() -> None:
    settings = Settings.model_validate(
        {
            "application_env": "production",
            "model_health_token": "h" * 32,
            "metrics_token": "m" * 32,
            "jwt_secret": "s" * 32,
            "jwt_issuer": "issuer",
            "jwt_audience": "audience",
        }
    )
    client = TestClient(build_server_app(FakeAgent(), settings=settings))

    assert client.post("/api/v1/chat", json={"message": "hello"}).status_code == 401
    token = jwt.encode(
        {
            "sub": "operator",
            "tenant_id": "tenant-a",
            "roles": ["service_agent"],
            "iss": "issuer",
            "aud": "audience",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "s" * 32,
        algorithm="HS256",
    )
    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hello"},
    )
    assert response.status_code == 200
