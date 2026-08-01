"""add document and ingestion job persistence tables"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_documents_and_ingestion_jobs"
down_revision = "0007_add_run_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("storage_name", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("chunker_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("storage_name"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_tenant_hash", "documents", ["tenant_id", "content_hash"], unique=True)
    op.create_index("ix_documents_tenant_status_created", "documents", ["tenant_id", "status", "created_at"])
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error", sa.String(length=4000), nullable=True),
        sa.Column("result_ref", sa.String(length=512), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_tenant_id", "ingestion_jobs", ["tenant_id"])
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"])
    op.create_index("ux_ingestion_jobs_tenant_idempotency", "ingestion_jobs", ["tenant_id", "idempotency_key"], unique=True)
    op.create_index("ix_ingestion_jobs_tenant_status_created", "ingestion_jobs", ["tenant_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_tenant_status_created", table_name="ingestion_jobs")
    op.drop_index("ux_ingestion_jobs_tenant_idempotency", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_document_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_tenant_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_documents_tenant_status_created", table_name="documents")
    op.drop_index("ix_documents_tenant_hash", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_table("documents")
