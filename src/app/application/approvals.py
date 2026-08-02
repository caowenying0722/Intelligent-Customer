"""Application orchestration for durable human approvals."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.app.domain.approvals import (
    ApprovalDecision,
    ApprovalRepositoryProtocol,
    ApprovalRequired,
    ExecutionStatus,
    HumanApproval,
)


class ApprovalApplicationService:
    def __init__(
        self,
        repository: ApprovalRepositoryProtocol,
        *,
        ttl_seconds: float = 900,
    ) -> None:
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("approval ttl must be between 1 and 86400 seconds")
        self.repository = repository
        self.ttl_seconds = ttl_seconds

    def request(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        run_id: UUID,
        required: ApprovalRequired,
    ) -> HumanApproval:
        idempotency_key = hashlib.sha256(
            f"{tenant_id}\0{conversation_id}\0{required.interrupt_id}".encode()
        ).hexdigest()
        return self.repository.request(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            run_id=run_id,
            interrupt_id=required.interrupt_id,
            tool_name=required.tool_name,
            arguments=required.arguments,
            risk_level=required.risk_level,
            idempotency_key=idempotency_key,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
        )

    def get(self, tenant_id: str, approval_id: UUID) -> HumanApproval | None:
        return self.repository.get(tenant_id, approval_id)

    def decide(
        self,
        tenant_id: str,
        approval_id: UUID,
        *,
        approved: bool,
        decided_by: str,
    ) -> ApprovalDecision:
        return self.repository.decide(
            tenant_id,
            approval_id,
            approved=approved,
            decided_by=decided_by,
            decided_at=datetime.now(timezone.utc),
        )

    def mark_execution(
        self,
        tenant_id: str,
        approval_id: UUID,
        status: ExecutionStatus,
    ) -> HumanApproval:
        return self.repository.mark_execution(tenant_id, approval_id, status)

    def close(self) -> None:
        self.repository.close()
