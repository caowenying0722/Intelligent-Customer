from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.app.security.auth import (
    AuthenticationError,
    AuthorizationError,
    JWTAuthenticator,
    require_role,
    require_tenant,
)


SECRET = "x" * 32


def _token(**overrides):
    payload = {
        "sub": "user-1", "tenant_id": "tenant-a", "roles": ["service_agent"],
        "iss": "issuer", "aud": "audience",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_authenticator_validates_claims_and_scope():
    auth = JWTAuthenticator(secret=SECRET, issuer="issuer", audience="audience")
    claims = auth.authenticate(_token())
    require_role(claims, ["service_agent"])
    require_tenant(claims, "tenant-a")


def test_authenticator_rejects_expired_or_missing_token():
    auth = JWTAuthenticator(secret=SECRET, issuer="issuer", audience="audience")
    with pytest.raises(AuthenticationError):
        auth.authenticate(None)
    with pytest.raises(AuthenticationError):
        auth.authenticate(_token(exp=datetime.now(timezone.utc) - timedelta(seconds=1)))


def test_authorization_rejects_wrong_role_or_tenant():
    claims = JWTAuthenticator(secret=SECRET, issuer="issuer", audience="audience").authenticate(_token())
    with pytest.raises(AuthorizationError):
        require_role(claims, ["admin"])
    with pytest.raises(AuthorizationError):
        require_tenant(claims, "tenant-b")
