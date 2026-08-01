from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.app.security.auth import JWTAuthenticator
from src.app.security.dependencies import auth_dependency, role_dependency, tenant_dependency


SECRET = "x" * 32


def token(roles=None, tenant="tenant-a"):
    return jwt.encode(
        {
            "sub": "u", "tenant_id": tenant, "roles": roles or ["customer"],
            "iss": "iss", "aud": "aud",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }, SECRET, algorithm="HS256"
    )


def test_dependencies_return_stable_401_403_and_tenant_scope():
    authenticator = JWTAuthenticator(secret=SECRET, issuer="iss", audience="aud")
    app = FastAPI()
    auth = auth_dependency(authenticator)
    admin = role_dependency(authenticator, {"admin"})
    tenant = tenant_dependency(authenticator)

    @app.get("/auth")
    async def auth_route(claims=Depends(auth)):
        return {"tenant": claims.tenant_id}

    @app.get("/admin")
    async def admin_route(claims=Depends(admin)):
        return {"ok": True}

    @app.get("/tenant")
    async def tenant_route(claims=Depends(tenant)):
        return {"tenant": claims.tenant_id}

    client = TestClient(app)
    assert client.get("/auth").status_code == 401
    assert client.get("/auth", headers={"Authorization": "Bearer " + token()}).status_code == 200
    assert client.get("/admin", headers={"Authorization": "Bearer " + token()}).status_code == 403
    headers = {"Authorization": "Bearer " + token(), "x-tenant-id": "tenant-b"}
    assert client.get("/tenant", headers=headers).status_code == 403
