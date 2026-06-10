"""asset embeddings for natural-language search

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-10

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 512


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.add_column("assets", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
        op.execute(
            "CREATE INDEX ix_assets_embedding ON assets"
            " USING hnsw (embedding vector_cosine_ops)"
        )
    else:
        # SQLite (local tests only): store the vector as JSON; similarity is
        # computed in Python for this backend.
        op.add_column("assets", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_assets_embedding")
    op.drop_column("assets", "embedding")
