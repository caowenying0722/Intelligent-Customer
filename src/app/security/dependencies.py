"""FastAPI dependency factories for authentication, roles, and tenant scope."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from src.app.security.audit import (
    AuditSink,
    LoggingAuditSink,
    SecurityAuditEvent,
    actor_hash,
    record_safely,
)
from src.app.security.auth import (
    AuthenticationError,
    AuthorizationError,
    JWTAuthenticator,
    TokenClaims,
    require_role,
    require_tenant,
)


def auth_dependency(
    authenticator: JWTAuthenticator, audit_sink: AuditSink | None = None
):
    sink = audit_sink or LoggingAuditSink()

    async def dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="x-tenant-id"),
    ) -> TokenClaims:
        token = None
        if authorization is not None:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() != "bearer" or not value.strip():
                record_safely(
                    sink,
                    SecurityAuditEvent(
                        event_type="auth.failure",
                        outcome="denied",
                        request_id=getattr(request.state, "request_id", None),
                        reason="invalid_authorization_header",
                    ),
                )
                raise HTTPException(
                    status_code=401, detail="invalid authorization header"
                )
            token = value.strip()
        try:
            claims = authenticator.authenticate(token)
            if tenant_id is not None and tenant_id != claims.tenant_id:
                record_safely(
                    sink,
                    SecurityAuditEvent(
                        event_type="auth.failure",
                        outcome="denied",
                        request_id=getattr(request.state, "request_id", None),
                        tenant_id=claims.tenant_id,
                        subject_hash=actor_hash(claims.subject),
                        roles=tuple(sorted(claims.roles)),
                        reason="tenant_scope_mismatch",
                    ),
                )
                raise HTTPException(status_code=403, detail="tenant scope mismatch")
            request.state.tenant_id = claims.tenant_id
            request.state.auth_claims = claims
            record_safely(
                sink,
                SecurityAuditEvent(
                    event_type="auth.success",
                    outcome="allowed",
                    request_id=getattr(request.state, "request_id", None),
                    tenant_id=claims.tenant_id,
                    subject_hash=actor_hash(claims.subject),
                    roles=tuple(sorted(claims.roles)),
                ),
            )
            return claims
        except AuthenticationError as exc:
            record_safely(
                sink,
                SecurityAuditEvent(
                    event_type="auth.failure",
                    outcome="denied",
                    request_id=getattr(request.state, "request_id", None),
                    reason="missing_token" if token is None else "invalid_access_token",
                ),
            )
            raise HTTPException(status_code=401, detail="invalid access token") from exc

    return dependency


def role_dependency(
    authenticator: JWTAuthenticator,
    roles: set[str],
    audit_sink: AuditSink | None = None,
):
    sink = audit_sink or LoggingAuditSink()
    authenticate = auth_dependency(authenticator, sink)

    async def dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="x-tenant-id"),
    ) -> TokenClaims:
        claims = await authenticate(request, authorization, tenant_id)
        try:
            require_role(claims, roles)
        except AuthorizationError as exc:
            record_safely(
                sink,
                SecurityAuditEvent(
                    event_type="authorization.failure",
                    outcome="denied",
                    request_id=getattr(request.state, "request_id", None),
                    tenant_id=claims.tenant_id,
                    subject_hash=actor_hash(claims.subject),
                    roles=tuple(sorted(claims.roles)),
                    reason="insufficient_role",
                ),
            )
            raise HTTPException(status_code=403, detail="insufficient role") from exc
        return claims

    return dependency


def role_guard(roles: set[str], audit_sink: AuditSink | None = None):
    """Authorize a route after the router-level JWT dependency has run."""

    sink = audit_sink or LoggingAuditSink()

    async def dependency(request: Request) -> TokenClaims:
        claims = getattr(request.state, "auth_claims", None)
        if not isinstance(claims, TokenClaims):
            raise HTTPException(status_code=401, detail="invalid access token")
        try:
            require_role(claims, roles)
        except AuthorizationError as exc:
            record_safely(
                sink,
                SecurityAuditEvent(
                    event_type="authorization.failure",
                    outcome="denied",
                    request_id=getattr(request.state, "request_id", None),
                    tenant_id=claims.tenant_id,
                    subject_hash=actor_hash(claims.subject),
                    roles=tuple(sorted(claims.roles)),
                    reason="insufficient_role",
                ),
            )
            raise HTTPException(status_code=403, detail="insufficient role") from exc
        return claims

    return dependency


def tenant_dependency(
    authenticator: JWTAuthenticator,
    tenant_header: str = "x-tenant-id",
    audit_sink: AuditSink | None = None,
):
    sink = audit_sink or LoggingAuditSink()
    authenticate = auth_dependency(authenticator, sink)

    async def dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias=tenant_header),
    ) -> TokenClaims:
        claims = await authenticate(request, authorization, tenant_id)
        try:
            require_tenant(claims, tenant_id or "")
        except AuthorizationError as exc:
            record_safely(
                sink,
                SecurityAuditEvent(
                    event_type="authorization.failure",
                    outcome="denied",
                    request_id=getattr(request.state, "request_id", None),
                    tenant_id=claims.tenant_id,
                    subject_hash=actor_hash(claims.subject),
                    roles=tuple(sorted(claims.roles)),
                    reason="tenant_scope_mismatch",
                ),
            )
            raise HTTPException(
                status_code=403, detail="tenant scope mismatch"
            ) from exc
        return claims

    return dependency
