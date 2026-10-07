from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from elums.models.performance import PerformanceKind, PerformanceStatus


class PerformanceCreate(BaseModel):
    song_id: uuid.UUID
    parent_performance_id: uuid.UUID | None = None
    device_label: str | None = None
    latency_offset_ms: float | None = None


class PerformancePublic(BaseModel):
    id: uuid.UUID
    song_id: uuid.UUID
    user_id: uuid.UUID
    kind: PerformanceKind
    parent_performance_id: uuid.UUID | None
    status: PerformanceStatus
    error_message: str | None

    audio_blob_sha256: str | None
    f0_blob_sha256: str | None
    analysis_blob_sha256: str | None

    score_overall: float | None
    pct_in_tune: float | None
    median_cents: float | None
    arrival_offset_ms_median: float | None
    octave_shift_semitones: int | None
    alignment_warning: bool

    offset_s: float | None
    latency_offset_ms: float | None
    device_label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
