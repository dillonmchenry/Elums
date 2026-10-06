from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from elums.models.ingest_job import IngestJobStage, IngestJobStatus
from elums.models.song import SongVisibility


class SongPublic(BaseModel):
    id: uuid.UUID
    title: str
    artist: str | None
    source_blob_sha256: str
    visibility: SongVisibility
    uploaded_by_user_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class SongBundlePublic(BaseModel):
    """Tue Oct 6 (T3): `GET /api/songs/{song_id}` — song metadata plus
    the chart/peaks/stem blob hashes the karaoke page needs. Deliberately
    NOT the chart's own contents inline — the client fetches that
    separately through `/blobs/<chart_blob_sha256>` (Caddy's Range-request
    path), same as every other blob.
    """

    id: uuid.UUID
    title: str
    artist: str | None
    visibility: SongVisibility

    vocals_blob_sha256: str | None
    instrumental_blob_sha256: str | None
    chart_blob_sha256: str | None
    peaks_blob_sha256: str | None
    f0_blob_sha256: str | None
    note_count: int


class IngestJobPublic(BaseModel):
    """Sun Oct 4 (N4): closes the gap PROGRESS.md's Day 1 loose ends
    flagged — "no HTTP endpoint exists yet for polling an ingest job's
    status," with tests/test_separation.py reaching into the DB directly
    as a stand-in. The SPA's progress poll (elums/api/routers/songs.py's
    `GET /songs/{song_id}/ingest`) is the real consumer."""

    status: IngestJobStatus
    current_stage: IngestJobStage | None
    separation_status: IngestJobStatus
    structure_beats_status: IngestJobStatus
    rms_vad_status: IngestJobStatus
    lyrics_status: IngestJobStatus
    ctc_alignment_status: IngestJobStatus
    f0_status: IngestJobStatus
    note_grid_status: IngestJobStatus
    step_index: int
    step_total: int
    message: str | None
    error_message: str | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}
