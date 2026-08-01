"""JWT validation and role/tenant authorization boundary."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field


class AuthenticationError(RuntimeError):
    """Token missing, malformed, expired, or otherwise invalid."""


class AuthorizationError(RuntimeError):
    """Token is valid but lacks the required role or tenant scope."""


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)
    issuer: str
    audience: str | list[str]
    expires_at: int


class JWTAuthenticator:
    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        if len(secret) < 32 or not issuer.strip() or not audience.strip():
            raise ValueError("JWT secret, issuer and audience are required")
        self.secret = secret
        self.issuer = issuer
        self.audience = audience

    def authenticate(self, token: str | None) -> TokenClaims:
        if not token:
            raise AuthenticationError("authentication required")
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub", "tenant_id"]},
            )
            claims = TokenClaims(
                subject=payload["sub"],
                tenant_id=payload["tenant_id"],
                roles=payload.get("roles", []),
                issuer=payload["iss"],
                audience=payload["aud"],
                expires_at=payload["exp"],
            )
            if claims.expires_at <= int(datetime.now(timezone.utc).timestamp()):
                raise AuthenticationError("token expired")
            return claims
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("invalid access token") from exc


def require_role(claims: TokenClaims, roles: Iterable[str]) -> None:
    allowed = set(roles)
    if not allowed.intersection(claims.roles):
        raise AuthorizationError("insufficient role")


def require_tenant(claims: TokenClaims, tenant_id: str) -> None:
    if claims.tenant_id != tenant_id:
        raise AuthorizationError("tenant scope mismatch")
