"""Performances — Wed Oct 7 (W3/W6 of IMPLEMENTATION_PLAN_2026-10-07.md).

Create -> chunked upload during the take -> complete (ffprobe, store,
defer scoring) -> GET. Publish-seed/join-list round out §7.3's async
seed/join: "no new alignment code" — a JOIN is a plain performance with
`parent_performance_id` set, scored by the exact same `run_scoring` task.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from elums.api.deps import get_blob_store, get_current_user, get_db
from elums.api.errors import ApiError
from elums.auth.sessions import get_session_by_token
from elums.blobs.service import record_blob
from elums.blobs.store import BlobStore
from elums.config import settings
from elums.ingest.probe import UndecodableAudioError, probe_audio
from elums.ingest.wav import build_wav_header
from elums.jobs.app import app as procrastinate_app
from elums.models.performance import Performance, PerformanceKind, PerformanceStatus
from elums.models.song import Song, SongVisibility
from elums.models.user import User
from elums.schemas.performances import PerformanceComplete, PerformanceCreate, PerformancePublic

router = APIRouter(prefix="/performances", tags=["performances"])

_SCORING_TASK_NAME = "elums.scoring.tasks.run_scoring"
_CHUNK_FILENAME_WIDTH = 6


def _staging_dir(performance_id: uuid.UUID) -> Path:
    return settings.performance_staging_root / str(performance_id)


def _chunk_path(performance_id: uuid.UUID, index: int) -> Path:
    return _staging_dir(performance_id) / f"{index:0{_CHUNK_FILENAME_WIDTH}d}.chunk"


def _next_expected_index(performance_id: uuid.UUID) -> int:
    """The first index with no chunk file on disk yet — chunks are never
    sparse by construction (each PUT either lands at `next_expected` or
    is rejected), so "count of existing files" and "first gap" coincide."""
    staging_dir = _staging_dir(performance_id)
    if not staging_dir.exists():
        return 0
    index = 0
    while _chunk_path(performance_id, index).exists():
        index += 1
    return index


async def _get_owned_performance(
    db: AsyncSession, performance_id: str, current_user: User
) -> Performance:
    try:
        performance_uuid = uuid.UUID(performance_id)
    except ValueError as exc:
        raise ApiError("not_found", "No such performance.", status_code=404) from exc

    performance = await db.get(Performance, performance_uuid)
    if performance is None or performance.user_id != current_user.id:
        raise ApiError("not_found", "No such performance.", status_code=404)
    return performance


@router.post("", response_model=PerformancePublic, status_code=201)
async def create_performance(
    body: PerformanceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Performance:
    song = await db.get(Song, body.song_id)
    if song is None:
        raise ApiError("not_found", "No such song.", status_code=404)

    kind = PerformanceKind.SOLO
    if body.parent_performance_id is not None:
        parent = await db.get(Performance, body.parent_performance_id)
        if parent is None or parent.song_id != body.song_id:
            raise ApiError(
                "invalid_parent", "parent_performance_id must reference a performance of the same song.",
                status_code=400,
            )
        kind = PerformanceKind.JOIN

    performance = Performance(
        song_id=body.song_id,
        user_id=current_user.id,
        kind=kind,
        parent_performance_id=body.parent_performance_id,
        device_label=body.device_label,
        latency_offset_ms=body.latency_offset_ms,
        status=PerformanceStatus.UPLOADING,
    )
    db.add(performance)
    await db.commit()
    return performance


@router.put("/{performance_id}/chunks/{index}", status_code=204)
async def put_chunk(
    performance_id: str,
    index: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    performance = await _get_owned_performance(db, performance_id, current_user)
    if performance.status is not PerformanceStatus.UPLOADING:
        raise ApiError(
            "performance_not_uploading", "This performance is no longer accepting chunks.", status_code=409
        )

    next_expected = _next_expected_index(performance.id)
    is_retransmit = index < next_expected
    if index > next_expected:
        raise ApiError(
            "out_of_order_chunk",
            f"Expected chunk index {next_expected}, got {index}.",
            status_code=409,
        )

    staging_dir = _staging_dir(performance.id)
    staging_dir.mkdir(parents=True, exist_ok=True)

    existing_total = sum(p.stat().st_size for p in staging_dir.glob("*.chunk"))
    try:
        body = await request.body()
    except ClientDisconnect as exc:
        raise ApiError("upload_interrupted", "Client disconnected mid-chunk.", status_code=400) from exc

    if not is_retransmit and existing_total + len(body) > settings.max_take_bytes:
        raise ApiError(
            "upload_too_large", f"Take exceeds the {settings.max_take_bytes}-byte limit.", status_code=413
        )

    # Idempotent re-PUT of an already-received index just overwrites the
    # same file with (expected-identical) bytes — never a partial-write
    # hazard, since this is one `write_bytes` call, not a streamed append.
    _chunk_path(performance.id, index).write_bytes(body)


@router.post("/{performance_id}/complete", response_model=PerformancePublic)
async def complete_performance(
    performance_id: str,
    body: PerformanceComplete = PerformanceComplete(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
) -> Performance:
    performance = await _get_owned_performance(db, performance_id, current_user)
    if performance.status is not PerformanceStatus.UPLOADING:
        raise ApiError(
            "performance_not_uploading", "This performance has already been completed.", status_code=409
        )

    staging_dir = _staging_dir(performance.id)
    chunk_count = _next_expected_index(performance.id)
    if chunk_count == 0:
        raise ApiError("no_chunks_uploaded", "No chunks were uploaded for this performance.", status_code=400)

    # X0 (Oct 8): chunks are headerless 16-bit mono PCM (see
    # elums/ingest/wav.py's docstring) — the total byte count is only
    # known now, so the WAV header is built and prepended here rather
    # than carried by chunk 0.
    data_length = sum(_chunk_path(performance.id, i).stat().st_size for i in range(chunk_count))
    assembled_path = staging_dir / "assembled.audio"
    with assembled_path.open("wb") as out:
        out.write(build_wav_header(body.sample_rate, data_length))
        for i in range(chunk_count):
            out.write(_chunk_path(performance.id, i).read_bytes())

    with assembled_path.open("rb") as f:
        ref = store.put(f, content_type="audio/wav")

    local_path = store.local_path(ref.sha256)
    assert local_path is not None

    try:
        await probe_audio(local_path)
    except UndecodableAudioError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ApiError(
            "undecodable_audio", "No decodable audio stream was found in this take.", status_code=415
        ) from exc

    await record_blob(db, ref)
    performance.audio_blob_sha256 = ref.sha256
    performance.status = PerformanceStatus.SCORING
    await db.commit()

    shutil.rmtree(staging_dir, ignore_errors=True)

    await procrastinate_app.configure_task(
        name=_SCORING_TASK_NAME, queue="gpu", lock="gpu:separation"
    ).defer_async(performance_id=str(performance.id))

    return performance


@router.get("/{performance_id}", response_model=PerformancePublic)
async def get_performance(
    performance_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Performance:
    """Owner-or-public, reusing `get_ingest_status`'s convention verbatim
    (elums/api/routers/songs.py) — a performance's visibility follows its
    SONG's visibility, since a performance has no visibility field of its
    own."""
    try:
        performance_uuid = uuid.UUID(performance_id)
    except ValueError as exc:
        raise ApiError("not_found", "No such performance.", status_code=404) from exc

    performance = await db.get(Performance, performance_uuid)
    if performance is None:
        raise ApiError("not_found", "No such performance.", status_code=404)

    song = await db.get(Song, performance.song_id)
    if song is None or song.visibility is not SongVisibility.PUBLIC:
        raw_token = request.cookies.get(settings.session_cookie_name)
        session = await get_session_by_token(db, raw_token) if raw_token else None
        if session is None or session.user_id != performance.user_id:
            raise ApiError("not_found", "No such performance.", status_code=404)

    return performance


@router.post("/{performance_id}/publish-seed", response_model=PerformancePublic)
async def publish_seed(
    performance_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Performance:
    """§7.3: "a session becomes a solo take published as a joinable
    seed." Only the owner may publish, and only once scoring has
    succeeded — publishing a half-scored take would let a joiner build
    on top of a performance that might still fail."""
    performance = await _get_owned_performance(db, performance_id, current_user)
    if performance.status is not PerformanceStatus.SUCCEEDED:
        raise ApiError(
            "performance_not_scored", "Only a successfully scored performance can be published as a seed.",
            status_code=409,
        )
    performance.kind = PerformanceKind.SEED
    await db.commit()
    return performance
