"""CLAP embeddings — Tue Oct 6 (T5 of IMPLEMENTATION_PLAN_2026-10-06.md).
One 512-d vector per song, populated fire-and-forget after
`run_note_grid` sets the ingest job `SUCCEEDED` (a CLAP failure must
never fail an ingest job — see elums/ingest/tasks.py's `run_clap_embedding`).

No HNSW index today, per the plan's own instruction — Sunday builds it
after the bulk GTSinger-adjacent load, with
`hnsw.iterative_scan = relaxed_order` and `ANALYZE` (§8.1: filtered
recall collapses without them). A plain btree-free table today is
correct, not an oversight.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk

EMBEDDING_DIM = 512


class SongEmbedding(TimestampMixin, Base):
    __tablename__ = "song_embeddings"

    id = uuidv7_pk()

    song_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("songs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
