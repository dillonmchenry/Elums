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


class PerformanceComplete(BaseModel):
    """Thu Oct 8 (X0): the client now uploads headerless 16-bit PCM
    chunks (see ``elums/ingest/wav.py``'s docstring for why), so
    `complete` needs the capture sample rate to build a real WAV
    header once — unlike MediaRecorder's self-describing WebM, raw PCM
    chunks carry no format metadata at all. Defaults to 48000 (the
    common desktop `AudioContext` default) only for backward
    compatibility with any in-flight pre-X0 client; real callers
    always send the `AudioContext.sampleRate` they actually captured
    at (§10.4: never force `sampleRate`, so this varies by device)."""

    sample_rate: int = 48000


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
