from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.app.security.audit import InMemoryAuditSink, SecurityAuditEvent, actor_hash
from src.app.security.auth import JWTAuthenticator
from src.app.security.dependencies import auth_dependency, role_dependency


SECRET = "s" * 32


def _token(*, tenant: str = "tenant-a", roles: list[str] | None = None) -> str:
    return jwt.encode(
        {
            "sub": "user@example.com",
            "tenant_id": tenant,
            "roles": roles or ["customer"],
            "iss": "iss",
            "aud": "aud",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def _client(dependency) -> TestClient:
    app = FastAPI()

    @app.get("/secure")
    async def secure(claims=Depends(dependency)):
        return {"tenant": claims.tenant_id}

    return TestClient(app)


def test_auth_audit_is_sanitized_and_records_outcomes() -> None:
    sink = InMemoryAuditSink(max_events=4)
    authenticator = JWTAuthenticator(secret=SECRET, issuer="iss", audience="aud")
    client = _client(auth_dependency(authenticator, sink))
    raw_token = _token()

    assert client.get("/secure").status_code == 401
    assert client.get(
        "/secure",
        headers={"Authorization": f"Bearer {raw_token}", "x-tenant-id": "tenant-b"},
    ).status_code == 403
    assert (
        client.get(
            "/secure", headers={"Authorization": f"Bearer {raw_token}"}
        ).status_code
        == 200
    )

    events = sink.snapshot()
    assert [event.event_type for event in events] == [
        "auth.failure",
        "auth.failure",
        "auth.success",
    ]
    assert events[0].reason == "missing_token"
    assert events[1].reason == "tenant_scope_mismatch"
    assert events[2].subject_hash == actor_hash("user@example.com")
    assert all(raw_token not in str(event.as_dict()) for event in events)
    assert all("user@example.com" not in str(event.as_dict()) for event in events)


def test_role_denial_is_audited_without_changing_403_contract() -> None:
    sink = InMemoryAuditSink()
    authenticator = JWTAuthenticator(secret=SECRET, issuer="iss", audience="aud")
    client = _client(role_dependency(authenticator, {"admin"}, sink))

    response = client.get("/secure", headers={"Authorization": f"Bearer {_token()}"})

    assert response.status_code == 403
    event = sink.snapshot()[-1]
    assert event.event_type == "authorization.failure"
    assert event.outcome == "denied"
    assert event.reason == "insufficient_role"


def test_in_memory_audit_sink_is_bounded() -> None:
    sink = InMemoryAuditSink(max_events=1)
    sink.record(SecurityAuditEvent(event_type="one", outcome="allowed"))
    sink.record(SecurityAuditEvent(event_type="two", outcome="denied"))

    assert [event.event_type for event in sink.snapshot()] == ["two"]
