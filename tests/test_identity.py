from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from src.app.infrastructure.postgres import Base
from src.app.main import create_app
from src.app.security.auth import JWTAuthenticator
from src.app.security.identity import (
    SqlAlchemyIdentityRepository,
    hash_password,
    verify_password,
)

SECRET = "s" * 48


def repository() -> SqlAlchemyIdentityRepository:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return SqlAlchemyIdentityRepository("sqlite://", engine=engine)


def test_password_hash_is_not_reversible_and_verifies() -> None:
    encoded = hash_password("correct horse battery")

    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("wrong password", encoded)
    assert encoded != hash_password("correct horse battery")


def test_login_issues_tenant_scoped_token_and_rejects_wrong_tenant() -> None:
    identity = repository()
    identity.upsert_tenant("tenant-a", "a", "Tenant A")
    identity.upsert_tenant("tenant-b", "b", "Tenant B")
    identity.upsert_user("u-1", "user@example.com", "User", "correct horse battery")
    identity.upsert_membership("u-1", "tenant-a", "customer")
    identity.upsert_membership("u-1", "tenant-b", "service_agent")
    authenticator = JWTAuthenticator(secret=SECRET, issuer="issuer", audience="aud")
    app = create_app(authenticator=authenticator, identity_repository=identity)

    with TestClient(app) as client:
        selection = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correct horse battery"},
        )
        assert selection.status_code == 409
        assert selection.json()["code"] == "tenant_selection_required"

        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "user@example.com",
                "password": "correct horse battery",
                "tenant_id": "tenant-a",
            },
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        claims = authenticator.authenticate(token)
        assert claims.subject == "u-1"
        assert claims.tenant_id == "tenant-a"
        assert claims.roles == ["customer"]

        wrong_scope = client.get(
            "/api/v1/runs",
            headers={"Authorization": f"Bearer {token}", "x-tenant-id": "tenant-b"},
        )
        assert wrong_scope.status_code == 403

    identity.close()
