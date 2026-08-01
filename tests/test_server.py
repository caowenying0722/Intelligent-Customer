from typing import cast

from fastapi.testclient import TestClient

from agent.tools.agent_tools import RagService
from src.app.server import build_server_app


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
