"""SQLAlchemy adapter for durable human approvals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.app.domain.approvals import (
    ApprovalDecision,
    ApprovalNotFound,
    ApprovalStateConflict,
    ExecutionStatus,
    HumanApproval,
    canonical_arguments,
)
from src.app.infrastructure.postgres import Base


class HumanApprovalRow(Base):
    __tablename__ = "human_approvals"
    __table_args__ = (
        Index(
            "ux_human_approvals_tenant_interrupt",
            "tenant_id",
            "interrupt_id",
            unique=True,
        ),
        Index(
            "ux_human_approvals_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_human_approvals_tenant_status_expires",
            "tenant_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    interrupt_id: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(128))
    arguments_json: Mapped[str] = mapped_column(Text())
    risk_level: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    execution_status: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _to_domain(row: HumanApprovalRow) -> HumanApproval:
    return HumanApproval(
        approval_id=UUID(row.id),
        tenant_id=row.tenant_id,
        conversation_id=UUID(row.conversation_id),
        run_id=UUID(row.run_id),
        interrupt_id=row.interrupt_id,
        tool_name=row.tool_name,
        arguments=json.loads(row.arguments_json),
        risk_level=row.risk_level,
        status=row.status,  # type: ignore[arg-type]
        execution_status=row.execution_status,  # type: ignore[arg-type]
        requested_at=_aware(row.requested_at),
        expires_at=_aware(row.expires_at),
        decided_at=_aware(row.decided_at) if row.decided_at is not None else None,
        decided_by=row.decided_by,
        idempotency_key=row.idempotency_key,
    )


class SqlAlchemyApprovalRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _find_existing(
        self, session: Session, tenant_id: str, interrupt_id: str, idempotency_key: str
    ) -> HumanApprovalRow | None:
        return session.scalar(
            select(HumanApprovalRow).where(
                HumanApprovalRow.tenant_id == tenant_id,
                (
                    (HumanApprovalRow.interrupt_id == interrupt_id)
                    | (HumanApprovalRow.idempotency_key == idempotency_key)
                ),
            )
        )

    def request(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        run_id: UUID,
        interrupt_id: str,
        tool_name: str,
        arguments: dict[str, object],
        risk_level: str,
        idempotency_key: str,
        expires_at: datetime,
    ) -> HumanApproval:
        arguments_json = canonical_arguments(arguments)
        with Session(self.engine) as session:
            existing = self._find_existing(
                session, tenant_id, interrupt_id, idempotency_key
            )
            if existing is not None:
                return _to_domain(existing)
            row = HumanApprovalRow(
                id=str(uuid4()),
                tenant_id=tenant_id,
                conversation_id=str(conversation_id),
                run_id=str(run_id),
                interrupt_id=interrupt_id,
                tool_name=tool_name,
                arguments_json=arguments_json,
                risk_level=risk_level,
                status="pending",
                execution_status="not_started",
                requested_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                idempotency_key=idempotency_key,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._find_existing(
                    session, tenant_id, interrupt_id, idempotency_key
                )
                if existing is None:
                    raise
                return _to_domain(existing)
            return _to_domain(row)

    def get(self, tenant_id: str, approval_id: UUID) -> HumanApproval | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(HumanApprovalRow).where(
                    HumanApprovalRow.id == str(approval_id),
                    HumanApprovalRow.tenant_id == tenant_id,
                )
            )
            return _to_domain(row) if row is not None else None

    def decide(
        self,
        tenant_id: str,
        approval_id: UUID,
        *,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
    ) -> ApprovalDecision:
        with Session(self.engine) as session:
            row = session.scalar(
                select(HumanApprovalRow)
                .where(
                    HumanApprovalRow.id == str(approval_id),
                    HumanApprovalRow.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ApprovalNotFound(approval_id)
            if row.status == "pending" and decided_at >= _aware(row.expires_at):
                row.status = "expired"
                session.commit()
                raise ApprovalStateConflict("approval expired")
            desired = "approved" if approved else "rejected"
            if row.status == desired:
                return ApprovalDecision(_to_domain(row), changed=False)
            if row.status != "pending":
                raise ApprovalStateConflict("approval already decided")
            row.status = desired
            row.execution_status = "not_started" if approved else "denied"
            row.decided_at = decided_at
            row.decided_by = decided_by
            session.commit()
            return ApprovalDecision(_to_domain(row), changed=True)

    def mark_execution(
        self,
        tenant_id: str,
        approval_id: UUID,
        status: ExecutionStatus,
    ) -> HumanApproval:
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid execution status")
        with Session(self.engine) as session:
            row = session.scalar(
                select(HumanApprovalRow)
                .where(
                    HumanApprovalRow.id == str(approval_id),
                    HumanApprovalRow.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ApprovalNotFound(approval_id)
            if row.status != "approved":
                raise ApprovalStateConflict("approval is not approved")
            if row.execution_status == "completed":
                return _to_domain(row)
            row.execution_status = status
            session.commit()
            return _to_domain(row)

    def close(self) -> None:
        # The conversation repository owns and closes the shared engine.
        return None
