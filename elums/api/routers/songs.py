"""M7: `POST /api/songs` — multipart upload, sniffed with ffprobe (never
the client's Content-Type/extension), capped by size/duration from
`Settings`, streamed to the BlobStore while hashing (never fully buffered
in memory). Per ELUMS_TECHNICAL_APPROACH.md §4 and
IMPLEMENTATION_PLAN_2026-10-03.md M7.
"""

from __future__ import annotations

import uuid
from typing import BinaryIO

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_blob_store, get_current_user, get_db
from elums.api.errors import ApiError
from elums.auth.sessions import get_session_by_token
from elums.blobs.service import record_blob
from elums.blobs.store import BlobStore
from elums.config import settings
from elums.ingest.probe import UndecodableAudioError, probe_audio, split_artist_title_from_filename
from elums.jobs.app import app as procrastinate_app
from elums.models.ingest_job import IngestJob
from elums.models.performance import Performance, PerformanceKind
from elums.models.song import Song, SongVisibility
from elums.models.song_analysis import SongAnalysis
from elums.models.stem import Stem, StemKind
from elums.models.user import User
from elums.schemas.performances import PerformancePublic
from elums.schemas.songs import IngestJobPublic, SongBundlePublic, SongPublic

router = APIRouter(prefix="/songs", tags=["songs"])

# M8: deferred by task NAME, not by importing `elums.separation.task`
# directly — that module imports torch, which the `api` image
# deliberately does not have (§11.6: keep api/worker torch-free). `queue`
# and `lock` are passed explicitly here because this process never
# imports the `@app.task(...)`-decorated function itself, so there's no
# decorator for Procrastinate to read them off of — see
# elums/jobs/gpu_app.py and elums/separation/task.py's module docstrings.
_SEPARATION_TASK_NAME = "elums.separation.task.separate"


class _SizeCappedReader:
    """Wraps the upload's underlying file object so `BlobStore.put`'s
    streaming read loop raises before writing past the cap, reusing the
    exact "exception mid-stream leaves no blob at the target hash"
    guarantee `store.put` already provides — rather than inventing a
    second size-check code path."""

    def __init__(self, fileobj: BinaryIO, max_bytes: int) -> None:
        self._fileobj = fileobj
        self._max_bytes = max_bytes
        self._read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        self._read_bytes += len(chunk)
        if self._read_bytes > self._max_bytes:
            raise ApiError(
                "upload_too_large",
                f"Upload exceeds the {self._max_bytes}-byte limit.",
                status_code=413,
            )
        return chunk


