"""Durable local identity and tenant membership support.

This module is intentionally provider-neutral: the local password flow is useful
for development and controlled deployments, while the resulting JWT claims are
the same claims an OIDC/SSO adapter can issue later.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.app.infrastructure.postgres import Base

_SALT_BYTES = 16
_KEY_BYTES = 64
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


class IdentityError(RuntimeError):
    """Base error for safe authentication failures."""


class InvalidCredentials(IdentityError):
    """The username/password pair is not valid."""


class TenantSelectionRequired(IdentityError):
    """The user belongs to multiple tenants and must select one."""

    def __init__(self, memberships: list[MembershipInfo]) -> None:
        super().__init__("tenant selection required")
        self.memberships = memberships


@dataclass(frozen=True)
class MembershipInfo:
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    role: str


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str
    display_name: str
    membership: MembershipInfo
    memberships: tuple[MembershipInfo, ...]


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MembershipRow(Base):
    __tablename__ = "tenant_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )
    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


class SqlAlchemyIdentityRepository:
    def __init__(self, database_url: str, *, engine=None) -> None:
        if engine is not None:
            self.engine = engine
            self._owns_engine = False
            return
        parsed = urlparse(database_url)
        options: dict[str, object] = {"future": True}
        if parsed.scheme.startswith("postgresql"):
            options["connect_args"] = {"connect_timeout": 10}
        self.engine = create_engine(database_url, **options)
        self._owns_engine = True

    def close(self) -> None:
        if self._owns_engine:
            self.engine.dispose()

    def memberships_for(self, user_id: str) -> list[MembershipInfo]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(MembershipRow, TenantRow)
                .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
                .where(
                    MembershipRow.user_id == user_id,
                    MembershipRow.status == "active",
                    TenantRow.status == "active",
                )
                .order_by(TenantRow.name)
            ).all()
            return [
                MembershipInfo(
                    tenant_id=membership.tenant_id,
                    tenant_slug=tenant.slug,
                    tenant_name=tenant.name,
                    role=membership.role,
                )
                for membership, tenant in rows
            ]

    def authenticate(
        self, email: str, password: str, tenant_id: str | None = None
    ) -> AuthenticatedUser:
        normalized_email = email.strip().lower()
        with Session(self.engine) as session:
            user = session.scalar(
                select(UserRow).where(UserRow.email == normalized_email)
            )
            valid = (
                user is not None
                and user.status == "active"
                and verify_password(password, user.password_hash)
            )
            if not valid:
                raise InvalidCredentials("invalid credentials")
            rows = session.execute(
                select(MembershipRow, TenantRow)
                .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
                .where(
                    MembershipRow.user_id == user.id,
                    MembershipRow.status == "active",
                    TenantRow.status == "active",
                )
                .order_by(TenantRow.name)
            ).all()
            memberships = [
                MembershipInfo(
                    tenant_id=membership.tenant_id,
                    tenant_slug=tenant.slug,
                    tenant_name=tenant.name,
                    role=membership.role,
                )
                for membership, tenant in rows
            ]
            if not memberships:
                raise InvalidCredentials("invalid credentials")
            selected = [item for item in memberships if item.tenant_id == tenant_id]
            if tenant_id is None:
                if len(memberships) != 1:
                    raise TenantSelectionRequired(memberships)
                selected = memberships[:1]
            if not selected:
                raise InvalidCredentials("invalid credentials")
            return AuthenticatedUser(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                membership=selected[0],
                memberships=tuple(memberships),
            )

    def upsert_tenant(self, tenant_id: str, slug: str, name: str) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            row = session.get(TenantRow, tenant_id)
            if row is None:
                session.add(
                    TenantRow(
                        id=tenant_id,
                        slug=slug,
                        name=name,
                        status="active",
                        created_at=now,
                    )
                )
            else:
                row.slug, row.name, row.status = slug, name, "active"
            session.commit()

    def upsert_user(
        self, user_id: str, email: str, display_name: str, password: str
    ) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            row = session.get(UserRow, user_id)
            if row is None:
                session.add(
                    UserRow(
                        id=user_id,
                        email=email.strip().lower(),
                        display_name=display_name,
                        password_hash=hash_password(password),
                        status="active",
                        created_at=now,
                    )
                )
            else:
                row.email = email.strip().lower()
                row.display_name = display_name
                row.password_hash = hash_password(password)
                row.status = "active"
            session.commit()

    def upsert_membership(self, user_id: str, tenant_id: str, role: str) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            row = session.scalar(
                select(MembershipRow).where(
                    MembershipRow.user_id == user_id,
                    MembershipRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                session.add(
                    MembershipRow(
                        id=secrets.token_hex(16),
                        user_id=user_id,
                        tenant_id=tenant_id,
                        role=role,
                        status="active",
                        created_at=now,
                    )
                )
            else:
                row.role, row.status = role, "active"
            session.commit()
