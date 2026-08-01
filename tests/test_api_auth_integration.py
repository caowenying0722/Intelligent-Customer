from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from src.app.application.chat import ChatApplicationService
from src.app.main import create_app
from src.app.security.auth import JWTAuthenticator


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_api_router_requires_configured_authenticator():
    secret = "x" * 32
    auth = JWTAuthenticator(secret=secret, issuer="iss", audience="aud")
    client = TestClient(create_app(chat_service=ChatApplicationService(Agent()), authenticator=auth))
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401
    token = jwt.encode(
        {"sub": "u", "tenant_id": "t", "roles": ["customer"], "iss": "iss", "aud": "aud", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        secret, algorithm="HS256",
    )
    response = client.post(
        "/api/v1/chat", headers={"Authorization": f"Bearer {token}"}, json={"message": "hi"}
    )
    assert response.status_code == 200
