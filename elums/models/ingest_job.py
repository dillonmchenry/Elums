"""The upload-to-karaoke-chart pipeline, M4's primary schema deliverable.

Stage order is fixed by ELUMS_TECHNICAL_APPROACH.md's pipeline diagram and
Day 1 of ELUMS_BUILD_SCHEDULE.md:

    Upload -> separation -> structure_beats -> rms_vad
                                              -> lyrics -> ctc_alignment
           -> f0 -> note_grid

`structure_beats` and `rms_vad` both consume the vocal/instrumental stems
from `separation` and can run concurrently; `lyrics` and `ctc_alignment`
are sequential (alignment needs the transcript); `f0` runs off the vocal
stem independently; `note_grid` is the final fold-in of everything above.
One row per job; one column per stage holding that stage's own status,
not a fan-out to a child table — simple enough for M4, revisited only if
a stage needs its own retry/backoff history.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class IngestJobStage(str, enum.Enum):
    SEPARATION = "separation"
    STRUCTURE_BEATS = "structure_beats"
    RMS_VAD = "rms_vad"
    LYRICS = "lyrics"
    CTC_ALIGNMENT = "ctc_alignment"
    F0 = "f0"
    NOTE_GRID = "note_grid"


STAGE_ORDER: tuple[IngestJobStage, ...] = (
    IngestJobStage.SEPARATION,
    IngestJobStage.STRUCTURE_BEATS,
    IngestJobStage.RMS_VAD,
    IngestJobStage.LYRICS,
    IngestJobStage.CTC_ALIGNMENT,
    IngestJobStage.F0,
    IngestJobStage.NOTE_GRID,
)


class IngestJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class IngestJob(TimestampMixin, Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (Index("ix_ingest_jobs_status", "status"),)

    id: Mapped[uuid.UUID] = uuidv7_pk()

    # The uploaded source file, content-addressed in the BlobStore (M7).
    # Nullable until M7 exists; M4 only needs the column to be present.
    source_blob_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)

    # FK added in M6 now that `users` exists (M4's migration shipped this
    # column without the constraint, by design — see that commit).
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Overall roll-up, derived from the per-stage columns below but kept as
    # its own column so `WHERE status = 'running'` doesn't need 7 OR clauses.
    status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )

    current_stage: Mapped[IngestJobStage | None] = mapped_column(
        Enum(IngestJobStage, name="ingest_job_stage", native_enum=True), nullable=True
    )

    # Per-stage status, one column each — queryable without a join, and
    # the UI's 7-dot progress indicator (Day 1 acceptance criterion) is a
    # single-row read.
    separation_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    structure_beats_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    rms_vad_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    lyrics_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    ctc_alignment_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    f0_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    note_grid_status: Mapped[IngestJobStatus] = mapped_column(
        Enum(IngestJobStatus, name="ingest_job_status", native_enum=True),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )

    # Free-form per-stage output refs (blob hashes, durations, model
    # versions) — a JSONB escape hatch instead of 7 more tables on day 1.
    stage_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
