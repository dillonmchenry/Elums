"""Separated audio stems — M8. One row per (song, kind): `vocals` or
`instrumental`, pointing at an immutable blob. Kept as a first-class table
(not folded into `ingest_jobs.stage_results`) because Sunday's
`all-in-one-infer` run needs to find these by `song_id` + `kind` directly
via `--stems-from-dir`, per IMPLEMENTATION_PLAN_2026-10-03.md M8.

Unique on (song_id, kind): a rerun (job killed mid-run, requeued at a
smaller segment size after OOM) upserts in place rather than
accumulating duplicate rows — the underlying blob is already
content-addressed and immutable, so only the pointer needs to move.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class StemKind(str, enum.Enum):
    VOCALS = "vocals"
    INSTRUMENTAL = "instrumental"


class Stem(TimestampMixin, Base):
    __tablename__ = "stems"
    __table_args__ = (UniqueConstraint("song_id", "kind", name="uq_stems_song_kind"),)

    id = uuidv7_pk()

    song_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[StemKind] = mapped_column(Enum(StemKind, name="stem_kind", native_enum=True), nullable=False)
    blob_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("blobs.sha256"), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
