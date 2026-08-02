"""add ingestion worker leases and fencing"""

import sqlalchemy as sa
from alembic import op

revision = "0012_add_ingestion_job_leases"
down_revision = "0011_add_human_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs", sa.Column("worker_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("lease_token", sa.String(36), nullable=True)
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("fence_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_ingestion_jobs_claim",
        "ingestion_jobs",
        ["status", "lease_expires_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "fence_version")
    op.drop_column("ingestion_jobs", "heartbeat_at")
    op.drop_column("ingestion_jobs", "lease_expires_at")
    op.drop_column("ingestion_jobs", "lease_token")
    op.drop_column("ingestion_jobs", "worker_id")
