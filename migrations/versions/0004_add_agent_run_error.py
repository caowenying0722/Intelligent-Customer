"""add agent run error details"""

import sqlalchemy as sa
from alembic import op

revision = "0004_add_agent_run_error"
down_revision = "0003_add_identity_and_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("error", sa.String(length=4000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "error")