@router.post("", response_model=SongPublic, status_code=201)
async def upload_song(
    file: UploadFile,
    title: str | None = Form(default=None),
    visibility: SongVisibility = Form(default=SongVisibility.PRIVATE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
) -> Song:
    capped_reader = _SizeCappedReader(file.file, settings.max_upload_bytes)
    # ApiError raised from inside `capped_reader.read()` propagates straight
    # up through `store.put`'s read loop — FastAPI's exception handler
    # turns it into the 413 response; no corrupt blob is ever written.
    ref = store.put(capped_reader, content_type=file.content_type or "application/octet-stream")

    local_path = store.local_path(ref.sha256)
    assert local_path is not None  # LocalBlobStore always has one once put() returns

    try:
        probe = await probe_audio(local_path)
    except UndecodableAudioError as exc:
        raise ApiError(
            "undecodable_audio",
            "No decodable audio stream was found in this file.",
            status_code=415,
        ) from exc

    if probe.duration_s > settings.max_upload_duration_s:
        raise ApiError(
            "upload_too_long",
            f"Audio exceeds the {settings.max_upload_duration_s}s limit.",
            status_code=413,
        )

    await record_blob(db, ref)

    # Re-uploading identical bytes as the same user returns the existing
    # song instead of erroring or duplicating the catalog — falls out of
    # content addressing plus the `uq_songs_owner_blob` constraint.
    existing = await db.execute(
        select(Song).where(
            Song.uploaded_by_user_id == current_user.id,
            Song.source_blob_sha256 == ref.sha256,
        )
    )
    song = existing.scalar_one_or_none()

    if song is None:
        # Mon Oct 5 (L1): prefer the file's own ID3/vorsbis tags over the
        # upload filename for both title and artist — fall back to
        # splitting "Artist - Title" out of the filename only where tags
        # are absent (elums/ingest/probe.py's split_artist_title_from_filename).
        fallback_artist, fallback_title = split_artist_title_from_filename(file.filename or "")
        song = Song(
            uploaded_by_user_id=current_user.id,
            title=title or probe.title or fallback_title or (file.filename or "Untitled"),
            artist=probe.artist or fallback_artist,
            source_blob_sha256=ref.sha256,
            visibility=visibility,
        )
        db.add(song)
        await db.flush()

        db.add(
            IngestJob(
                song_id=song.id,
                source_blob_sha256=ref.sha256,
                source_filename=file.filename or "upload",
                uploaded_by_user_id=current_user.id,
            )
        )

    await db.commit()

    # Not a single atomic transaction with the `songs`/`ingest_jobs` commit
    # above — Procrastinate's own connector and this request's SQLAlchemy
    # session are two separate Postgres connections, and sharing one
    # transaction across both would need lower-level plumbing than this
    # milestone's time budget allows. Deferred immediately after a
    # successful commit instead: the only gap this leaves is a crash in
    # the few milliseconds between the two calls, which strands a
    # `pending` ingest_job with no job behind it — recoverable later by a
    # sweep that re-defers any `pending` job older than a few minutes
    # (not built today; noted as a known gap, not a silent one). The
    # connector itself is opened once, for the app's whole lifetime, in
    # elums/api/main.py's lifespan — not re-opened per request here.
    await procrastinate_app.configure_task(
        name=_SEPARATION_TASK_NAME, queue="gpu", lock="gpu:separation"
    ).defer_async(song_id=str(song.id))

    return song


@router.get("/{song_id}/ingest", response_model=IngestJobPublic)
async def get_ingest_status(
    song_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> IngestJob:
    """Sun Oct 4 (N4): closes PROGRESS.md's Day 1 loose end — the SPA's
    progress poll had no real endpoint to call and
    tests/test_separation.py stood in with a raw DB query.

    Owner-or-public, same rule `/internal/blob-authz` already enforces
    for blob bytes (elums/api/routers/internal.py) — deliberately NOT
    `Depends(get_current_user)`, which hard-401s with no cookie at all;
    a public song's ingest status is meant to be visible anonymously,
    the same as its blobs.
    """
    try:
        song_uuid = uuid.UUID(song_id)
    except ValueError as exc:
        raise ApiError("not_found", "No such song.", status_code=404) from exc

    song = await db.get(Song, song_uuid)
    if song is None:
        raise ApiError("not_found", "No such song.", status_code=404)

    if song.visibility is not SongVisibility.PUBLIC:
        raw_token = request.cookies.get(settings.session_cookie_name)
        session = await get_session_by_token(db, raw_token) if raw_token else None
        if session is None or session.user_id != song.uploaded_by_user_id:
            raise ApiError("not_found", "No such song.", status_code=404)

    result = await db.execute(select(IngestJob).where(IngestJob.song_id == song_uuid))
    ingest_job = result.scalar_one_or_none()
    if ingest_job is None:
        raise ApiError("not_found", "No ingest job for this song.", status_code=404)

    return ingest_job


@router.get("/{song_id}", response_model=SongBundlePublic)
async def get_song_bundle(
    song_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SongBundlePublic:
    """Tue Oct 6 (T3 of IMPLEMENTATION_PLAN_2026-10-06.md): the karaoke
    page's one fetch — song metadata plus the chart/peaks/stem blob
    hashes. **Reuses `get_ingest_status`'s owner-or-public rule and
    404-not-403 convention verbatim** (Day 2 §5.3's precedent) rather
    than reinventing it, per the plan's own instruction.
    """
    try:
        song_uuid = uuid.UUID(song_id)
    except ValueError as exc:
        raise ApiError("not_found", "No such song.", status_code=404) from exc

    song = await db.get(Song, song_uuid)
    if song is None:
        raise ApiError("not_found", "No such song.", status_code=404)

    if song.visibility is not SongVisibility.PUBLIC:
        raw_token = request.cookies.get(settings.session_cookie_name)
        session = await get_session_by_token(db, raw_token) if raw_token else None
        if session is None or session.user_id != song.uploaded_by_user_id:
            raise ApiError("not_found", "No such song.", status_code=404)

    stems_result = await db.execute(select(Stem).where(Stem.song_id == song_uuid))
    stems = {stem.kind: stem for stem in stems_result.scalars()}

    analysis_result = await db.execute(
        select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
    )
    analysis = analysis_result.scalar_one_or_none()

    return SongBundlePublic(
        id=song.id,
        title=song.title,
        artist=song.artist,
        visibility=song.visibility,
        vocals_blob_sha256=(
            stems[StemKind.VOCALS].blob_sha256 if StemKind.VOCALS in stems else None
        ),
        instrumental_blob_sha256=(
            stems[StemKind.INSTRUMENTAL].blob_sha256 if StemKind.INSTRUMENTAL in stems else None
        ),
        chart_blob_sha256=analysis.chart_blob_sha256 if analysis else None,
        peaks_blob_sha256=analysis.peaks_blob_sha256 if analysis else None,
        f0_blob_sha256=analysis.f0_blob_sha256 if analysis else None,
        note_count=analysis.note_count if analysis else 0,
    )


@router.get("/{song_id}/seeds", response_model=list[PerformancePublic])
async def list_seeds(
    song_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[Performance]:
    """Wed Oct 7 (W6): §7.3's async seed/join — "a session becomes a
    solo take published as a joinable seed." Public by construction
    (publishing a seed is an explicit opt-in act, unlike a song's own
    visibility default), so this endpoint takes no auth at all, same
    reasoning a public song's blobs are anonymously fetchable."""
    try:
        song_uuid = uuid.UUID(song_id)
    except ValueError as exc:
        raise ApiError("not_found", "No such song.", status_code=404) from exc

    result = await db.execute(
        select(Performance)
        .where(Performance.song_id == song_uuid, Performance.kind == PerformanceKind.SEED)
        .order_by(Performance.created_at.desc())
    )
    return list(result.scalars())
