"""allow persisted jobs without documents and classify job tasks"""

from alembic import op
import sqlalchemy as sa

revision = "0009_add_ingestion_job_task_type"
down_revision = "0008_add_documents_and_ingestion_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.alter_column("document_id", existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column("task_type", sa.String(length=64), nullable=False, server_default="ingestion"))


def downgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_column("task_type")
        batch.alter_column("document_id", existing_type=sa.String(length=36), nullable=False)
