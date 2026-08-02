"""add durable human approval records"""

import sqlalchemy as sa
from alembic import op

revision = "0011_add_human_approvals"
down_revision = "0010_add_ingestion_job_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("interrupt_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_human_approvals_tenant_id", "human_approvals", ["tenant_id"])
    op.create_index(
        "ux_human_approvals_tenant_interrupt",
        "human_approvals",
        ["tenant_id", "interrupt_id"],
        unique=True,
    )
    op.create_index(
        "ux_human_approvals_tenant_idempotency",
        "human_approvals",
        ["tenant_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_human_approvals_tenant_status_expires",
        "human_approvals",
        ["tenant_id", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_human_approvals_tenant_status_expires", table_name="human_approvals"
    )
    op.drop_index("ux_human_approvals_tenant_idempotency", table_name="human_approvals")
    op.drop_index("ux_human_approvals_tenant_interrupt", table_name="human_approvals")
    op.drop_index("ix_human_approvals_tenant_id", table_name="human_approvals")
    op.drop_table("human_approvals")
