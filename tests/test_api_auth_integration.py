from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from src.app.application.chat import ChatApplicationService
from src.app.main import create_app
from src.app.security.audit import InMemoryAuditSink
from src.app.security.auth import JWTAuthenticator


class Agent:
    def run(self, message: str) -> str:
        return message

    def stream(self, message: str) -> list[str]:
        return [message]


def test_api_router_requires_configured_authenticator():
    secret = "x" * 32
    auth = JWTAuthenticator(secret=secret, issuer="iss", audience="aud")
    client = TestClient(
        create_app(chat_service=ChatApplicationService(Agent()), authenticator=auth)
    )
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401
    token = jwt.encode(
        {
            "sub": "u",
            "tenant_id": "t",
            "roles": ["customer"],
            "iss": "iss",
            "aud": "aud",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi"},
    )
    assert response.status_code == 200
    conversation = response.json()["conversation_id"]
    assert (
        client.get(
            f"/api/v1/conversations/{conversation}",
            headers={"Authorization": f"Bearer {token}", "x-tenant-id": "tenant-b"},
        ).status_code
        == 403
    )


def test_api_auth_and_audit_sink_work_together() -> None:
    secret = "y" * 32
    auth = JWTAuthenticator(secret=secret, issuer="iss", audience="aud")
    sink = InMemoryAuditSink()
    client = TestClient(
        create_app(
            chat_service=ChatApplicationService(Agent()),
            authenticator=auth,
            audit_sink=sink,
        )
    )
    token = jwt.encode(
        {
            "sub": "user@example.com",
            "tenant_id": "tenant-a",
            "roles": ["customer"],
            "iss": "iss",
            "aud": "aud",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )

    assert client.post("/api/v1/chat").status_code == 401
    assert (
        client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}", "x-tenant-id": "tenant-a"},
            json={"message": "hello"},
        ).status_code
        == 200
    )

    events = sink.snapshot()
    assert events[0].event_type == "auth.failure"
    assert events[-1].event_type == "auth.success"
    assert all("user@example.com" not in str(event.as_dict()) for event in events)
    assert all(token not in str(event.as_dict()) for event in events)


def test_mutating_routes_require_operator_role() -> None:
    secret = "z" * 32
    auth = JWTAuthenticator(secret=secret, issuer="iss", audience="aud")
    client = TestClient(create_app(authenticator=auth))

    def make_token(roles: list[str]) -> str:
        return jwt.encode(
            {
                "sub": "u",
                "tenant_id": "tenant-a",
                "roles": roles,
                "iss": "iss",
                "aud": "aud",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            secret,
            algorithm="HS256",
        )

    customer = {"Authorization": f"Bearer {make_token(['customer'])}"}
    operator = {"Authorization": f"Bearer {make_token(['service_agent'])}"}
    payload = {
        "filename": "manual.txt",
        "content_base64": "aGVsbG8=",
        "content_type": "text/plain",
        "idempotency_key": "auth-role-1",
    }

    assert (
        client.post("/api/v1/documents", headers=customer, json=payload).status_code
        == 403
    )
    assert (
        client.post("/api/v1/documents", headers=operator, json=payload).status_code
        == 503
    )
