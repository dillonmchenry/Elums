"""M7: `POST /api/songs` — multipart upload, sniffed with ffprobe (never
the client's Content-Type/extension), capped by size/duration from
`Settings`, streamed to the BlobStore while hashing (never fully buffered
in memory). Per ELUMS_TECHNICAL_APPROACH.md §4 and
IMPLEMENTATION_PLAN_2026-10-03.md M7.
"""

from __future__ import annotations

from typing import BinaryIO

from fastapi import APIRouter, Depends, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_blob_store, get_current_user, get_db
from elums.api.errors import ApiError
from elums.blobs.service import record_blob
from elums.blobs.store import BlobStore
from elums.config import settings
from elums.ingest.probe import UndecodableAudioError, probe_audio
from elums.models.ingest_job import IngestJob
from elums.models.song import Song, SongVisibility
from elums.models.user import User
from elums.schemas.songs import SongPublic

router = APIRouter(prefix="/songs", tags=["songs"])


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
        song = Song(
            uploaded_by_user_id=current_user.id,
            title=title or (file.filename or "Untitled"),
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
    return song
