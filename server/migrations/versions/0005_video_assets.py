"""video assets: duration and web-safe playback rendition

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17

"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("duration_seconds", sa.Float(), nullable=True))
    # Path of the transcoded H.264 rendition in media storage; NULL when the
    # original is already web-safe. transcoded_at records that the decision
    # ran (NULL = video not considered yet).
    op.add_column("assets", sa.Column("playback_path", sa.String(1024), nullable=True))
    op.add_column("assets", sa.Column("transcoded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "transcoded_at")
    op.drop_column("assets", "playback_path")
    op.drop_column("assets", "duration_seconds")
