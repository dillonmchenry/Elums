"""A single take — Wed Oct 7 (W3 of IMPLEMENTATION_PLAN_2026-10-07.md).

One row per recorded take against a song's chart. `kind` distinguishes a
solo take (`SOLO`) from one published as a joinable seed (`SEED`) and a
take recorded against someone else's seed (`JOIN`) — §7.3's "async
seed/join falls out for free" architecture: all three share this one
table and one scoring pipeline, with `parent_performance_id` the only
thing that varies.

Three content-addressed blobs, same tiering split `Stem`/`SongAnalysis`
already draw: the take audio itself (`audio_blob_sha256`), its own F0
track (`f0_blob_sha256`, binary float16, same format
`elums/ingest/f0.py::pack_f0_blob` uses), and the per-note measurement
vector plus diagnostics (`analysis_blob_sha256`, JSON — one blob per
performance per §4's "one versioned analysis blob" decision). All three
start NULL: a performance exists (and can receive chunked upload PUTs)
before any of them exist, and scoring fills them in once `complete` has
run.

`status` mirrors `IngestJob`'s own small state machine
(uploading -> scoring -> succeeded/failed) rather than inventing a
different vocabulary for the same shape of problem.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class PerformanceKind(str, enum.Enum):
    SOLO = "solo"
    SEED = "seed"
    JOIN = "join"


class PerformanceStatus(str, enum.Enum):
    UPLOADING = "uploading"
    SCORING = "scoring"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Performance(TimestampMixin, Base):
    __tablename__ = "performances"

    id = uuidv7_pk()

    song_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[PerformanceKind] = mapped_column(
        Enum(PerformanceKind, name="performance_kind", native_enum=True),
        nullable=False,
        default=PerformanceKind.SOLO,
    )
    # Self-referential: a JOIN's seed, or a SOLO later published as a SEED
    # that then gets its own JOINs. NULL for a plain solo take.
    parent_performance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("performances.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[PerformanceStatus] = mapped_column(
        Enum(PerformanceStatus, name="performance_status", native_enum=True),
        nullable=False,
        default=PerformanceStatus.UPLOADING,
    )
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Three content-addressed blobs — nullable until each exists.
    audio_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )
    f0_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )
    analysis_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )

    # W4's frozen queryable summary fields (the full per-note vector lives
    # in the analysis blob — §4's tiering rule again).
    score_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_in_tune: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrival_offset_ms_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    octave_shift_semitones: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alignment_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Timing/device metadata captured client-side (§10.1/§7.4) — not
    # measured server-side; `offset_s` is W4's own GCC-free voicing-mask
    # grid-search result, `latency_offset_ms` is the client's own
    # recording-start nominal offset (§10.1's "AudioContext.currentTime
    # at record start" note), kept distinct on purpose.
    offset_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_offset_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
