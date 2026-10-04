"""The structure_beats -> rms_vad job chain — Sun Oct 4 (N4 of
IMPLEMENTATION_PLAN_2026-10-04.md). Registered through
elums/jobs/gpu_app.py ONLY, same reasoning as elums/separation/task.py's
module docstring: this imports elums.ingest.structure, which imports
torch — the torch-free api/worker images must never import this module.

Chain mechanics mirror elums/separation/task.py's own OOM-requeue
pattern: each stage defers the next one by calling `.defer_async()`
directly at the end of its own success path, rather than a separate
scheduler. `structure_beats` shares the `gpu:separation` lock (it is
GPU-bound — its own HTDemucs pass plus the harmonix-all forward pass);
`rms_vad` does not (librosa-only, no CUDA), so a cheap CPU stage never
waits behind the GPU semaphore for no reason — it still runs on the
`gpu` queue because this is the only image with librosa/audio-separator
installed (§11.6: api/worker stay torch-free), just without the lock
serializing it against separation.

Per IMPLEMENTATION_PLAN_2026-10-04.md §5's acceptance criterion: when
`rms_vad` succeeds, overall `ingest_job.status` goes to SUCCEEDED and
`completed_at` is set — mirroring exactly the precedent
elums/separation/task.py set on Day 1, when `lyrics`/`ctc_alignment`/
`f0`/`note_grid` existed in the schema but had no task behind them yet.
Monday's lyrics task picks up by setting status back to RUNNING and
deferring itself from wherever the chain needs to resume.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from elums.blobs.service import record_blob
from elums.blobs.store import BlobRef, LocalBlobStore
from elums.config import settings
from elums.db import session_scope
from elums.ingest.key import estimate_key
from elums.ingest.structure import StructureAnalysisError, run_structure
from elums.ingest.vad import segment_vocal_activity
from elums.jobs.app import app
from elums.models.ingest_job import IngestJob, IngestJobStage, IngestJobStatus
from elums.models.song import Song
from elums.models.song_analysis import SongAnalysis
from elums.models.stem import Stem, StemKind

logger = structlog.get_logger()

_RMS_VAD_TASK_NAME = "elums.ingest.tasks.run_rms_vad"


async def _get_ingest_job(db: AsyncSession, song_id: uuid.UUID) -> IngestJob | None:
    result = await db.execute(select(IngestJob).where(IngestJob.song_id == song_id))
    return result.scalar_one_or_none()


async def _mark_stage_failed(song_id: uuid.UUID, message: str) -> None:
    async with session_scope() as db:
        ingest_job = await _get_ingest_job(db, song_id)
        if ingest_job is None:
            return
        ingest_job.status = IngestJobStatus.FAILED
        ingest_job.error_message = message
        ingest_job.completed_at = datetime.now(UTC)
        await db.commit()
    logger.error("ingest_stage.failed", song_id=str(song_id), reason=message)


def _store_json_blob(store: LocalBlobStore, payload: dict) -> BlobRef:
    data = json.dumps(payload).encode("utf-8")
    return store.put(io.BytesIO(data), content_type="application/json")


@app.task(queue="gpu", lock="gpu:separation")
async def run_structure_beats(song_id: str) -> None:
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        song = await db.get(Song, song_uuid)
        ingest_job = await _get_ingest_job(db, song_uuid)
        if song is None or ingest_job is None:
            logger.warning("structure_beats.song_or_job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.STRUCTURE_BEATS
        ingest_job.structure_beats_status = IngestJobStatus.RUNNING
        ingest_job.message = "Analyzing structure, beats, and key..."
        await db.commit()

        blob_store = LocalBlobStore(settings.blob_root)
        source_path = blob_store.local_path(song.source_blob_sha256)
        instrumental_row = await db.execute(
            select(Stem).where(Stem.song_id == song_uuid, Stem.kind == StemKind.INSTRUMENTAL)
        )
        instrumental_stem = instrumental_row.scalar_one_or_none()
        instrumental_path = (
            blob_store.local_path(instrumental_stem.blob_sha256) if instrumental_stem else None
        )

    if source_path is None or instrumental_path is None:
        await _mark_stage_failed(
            song_uuid, "Source audio or instrumental stem is missing from the blob store."
        )
        return

    work_dir = Path(tempfile.mkdtemp(prefix=f"structure-{song_uuid}-"))
    try:
        structure_out = run_structure(source_path, work_dir, settings.model_root)
        key_out = estimate_key(str(instrumental_path))
    except StructureAnalysisError as exc:
        await _mark_stage_failed(song_uuid, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        await _mark_stage_failed(song_uuid, f"Structure/key analysis failed: {exc}")
        return
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    blob_store = LocalBlobStore(settings.blob_root)
    artifact = {
        "bpm": structure_out.bpm,
        "beats": structure_out.beats,
        "downbeats": structure_out.downbeats,
        "sections": [
            {"start_s": s.start_s, "end_s": s.end_s, "label": s.label} for s in structure_out.sections
        ],
        "key": {
            "tonic": key_out.tonic,
            "mode": key_out.mode,
            "confidence": key_out.confidence,
            "correlations": key_out.correlations,  # all 24 — Tuesday's note-histogram cross-check
        },
    }
    blob_ref = _store_json_blob(blob_store, artifact)

    async with session_scope() as db:
        await record_blob(db, blob_ref)

        stmt = insert(SongAnalysis).values(
            song_id=song_uuid,
            bpm=structure_out.bpm,
            key_tonic=key_out.tonic,
            key_mode=key_out.mode,
            key_confidence=key_out.confidence,
            beat_count=len(structure_out.beats),
            downbeat_count=len(structure_out.downbeats),
            section_count=len(structure_out.sections),
            voiced_duration_s=0.0,
            analysis_blob_sha256=blob_ref.sha256,
            model_versions={"structure": "harmonix-all", "key": "krumhansl-schmuckler"},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["song_id"],
            set_={
                "bpm": structure_out.bpm,
                "key_tonic": key_out.tonic,
                "key_mode": key_out.mode,
                "key_confidence": key_out.confidence,
                "beat_count": len(structure_out.beats),
                "downbeat_count": len(structure_out.downbeats),
                "section_count": len(structure_out.sections),
                "analysis_blob_sha256": blob_ref.sha256,
            },
        )
        await db.execute(stmt)

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.structure_beats_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "structure_beats": {
                    "model": "harmonix-all",
                    "duration_ms": structure_out.duration_ms,
                    "vram_peak_mb": structure_out.vram_peak_mb,
                },
            }
        await db.commit()

    logger.info(
        "structure_beats.succeeded",
        song_id=song_id,
        bpm=structure_out.bpm,
        sections=len(structure_out.sections),
        duration_ms=structure_out.duration_ms,
        vram_peak_mb=structure_out.vram_peak_mb,
    )

    await app.configure_task(
        name=_RMS_VAD_TASK_NAME, queue="gpu"  # no lock — CPU-only, §4's gpu:separation semaphore
        # exists for CUDA contention, which librosa's RMS envelope never causes.
    ).defer_async(song_id=song_id)


@app.task(queue="gpu")
async def run_rms_vad(song_id: str) -> None:
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is None:
            logger.warning("rms_vad.job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.RMS_VAD
        ingest_job.rms_vad_status = IngestJobStatus.RUNNING
        ingest_job.message = "Segmenting vocal activity..."
        await db.commit()

        blob_store = LocalBlobStore(settings.blob_root)
        vocals_row = await db.execute(
            select(Stem).where(Stem.song_id == song_uuid, Stem.kind == StemKind.VOCALS)
        )
        vocals_stem = vocals_row.scalar_one_or_none()
        vocals_path = blob_store.local_path(vocals_stem.blob_sha256) if vocals_stem else None

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()

    if vocals_path is None or analysis is None:
        await _mark_stage_failed(
            song_uuid, "Vocal stem or structure analysis row is missing."
        )
        return

    try:
        segments = segment_vocal_activity(str(vocals_path))
    except Exception as exc:  # noqa: BLE001
        await _mark_stage_failed(song_uuid, f"VAD segmentation failed: {exc}")
        return

    voiced_duration_s = sum(s.end_s - s.start_s for s in segments)

    # Merge into the SAME analysis artifact (§4's "one content-addressed
    # blob" tiering decision) rather than a second blob — re-read the
    # structure stage's JSON, add vad_segments, write the merged bytes at
    # their own (new) hash, repoint the summary row. The old blob is
    # simply unreferenced afterward; content-addressed storage makes that
    # cheap and correct (no delete needed, no dangling pointer risk).
    blob_store = LocalBlobStore(settings.blob_root)
    with blob_store.open(analysis.analysis_blob_sha256) as f:
        artifact = json.loads(f.read())
    artifact["vad_segments"] = [{"start_s": s.start_s, "end_s": s.end_s} for s in segments]
    new_blob_ref = _store_json_blob(blob_store, artifact)

    async with session_scope() as db:
        await record_blob(db, new_blob_ref)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()
        if analysis is not None:
            analysis.voiced_duration_s = voiced_duration_s
            analysis.analysis_blob_sha256 = new_blob_ref.sha256
            analysis.model_versions = {**analysis.model_versions, "vad": "rms-threshold-v1"}

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.rms_vad_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "rms_vad": {"model": "rms-threshold-v1", "segment_count": len(segments)},
            }
            # Terminal for today, same precedent elums/separation/task.py
            # set on Day 1 — see this module's docstring.
            ingest_job.status = IngestJobStatus.SUCCEEDED
            ingest_job.step_index = ingest_job.step_total
            ingest_job.message = "Structure, key, and vocal-activity analysis complete."
            ingest_job.completed_at = datetime.now(UTC)
        await db.commit()

    logger.info(
        "rms_vad.succeeded",
        song_id=song_id,
        segment_count=len(segments),
        voiced_duration_s=voiced_duration_s,
    )
