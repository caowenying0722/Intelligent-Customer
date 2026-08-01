"""add agent run timing fields"""

import sqlalchemy as sa
from alembic import op

revision = "0006_add_run_timing"
down_revision = "0005_add_run_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_runs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "completed_at")
    op.drop_column("agent_runs", "started_at")
