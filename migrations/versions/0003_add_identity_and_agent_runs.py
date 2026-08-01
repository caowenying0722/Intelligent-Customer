"""add conversation identity and agent run tracking"""

import sqlalchemy as sa
from alembic import op

revision = "0003_add_identity_and_agent_runs"
down_revision = "0002_add_conversation_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "user_id", sa.String(length=128), nullable=False, server_default="local"
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="active"
        ),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_tenant_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_column("conversations", "status")
    op.drop_column("conversations", "user_id")
