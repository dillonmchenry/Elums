"""pgvector_song_embeddings

Revision ID: a3e5f7c9b1d2
Revises: f1a9c6b2e4d1
Create Date: 2026-10-06 09:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = 'a3e5f7c9b1d2'
down_revision: Union[str, None] = 'f1a9c6b2e4d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EC-5: the `pgvector/pgvector:pg18` image ships the extension's
    # files but never runs CREATE EXTENSION itself.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "song_embeddings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("song_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_song_embeddings_song_id", "song_embeddings", ["song_id"])
    # Deliberately NO HNSW index today — Sunday's bulk-load milestone
    # builds it (hnsw.iterative_scan = relaxed_order, then ANALYZE), per
    # §8.1 and this plan's own T5 instruction.


def downgrade() -> None:
    op.drop_index("ix_song_embeddings_song_id", table_name="song_embeddings")
    op.drop_table("song_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
