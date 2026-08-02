from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.app.infrastructure.approvals import SqlAlchemyApprovalRepository
from src.app.infrastructure.postgres import Base, SqlAlchemyConversationRepository


def test_sqlalchemy_approval_is_idempotent_and_tenant_scoped() -> None:
    conversations = SqlAlchemyConversationRepository(
        "sqlite+pysqlite:///:memory:", initialize_schema=True
    )
    Base.metadata.create_all(conversations.engine)
    approvals = SqlAlchemyApprovalRepository(conversations.engine)
    conversation = conversations.create("tenant-a")
    run = conversations.create_run("tenant-a", conversation.conversation_id)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    first = approvals.request(
        tenant_id="tenant-a",
        conversation_id=conversation.conversation_id,
        run_id=run.run_id,
        interrupt_id="interrupt-1",
        tool_name="mutate",
        arguments={"value": "x"},
        risk_level="high",
        idempotency_key="key-1",
        expires_at=expires_at,
    )
    repeated = approvals.request(
        tenant_id="tenant-a",
        conversation_id=conversation.conversation_id,
        run_id=run.run_id,
        interrupt_id="interrupt-1",
        tool_name="mutate",
        arguments={"value": "x"},
        risk_level="high",
        idempotency_key="key-1",
        expires_at=expires_at,
    )

    assert repeated.approval_id == first.approval_id
    assert approvals.get("tenant-b", first.approval_id) is None
    decision = approvals.decide(
        "tenant-a",
        first.approval_id,
        approved=True,
        decided_by="approver",
        decided_at=datetime.now(timezone.utc),
    )
    completed = approvals.mark_execution("tenant-a", first.approval_id, "completed")
    assert decision.changed is True
    assert completed.execution_status == "completed"
    conversations.close()
