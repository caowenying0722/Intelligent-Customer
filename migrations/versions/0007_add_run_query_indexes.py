"""add indexes for tenant run listing"""

from alembic import op

revision = "0007_add_run_query_indexes"
down_revision = "0006_add_run_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_runs_tenant_status_created",
        "agent_runs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_agent_runs_tenant_created", "agent_runs", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_tenant_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_status_created", table_name="agent_runs")
