"""faces and people for face recognition

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10

"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 512


def _embedding_column():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        return sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True)
    return sa.Column("embedding", sa.JSON(), nullable=True)


def upgrade() -> None:
    op.add_column(
        "assets", sa.Column("faces_scanned_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "people",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "faces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            sa.Uuid(),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _embedding_column(),
        sa.Column("bbox_x", sa.Integer(), nullable=False),
        sa.Column("bbox_y", sa.Integer(), nullable=False),
        sa.Column("bbox_w", sa.Integer(), nullable=False),
        sa.Column("bbox_h", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_faces_asset_id", "faces", ["asset_id"])
    op.create_index("ix_faces_person_id", "faces", ["person_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_faces_embedding ON faces USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_faces_embedding")
    op.drop_index("ix_faces_person_id", table_name="faces")
    op.drop_index("ix_faces_asset_id", table_name="faces")
    op.drop_table("faces")
    op.drop_table("people")
    op.drop_column("assets", "faces_scanned_at")
