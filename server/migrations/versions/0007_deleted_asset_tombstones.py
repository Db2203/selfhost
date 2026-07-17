"""tombstones so deleted photos survive a re-index

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17

"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deleted_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_deleted_owner_hash"),
    )
    op.create_index("ix_deleted_assets_content_hash", "deleted_assets", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_deleted_assets_content_hash", table_name="deleted_assets")
    op.drop_table("deleted_assets")
