"""Durable human-approval contracts for high-risk Agent tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]
ExecutionStatus = Literal["not_started", "running", "completed", "failed", "denied"]


def canonical_arguments(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded.encode("utf-8")) > 8_000:
        raise ValueError("approval arguments exceed the size limit")
    return encoded


@dataclass
class ApprovalRequired(RuntimeError):
    interrupt_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str = "high"

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "human approval is required")


@dataclass(frozen=True)
class HumanApproval:
    approval_id: UUID
    tenant_id: str
    conversation_id: UUID
    run_id: UUID
    interrupt_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str
    status: ApprovalStatus = "pending"
    execution_status: ExecutionStatus = "not_started"
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=15)
    )
    decided_at: datetime | None = None
    decided_by: str | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class ApprovalDecision:
    approval: HumanApproval
    changed: bool


class ApprovalNotFound(KeyError):
    pass


class ApprovalStateConflict(RuntimeError):
    pass


class ApprovalRepositoryProtocol(Protocol):
    def request(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        run_id: UUID,
        interrupt_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        idempotency_key: str,
        expires_at: datetime,
    ) -> HumanApproval: ...

    def get(self, tenant_id: str, approval_id: UUID) -> HumanApproval | None: ...

    def decide(
        self,
        tenant_id: str,
        approval_id: UUID,
        *,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
    ) -> ApprovalDecision: ...

    def mark_execution(
        self,
        tenant_id: str,
        approval_id: UUID,
        status: ExecutionStatus,
    ) -> HumanApproval: ...

    def close(self) -> None: ...


class InMemoryApprovalRepository:
    """Thread-safe development adapter with the same state rules as PostgreSQL."""

    def __init__(self) -> None:
        self._items: dict[UUID, HumanApproval] = {}
        self._by_interrupt: dict[tuple[str, str], UUID] = {}
        self._by_idempotency: dict[tuple[str, str], UUID] = {}
        self._lock = Lock()

    def request(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        run_id: UUID,
        interrupt_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        idempotency_key: str,
        expires_at: datetime,
    ) -> HumanApproval:
        canonical_arguments(arguments)
        with self._lock:
            existing_id = self._by_interrupt.get((tenant_id, interrupt_id))
            if existing_id is None:
                existing_id = self._by_idempotency.get((tenant_id, idempotency_key))
            if existing_id is not None:
                return self._items[existing_id]
            approval = HumanApproval(
                approval_id=uuid4(),
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=run_id,
                interrupt_id=interrupt_id,
                tool_name=tool_name,
                arguments=dict(arguments),
                risk_level=risk_level,
                idempotency_key=idempotency_key,
                expires_at=expires_at,
            )
            self._items[approval.approval_id] = approval
            self._by_interrupt[(tenant_id, interrupt_id)] = approval.approval_id
            self._by_idempotency[(tenant_id, idempotency_key)] = approval.approval_id
            return approval

    def get(self, tenant_id: str, approval_id: UUID) -> HumanApproval | None:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.tenant_id != tenant_id:
                return None
            return approval

    def decide(
        self,
        tenant_id: str,
        approval_id: UUID,
        *,
        approved: bool,
        decided_by: str,
        decided_at: datetime,
    ) -> ApprovalDecision:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.tenant_id != tenant_id:
                raise ApprovalNotFound(approval_id)
            if approval.status == "pending" and decided_at >= approval.expires_at:
                expired = replace(approval, status="expired")
                self._items[approval_id] = expired
                raise ApprovalStateConflict("approval expired")
            desired: ApprovalStatus = "approved" if approved else "rejected"
            if approval.status == desired:
                return ApprovalDecision(approval, changed=False)
            if approval.status != "pending":
                raise ApprovalStateConflict("approval already decided")
            updated = replace(
                approval,
                status=desired,
                execution_status="not_started" if approved else "denied",
                decided_at=decided_at,
                decided_by=decided_by,
            )
            self._items[approval_id] = updated
            return ApprovalDecision(updated, changed=True)

    def mark_execution(
        self,
        tenant_id: str,
        approval_id: UUID,
        status: ExecutionStatus,
    ) -> HumanApproval:
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid execution status")
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.tenant_id != tenant_id:
                raise ApprovalNotFound(approval_id)
            if approval.status != "approved":
                raise ApprovalStateConflict("approval is not approved")
            if approval.execution_status == "completed":
                return approval
            updated = replace(approval, execution_status=status)
            self._items[approval_id] = updated
            return updated

    def close(self) -> None:
        return None
