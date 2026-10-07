"""Structure/key/VAD summary — Sun Oct 4 (N3 of
IMPLEMENTATION_PLAN_2026-10-04.md). One row per song, per
ELUMS_TECHNICAL_APPROACH.md §4's data-tiering rule: the full analysis
artifact (every beat, downbeat, section, the 24-way key correlation
vector, every VAD span) is a content-addressed BLOB
(`analysis_blob_sha256`, fetched whole — nothing ever queries into it);
this table holds only the handful of fields that are genuinely
queryable, the same split M8's `Stem` already draws for stems-vs-blobs.

`key_tonic`/`key_mode`/`key_confidence` are deliberately NOT treated as
final — §5 of the approach doc calls the Krumhansl-Schmuckler estimator a
decent-not-great tool and says to cross-check it against the note
histogram once Tuesday's RMVPE track exists. Keeping the full correlation
vector in the blob (not just the winning tonic/mode here) is what makes
that cross-check possible without re-running librosa.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class SongAnalysis(TimestampMixin, Base):
    __tablename__ = "song_analyses"

    id = uuidv7_pk()

    song_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("songs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_tonic: Mapped[str | None] = mapped_column(String(2), nullable=True)
    key_mode: Mapped[str | None] = mapped_column(String(5), nullable=True)
    key_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    beat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voiced_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Mon Oct 5 (L4): "lrclib" (LRCLIB text, ASR never ran or wasn't
    # needed), "whisper" (no usable LRCLIB hit), or "reconciled" (LRCLIB
    # text anchored onto ASR/CTC timings via the LCS reconciliation in
    # elums/ingest/syllables.py). Nullable until the lyrics stage runs.
    lyrics_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    syllable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vocable_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The full artifact: beats[], downbeats[], sections[], the 24-way key
    # correlation vector, VAD spans — fetched whole by the client, never
    # queried into (§4's reasoning for M8's stem blobs applies identically
    # here).
    analysis_blob_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=False
    )

    # model name/version per stage, e.g. {"structure": "harmonix-all",
    # "key": "krumhansl-schmuckler", "vad": "rms-threshold-v1"} — Oct 11's
    # AI/cost ledger (ELUMS_BUILD_SCHEDULE.md) is a query over this and
    # ingest_jobs.stage_results together, not a separate archaeology pass.
    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Tue Oct 6 (T1/T3 of IMPLEMENTATION_PLAN_2026-10-06.md): the F0 track
    # is its OWN binary float16 blob (§4's tiering rule — not JSON, not
    # merged into analysis_blob_sha256 above), and the chart/peaks are the
    # client-facing bundle, a second artifact entirely from the internal
    # analysis blob. Nullable until each respective stage runs.
    f0_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )
    frame_rate_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    voiced_frame_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    chart_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )
    peaks_blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=True
    )
    note_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # T2's note-histogram cross-check (§5) — deliberately NOT overwriting
    # key_tonic/key_mode above; the owner judges which one wins (M1 gate).
    key_tonic_from_notes: Mapped[str | None] = mapped_column(String(2), nullable=True)
    key_mode_from_notes: Mapped[str | None] = mapped_column(String(5), nullable=True)
    key_confidence_from_notes: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Wed Oct 7 (W0 of IMPLEMENTATION_PLAN_2026-10-07.md): the resolved
    # key `_quantize_to_key` actually used — the higher-margin side of
    # key_tonic/key_mode (chroma) vs key_tonic_from_notes/key_mode_from_notes
    # (note histogram). `key_confidence_low` flags when even the WINNING
    # margin sits under elums.ingest.notes.KEY_CONFIDENCE_LOW_THRESHOLD —
    # a real, surfaced "this song's key is genuinely ambiguous," not a
    # silently confident pick. All four raw fields above stay untouched.
    key_tonic_resolved: Mapped[str | None] = mapped_column(String(2), nullable=True)
    key_mode_resolved: Mapped[str | None] = mapped_column(String(5), nullable=True)
    key_confidence_low: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
