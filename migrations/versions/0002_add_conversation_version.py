"""add optimistic conversation version"""

import sqlalchemy as sa
from alembic import op

revision = "0002_add_conversation_version"
down_revision = "0001_create_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("conversations", "version")
