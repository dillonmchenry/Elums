"""M8: the day's headline — Mel-Band RoFormer vocal separation as a
Procrastinate task on the `gpu` queue, serialized by the `gpu:separation`
lock (§4's durable GPU semaphore: exactly one GPU-bound job runs at a
time, across worker restarts, because the lock lives in Postgres rather
than in-process memory).

Only ever imported by `elums/jobs/gpu_app.py` (the gpu-worker's `--app=`
entrypoint) — never by `elums.jobs.app` directly, and never by the api/
worker processes, because this module imports torch and audio-separator,
which the torch-free `app` image deliberately does not have (§11.6).
`POST /api/songs` (elums/api/routers/songs.py) defers this job by task
NAME (`app.configure_task(name="elums.separation.task.separate", ...)`)
for exactly that reason — see that router's comment.

Sun Oct 4 (N4, IMPLEMENTATION_PLAN_2026-10-04.md): on success this now
defers `elums.ingest.tasks.run_structure_beats` by name (same "defer by
NAME, not by import" reasoning — this module still must not import
elums.ingest.tasks, or anything that chain eventually imports, to keep
this file's own import graph minimal and testable) rather than marking
the overall `ingest_job.status` terminal. Day 1's "SUCCEEDED after
separation" was always provisional — the schema had six more stage
columns sitting at PENDING — and today is where that stops being true.

Failure handling (IMPLEMENTATION_PLAN_2026-10-03.md M8's table):
  - checkpoint not yet downloaded -> retry with backoff (Procrastinate's
    own `retry=` below, scoped to `CheckpointNotReadyError` only)
  - CUDA OOM -> empty_cache(), requeue once at half the segment size,
    then fail with the measured peak once at the minimum
  - undecodable/corrupt audio -> fail immediately, no retry
  - worker killed mid-run -> Procrastinate's own SKIP LOCKED requeues it
    automatically; nothing to write here
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import soundfile as sf
import structlog
import torch
from procrastinate import RetryStrategy
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from elums.blobs.service import record_blob
from elums.blobs.store import BlobRef, LocalBlobStore
from elums.config import settings
from elums.db import session_scope
from elums.jobs.app import app
from elums.models.ingest_job import IngestJob, IngestJobStage, IngestJobStatus
from elums.models.song import Song
from elums.models.stem import Stem, StemKind
from elums.separation.engine import (
    CHECKPOINT_FILENAME,
    DEFAULT_SEGMENT_SIZE,
    MIN_SEGMENT_SIZE,
    CheckpointNotReadyError,
    SeparationOutput,
    run_separation,
)

logger = structlog.get_logger()

# N4: deferred by NAME, not by importing elums.ingest.tasks — see this
# module's docstring and elums/api/routers/songs.py's identical pattern
# for `_SEPARATION_TASK_NAME`.
_STRUCTURE_BEATS_TASK_NAME = "elums.ingest.tasks.run_structure_beats"


async def _get_ingest_job(db: AsyncSession, song_id: uuid.UUID) -> IngestJob | None:
    result = await db.execute(select(IngestJob).where(IngestJob.song_id == song_id))
    return result.scalar_one_or_none()


async def _mark_failed(song_id: uuid.UUID, message: str) -> None:
    async with session_scope() as db:
        ingest_job = await _get_ingest_job(db, song_id)
        if ingest_job is None:
            return
        ingest_job.status = IngestJobStatus.FAILED
        ingest_job.separation_status = IngestJobStatus.FAILED
        ingest_job.error_message = message
        ingest_job.completed_at = datetime.now(UTC)
        await db.commit()
    logger.error("separation.failed", song_id=str(song_id), reason=message)


async def _store_stem(store: LocalBlobStore, path: Path, content_type: str) -> BlobRef:
    with path.open("rb") as f:
        return store.put(f, content_type=content_type)


@app.task(
    queue="gpu",
    lock="gpu:separation",
    retry=RetryStrategy(
        max_attempts=5, wait=5, exponential_wait=2, retry_exceptions=(CheckpointNotReadyError,)
    ),
)
async def separate(song_id: str, segment_size: int = DEFAULT_SEGMENT_SIZE) -> None:
    song_uuid = uuid.UUID(song_id)  # str, not UUID: keeps the job's JSON args unambiguous

    async with session_scope() as db:
        song = await db.get(Song, song_uuid)
        ingest_job = await _get_ingest_job(db, song_uuid)
        if song is None or ingest_job is None:
            logger.warning("separation.song_or_job_missing", song_id=song_id)
            return

        ingest_job.status = IngestJobStatus.RUNNING
        ingest_job.current_stage = IngestJobStage.SEPARATION
        ingest_job.separation_status = IngestJobStatus.RUNNING
        ingest_job.step_index = 0
        ingest_job.step_total = 1
        ingest_job.message = "Separating vocals and instrumental..."
        await db.commit()

        blob_store = LocalBlobStore(settings.blob_root)
        source_path = blob_store.local_path(song.source_blob_sha256)

    if source_path is None:
        # Shouldn't happen: POST /api/songs never creates a song without
        # first writing its source blob. A missing blob here means disk
        # state and DB state have diverged — not something a retry fixes.
        await _mark_failed(song_uuid, "Source audio blob is missing from the blob store.")
        return

    work_dir = Path(tempfile.mkdtemp(prefix=f"separate-{song_uuid}-"))
    output: SeparationOutput | None = None
    try:
        output = await asyncio.to_thread(
            run_separation, source_path, work_dir, settings.model_root, segment_size
        )
    except CheckpointNotReadyError:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise  # Procrastinate retries with backoff — see `retry=` above
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        shutil.rmtree(work_dir, ignore_errors=True)
        if segment_size > MIN_SEGMENT_SIZE:
            next_segment_size = max(segment_size // 2, MIN_SEGMENT_SIZE)
            logger.warning(
                "separation.oom_retry_smaller_segment",
                song_id=song_id,
                segment_size=segment_size,
                next_segment_size=next_segment_size,
            )
            await separate.defer_async(song_id=song_id, segment_size=next_segment_size)
        else:
            await _mark_failed(
                song_uuid, f"Out of GPU memory even at the minimum segment size ({MIN_SEGMENT_SIZE})."
            )
        return
    except Exception as exc:  # noqa: BLE001 — audio-separator's own exceptions land here
        shutil.rmtree(work_dir, ignore_errors=True)
        await _mark_failed(song_uuid, f"Separation failed: {exc}")
        return

    try:
        blob_store = LocalBlobStore(settings.blob_root)
        vocals_ref = await _store_stem(blob_store, output.vocals_path, "audio/flac")
        instrumental_ref = await _store_stem(blob_store, output.instrumental_path, "audio/flac")
        vocals_info = sf.info(str(output.vocals_path))
        instrumental_info = sf.info(str(output.instrumental_path))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    async with session_scope() as db:
        await record_blob(db, vocals_ref)
        await record_blob(db, instrumental_ref)

        for ref, info, kind in (
            (vocals_ref, vocals_info, StemKind.VOCALS),
            (instrumental_ref, instrumental_info, StemKind.INSTRUMENTAL),
        ):
            stmt = insert(Stem).values(
                song_id=song_uuid,
                kind=kind,
                blob_sha256=ref.sha256,
                sample_rate=info.samplerate,
                duration_s=info.duration,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["song_id", "kind"],
                set_={
                    "blob_sha256": ref.sha256,
                    "sample_rate": info.samplerate,
                    "duration_s": info.duration,
                },
            )
            await db.execute(stmt)

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            # N4: no longer terminal — separation.status is RUNNING with
            # the *stage* marked SUCCEEDED, and structure_beats picks up
            # next. See this module's docstring.
            ingest_job.separation_status = IngestJobStatus.SUCCEEDED
            ingest_job.step_index = 1
            ingest_job.message = "Separation complete. Starting structure analysis..."
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "separation": {
                    "model": CHECKPOINT_FILENAME,
                    "duration_ms": output.duration_ms,
                    "vram_peak_mb": output.vram_peak_mb,
                    "segment_size": segment_size,
                },
            }
        await db.commit()

    # A12: model, duration_ms, vram_peak_mb all on one log line.
    logger.info(
        "separation.succeeded",
        song_id=song_id,
        model=CHECKPOINT_FILENAME,
        duration_ms=output.duration_ms,
        vram_peak_mb=output.vram_peak_mb,
        segment_size=segment_size,
    )

    # N4: chain into structure/beats/key next, deferred by name (see this
    # module's docstring) — shares the `gpu:separation` lock, so it waits
    # its turn rather than racing a concurrently-uploaded song's
    # separation job.
    await app.configure_task(
        name=_STRUCTURE_BEATS_TASK_NAME, queue="gpu", lock="gpu:separation"
    ).defer_async(song_id=song_id)
