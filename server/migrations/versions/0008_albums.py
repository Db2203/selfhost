"""albums

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-17

"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "albums",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "album_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "album_id",
            sa.Uuid(),
            sa.ForeignKey("albums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("album_id", "asset_id", name="uq_album_asset"),
    )
    op.create_index("ix_album_assets_album_id", "album_assets", ["album_id"])
    op.create_index("ix_album_assets_asset_id", "album_assets", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_album_assets_asset_id", table_name="album_assets")
    op.drop_index("ix_album_assets_album_id", table_name="album_assets")
    op.drop_table("album_assets")
    op.drop_table("albums")
