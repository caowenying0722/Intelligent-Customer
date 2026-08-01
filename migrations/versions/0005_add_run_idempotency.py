"""add agent run idempotency key"""

import sqlalchemy as sa
from alembic import op

revision = "0005_add_run_idempotency"
down_revision = "0004_add_agent_run_error"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("idempotency_key", sa.String(length=128), nullable=True)
    )
    op.create_index(
        "uq_agent_runs_tenant_idempotency",
        "agent_runs",
        ["tenant_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_tenant_idempotency", table_name="agent_runs")
    op.drop_column("agent_runs", "idempotency_key")
