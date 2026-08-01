"""persist bounded payload for recoverable task types"""

import sqlalchemy as sa
from alembic import op

revision = "0010_add_ingestion_job_payload"
down_revision = "0009_add_ingestion_job_task_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("task_payload", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "task_payload")
