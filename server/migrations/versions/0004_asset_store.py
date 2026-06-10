"""record which storage backend holds each asset's original

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-10

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "library" = the read-only mounted photo folder (indexer);
    # "uploads"  = the read-write media storage (phone backups).
    op.add_column(
        "assets",
        sa.Column("store", sa.String(16), nullable=False, server_default="library"),
    )


def downgrade() -> None:
    op.drop_column("assets", "store")
