"""FastAPI dependency factories for authentication, roles, and tenant scope."""

from __future__ import annotations

from fastapi import Header, HTTPException

from src.app.security.auth import (
    AuthenticationError,
    AuthorizationError,
    JWTAuthenticator,
    TokenClaims,
    require_role,
    require_tenant,
)


def auth_dependency(authenticator: JWTAuthenticator):
    async def dependency(authorization: str | None = Header(default=None)) -> TokenClaims:
        token = None
        if authorization is not None:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() != "bearer" or not value.strip():
                raise HTTPException(status_code=401, detail="invalid authorization header")
            token = value.strip()
        try:
            return authenticator.authenticate(token)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail="invalid access token") from exc

    return dependency


def role_dependency(authenticator: JWTAuthenticator, roles: set[str]):
    authenticate = auth_dependency(authenticator)

    async def dependency(authorization: str | None = Header(default=None)) -> TokenClaims:
        claims = await authenticate(authorization)
        try:
            require_role(claims, roles)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail="insufficient role") from exc
        return claims

    return dependency


def tenant_dependency(authenticator: JWTAuthenticator, tenant_header: str = "x-tenant-id"):
    authenticate = auth_dependency(authenticator)

    async def dependency(
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias=tenant_header),
    ) -> TokenClaims:
        claims = await authenticate(authorization)
        try:
            require_tenant(claims, tenant_id or "")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail="tenant scope mismatch") from exc
        return claims

    return dependency
