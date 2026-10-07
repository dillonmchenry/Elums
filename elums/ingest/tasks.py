"""The structure_beats -> rms_vad -> lyrics -> ctc_alignment -> f0 ->
note_grid job chain — Sun Oct 4 (N4 of
IMPLEMENTATION_PLAN_2026-10-04.md), extended Mon Oct 5 (L4) and Tue Oct 6
(T1/T3 of IMPLEMENTATION_PLAN_2026-10-06.md). Registered through
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

Per IMPLEMENTATION_PLAN_2026-10-04.md §5's acceptance criterion, Day 2's
`rms_vad` was terminal (overall `status` -> SUCCEEDED). Mon Oct 5 (L4,
IMPLEMENTATION_PLAN_2026-10-05.md) extends the chain:
`rms_vad -> lyrics -> ctc_alignment`, with `ctc_alignment` now the
terminal stage. `run_lyrics` picks a text source (LRCLIB, else Whisper,
see elums/ingest/lyrics.py); `run_ctc_alignment` does the actual
wav2vec2 forced alignment (elums/ingest/align.py) and the deterministic
syllable/reconciliation/vocable-fallback pass (elums/ingest/syllables.py),
merging the final `lyrics` object into the same analysis blob
`structure_beats`/`rms_vad` already write to (re-read -> merged ->
re-hashed -> repointed — the same pattern throughout this module).
"""

from __future__ import annotations

import asyncio
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
from elums.ingest.align import align_chars
from elums.ingest.chart import assemble_chart, compute_peaks, pack_peaks_blob
from elums.ingest.clap import ClapEmbeddingError, embed_audio
from elums.ingest.f0 import F0ExtractionError, extract_f0, pack_f0_blob, unpack_f0_blob, voiced_frame_ratio
from elums.ingest.key import estimate_key
from elums.ingest.lyrics import (
    fetch_lrclib,
    lrclib_result_is_thin,
    map_lrclib_to_vad_segments,
    transcribe_segments,
)
from elums.ingest.notes import build_note_grid
from elums.ingest.structure import StructureAnalysisError, run_structure
from elums.ingest.syllables import detect_vocable_events, group_syllables, reconcile_lyrics
from elums.ingest.vad import segment_vocal_activity
from elums.jobs.app import app
from elums.models.ingest_job import IngestJob, IngestJobStage, IngestJobStatus
from elums.models.song import Song
from elums.models.song_analysis import SongAnalysis
from elums.models.song_embedding import SongEmbedding
from elums.models.stem import Stem, StemKind

logger = structlog.get_logger()

_RMS_VAD_TASK_NAME = "elums.ingest.tasks.run_rms_vad"
_LYRICS_TASK_NAME = "elums.ingest.tasks.run_lyrics"
_CTC_ALIGNMENT_TASK_NAME = "elums.ingest.tasks.run_ctc_alignment"
_F0_TASK_NAME = "elums.ingest.tasks.run_f0"
_NOTE_GRID_TASK_NAME = "elums.ingest.tasks.run_note_grid"
_CLAP_EMBEDDING_TASK_NAME = "elums.ingest.tasks.run_clap_embedding"


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
            # Mon Oct 5 (L4): no longer terminal — status stays RUNNING,
            # lyrics picks up next. Also drops the step_index=step_total
            # blunt "done" signal (PROGRESS.md Day 2 loose end): the
            # per-stage *_status columns are the SPA's real source of
            # truth for progress; step_index/step_total were never a
            # meaningful fraction of the full 7-stage chain.
            ingest_job.message = "Vocal-activity analysis complete. Finding lyrics..."
        await db.commit()

    logger.info(
        "rms_vad.succeeded",
        song_id=song_id,
        segment_count=len(segments),
        voiced_duration_s=voiced_duration_s,
    )

    await app.configure_task(name=_LYRICS_TASK_NAME, queue="gpu").defer_async(song_id=song_id)


@app.task(queue="gpu")
async def run_lyrics(song_id: str) -> None:
    """Mon Oct 5 (L1): picks LRCLIB where it hits and isn't thin, else
    (or additionally, to supply ASR timings for reconciliation) Whisper
    over the VAD segments already persisted in the analysis blob. Stores
    enough state in the blob for `run_ctc_alignment` to pick up — no new
    DB columns for intermediate state, same "one analysis blob" tiering
    the rest of this module follows.
    """
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        song = await db.get(Song, song_uuid)
        ingest_job = await _get_ingest_job(db, song_uuid)
        if song is None or ingest_job is None:
            logger.warning("lyrics.song_or_job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.LYRICS
        ingest_job.lyrics_status = IngestJobStatus.RUNNING
        ingest_job.message = "Finding lyrics..."
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

    if vocals_path is None or analysis is None or vocals_stem is None:
        await _mark_stage_failed(song_uuid, "Vocal stem or structure analysis row is missing.")
        return

    blob_store = LocalBlobStore(settings.blob_root)
    with blob_store.open(analysis.analysis_blob_sha256) as f:
        artifact = json.loads(f.read())
    vad_segments = [(s["start_s"], s["end_s"]) for s in artifact.get("vad_segments", [])]

    import time

    t0 = time.monotonic()
    vram_peak_mb = 0.0
    try:
        lrclib_result = await asyncio.to_thread(
            fetch_lrclib, song.artist, song.title, vocals_stem.duration_s
        )
        needs_whisper = lrclib_result is None or lrclib_result_is_thin(
            lrclib_result, analysis.voiced_duration_s
        )

        whisper_segments: list = []
        if needs_whisper:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            whisper_segments = await asyncio.to_thread(
                transcribe_segments, str(vocals_path), vad_segments
            )
            if torch.cuda.is_available():
                vram_peak_mb = torch.cuda.max_memory_allocated() / 1024 / 1024

        if lrclib_result is not None and not lrclib_result_is_thin(
            lrclib_result, analysis.voiced_duration_s
        ):
            # LRCLIB alone is good enough — align its own text directly,
            # no Whisper, no reconciliation.
            alignment_segments = map_lrclib_to_vad_segments(lrclib_result, vad_segments)
            source_hint = "lrclib"
            reference_lines: list[str] | None = None
        elif lrclib_result is not None:
            # Thin LRCLIB hit: Whisper supplies the ASR timings,
            # LRCLIB's own lines are the reference text reconciled onto
            # them in run_ctc_alignment.
            alignment_segments = [
                {"start_s": s.start_s, "end_s": s.end_s, "text": s.text} for s in whisper_segments
            ]
            source_hint = "reconciled"
            reference_lines = [line.text for line in lrclib_result.lines]
        else:
            alignment_segments = [
                {"start_s": s.start_s, "end_s": s.end_s, "text": s.text} for s in whisper_segments
            ]
            source_hint = "whisper"
            reference_lines = None
    except Exception as exc:  # noqa: BLE001 — transformers'/network's own exceptions land here
        await _mark_stage_failed(song_uuid, f"Lyrics stage failed: {exc}")
        return
    duration_ms = int((time.monotonic() - t0) * 1000)

    # alignment_segments may already be dicts (LRCLIB path) or dataclasses
    # (Whisper path) — normalize to the dict shape the blob stores.
    normalized_segments = [
        seg if isinstance(seg, dict) else {"start_s": seg.start_s, "end_s": seg.end_s, "text": seg.text}
        for seg in alignment_segments
    ]

    artifact["lyrics_staging"] = {
        "alignment_segments": normalized_segments,
        "reference_lines": reference_lines,
        "source_hint": source_hint,
    }
    new_blob_ref = _store_json_blob(blob_store, artifact)

    async with session_scope() as db:
        await record_blob(db, new_blob_ref)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()
        if analysis is not None:
            analysis.analysis_blob_sha256 = new_blob_ref.sha256

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.lyrics_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "lyrics": {
                    "model": "lrclib" if source_hint == "lrclib" else "whisper-large-v3-turbo",
                    "source_hint": source_hint,
                    "segment_count": len(normalized_segments),
                    "duration_ms": duration_ms,
                    "vram_peak_mb": vram_peak_mb,
                },
            }
            ingest_job.message = "Lyrics found. Aligning timings..."
        await db.commit()

    logger.info(
        "lyrics.succeeded",
        song_id=song_id,
        source_hint=source_hint,
        segment_count=len(normalized_segments),
    )

    await app.configure_task(name=_CTC_ALIGNMENT_TASK_NAME, queue="gpu").defer_async(song_id=song_id)


@app.task(queue="gpu")
async def run_ctc_alignment(song_id: str) -> None:
    """Mon Oct 5 (L2+L3+L4): wav2vec2 CTC forced alignment
    (elums/ingest/align.py), then the deterministic syllable grouping /
    LCS reconciliation / energy-gated vocable fallback
    (elums/ingest/syllables.py). No longer terminal as of Tue Oct 6 (T1):
    defers `run_f0` instead of setting `status=SUCCEEDED` — the chain now
    continues through f0 -> note_grid, which is terminal (see
    `run_note_grid`'s docstring).
    """
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is None:
            logger.warning("ctc_alignment.job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.CTC_ALIGNMENT
        ingest_job.ctc_alignment_status = IngestJobStatus.RUNNING
        ingest_job.message = "Aligning lyrics to audio..."
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
        await _mark_stage_failed(song_uuid, "Vocal stem or analysis row is missing.")
        return

    blob_store = LocalBlobStore(settings.blob_root)
    with blob_store.open(analysis.analysis_blob_sha256) as f:
        artifact = json.loads(f.read())
    staging = artifact.get("lyrics_staging") or {}
    alignment_segments = [
        (s["start_s"], s["end_s"], s["text"]) for s in staging.get("alignment_segments", [])
    ]
    reference_lines = staging.get("reference_lines")
    source_hint = staging.get("source_hint", "whisper")
    vad_segments = [(s["start_s"], s["end_s"]) for s in artifact.get("vad_segments", [])]

    import time

    t0 = time.monotonic()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

        word_spans = await asyncio.to_thread(
            align_chars, str(vocals_path), alignment_segments, settings.model_root
        )
    except Exception as exc:  # noqa: BLE001 — torchaudio's own exceptions land here
        await _mark_stage_failed(song_uuid, f"CTC alignment failed: {exc}")
        return
    duration_ms = int((time.monotonic() - t0) * 1000)
    vram_peak_mb = (
        torch.cuda.max_memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0.0
    )

    import pyphen

    hyphenator = pyphen.Pyphen(lang="en_US")

    def _syllable_dicts(syllables) -> list[dict]:  # noqa: ANN001
        return [{"text": s.text, "start_s": s.start_s, "end_s": s.end_s} for s in syllables]

    if source_hint == "reconciled" and reference_lines:
        reconciled = reconcile_lyrics(reference_lines, word_spans)
        final_words = []
        for r in reconciled:
            if r.matched_span is not None:
                syllable_dicts = _syllable_dicts(group_syllables(r.matched_span, hyphenator))
            else:
                # Interpolated word: no char-level CTC timing to split on
                # (§3's "never split evenly in time" rule applies to real
                # char spans, which don't exist here) — one syllable
                # spanning the whole interpolated window.
                syllable_dicts = [{"text": r.text.upper(), "start_s": r.start_s, "end_s": r.end_s}]
            final_words.append(
                {"text": r.text, "start_s": r.start_s, "end_s": r.end_s, "syllables": syllable_dicts}
            )
        lyrics_source = "reconciled"
        vocable_source_words = reconciled
    else:
        final_words = []
        for w in word_spans:
            syllable_dicts = _syllable_dicts(group_syllables(w, hyphenator))
            final_words.append(
                {"text": w.text, "start_s": w.start_s, "end_s": w.end_s, "syllables": syllable_dicts}
            )
        lyrics_source = source_hint  # "lrclib" or "whisper"
        vocable_source_words = word_spans

    vocable_events = detect_vocable_events(vad_segments, vocable_source_words)
    word_count = len(final_words)
    syllable_count = sum(len(w["syllables"]) for w in final_words)
    vocable_event_count = len(vocable_events)

    artifact["lyrics"] = {
        "source": lyrics_source,
        "words": final_words,
        "vocable_events": [{"start_s": e.start_s, "end_s": e.end_s} for e in vocable_events],
    }
    artifact.pop("lyrics_staging", None)
    new_blob_ref = _store_json_blob(blob_store, artifact)

    async with session_scope() as db:
        await record_blob(db, new_blob_ref)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()
        if analysis is not None:
            analysis.lyrics_source = lyrics_source
            analysis.word_count = word_count
            analysis.syllable_count = syllable_count
            analysis.vocable_event_count = vocable_event_count
            analysis.analysis_blob_sha256 = new_blob_ref.sha256
            analysis.model_versions = {
                **analysis.model_versions,
                "ctc_alignment": "wav2vec2_asr_base_960h",
            }

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.ctc_alignment_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "ctc_alignment": {
                    "model": "wav2vec2_asr_base_960h",
                    "duration_ms": duration_ms,
                    "vram_peak_mb": vram_peak_mb,
                },
            }
            # Tue Oct 6 (T1): no longer terminal — status stays RUNNING,
            # f0 picks up next.
            ingest_job.message = "Lyrics aligned. Extracting pitch..."
        await db.commit()

    logger.info(
        "ctc_alignment.succeeded",
        song_id=song_id,
        lyrics_source=lyrics_source,
        word_count=word_count,
        syllable_count=syllable_count,
        vocable_event_count=vocable_event_count,
        duration_ms=duration_ms,
        vram_peak_mb=vram_peak_mb,
    )

    await app.configure_task(name=_F0_TASK_NAME, queue="gpu", lock="gpu:separation").defer_async(
        song_id=song_id
    )


@app.task(queue="gpu", lock="gpu:separation")
async def run_f0(song_id: str) -> None:
    """Tue Oct 6 (T1): per-frame F0 + confidence over the vocal stem via
    vendored RMVPE (elums/ingest/f0.py). Shares the `gpu:separation` lock
    — RMVPE's forward pass is GPU-bound, same reasoning as
    `structure_beats`.

    The F0 track is its OWN binary float16 blob (`f0_blob_sha256`), not
    merged into the analysis JSON blob — §4's tiering rule.
    """
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is None:
            logger.warning("f0.job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.F0
        ingest_job.f0_status = IngestJobStatus.RUNNING
        ingest_job.message = "Extracting pitch..."
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
        await _mark_stage_failed(song_uuid, "Vocal stem or analysis row is missing.")
        return

    try:
        f0_track = await asyncio.to_thread(extract_f0, str(vocals_path), settings.model_root)
    except F0ExtractionError as exc:
        await _mark_stage_failed(song_uuid, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        await _mark_stage_failed(song_uuid, f"F0 extraction failed: {exc}")
        return

    ratio = voiced_frame_ratio(f0_track.f0_hz)
    f0_blob_bytes = pack_f0_blob(f0_track.f0_hz, f0_track.confidence)
    blob_store = LocalBlobStore(settings.blob_root)
    import io

    f0_blob_ref = blob_store.put(io.BytesIO(f0_blob_bytes), content_type="application/octet-stream")

    async with session_scope() as db:
        await record_blob(db, f0_blob_ref)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()
        if analysis is not None:
            analysis.f0_blob_sha256 = f0_blob_ref.sha256
            analysis.frame_rate_hz = f0_track.frame_rate_hz
            analysis.voiced_frame_ratio = ratio
            analysis.model_versions = {**analysis.model_versions, "f0": "rmvpe"}

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.f0_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "f0": {
                    "model": "rmvpe",
                    "duration_ms": f0_track.duration_ms,
                    "vram_peak_mb": f0_track.vram_peak_mb,
                    "voiced_frame_ratio": ratio,
                },
            }
            ingest_job.message = "Pitch extracted. Building the note grid..."
        await db.commit()

    logger.info(
        "f0.succeeded",
        song_id=song_id,
        voiced_frame_ratio=ratio,
        duration_ms=f0_track.duration_ms,
        vram_peak_mb=f0_track.vram_peak_mb,
    )

    await app.configure_task(name=_NOTE_GRID_TASK_NAME, queue="gpu").defer_async(song_id=song_id)


@app.task(queue="gpu")
async def run_note_grid(song_id: str) -> None:
    """Tue Oct 6 (T2+T3): the deterministic note-grid segmentation
    (elums/ingest/notes.py) over the F0 track just written, then the
    chart writer + peaks (elums/ingest/chart.py). Terminal stage — mirrors
    the precedent elums/separation/task.py set on Day 1 and `run_rms_vad`/
    `run_ctc_alignment` set on Day 2/3: this is where `ingest_job.status`
    finally goes SUCCEEDED and `completed_at` is set.

    Not GPU-bound (pure numpy/soundfile) — no `gpu:separation` lock, same
    reasoning `run_rms_vad` uses.
    """
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        song = await db.get(Song, song_uuid)
        ingest_job = await _get_ingest_job(db, song_uuid)
        if song is None or ingest_job is None:
            logger.warning("note_grid.song_or_job_missing", song_id=song_id)
            return

        ingest_job.current_stage = IngestJobStage.NOTE_GRID
        ingest_job.note_grid_status = IngestJobStatus.RUNNING
        ingest_job.message = "Building the note grid..."
        await db.commit()

        blob_store = LocalBlobStore(settings.blob_root)
        vocals_row = await db.execute(
            select(Stem).where(Stem.song_id == song_uuid, Stem.kind == StemKind.VOCALS)
        )
        vocals_stem = vocals_row.scalar_one_or_none()
        instrumental_row = await db.execute(
            select(Stem).where(Stem.song_id == song_uuid, Stem.kind == StemKind.INSTRUMENTAL)
        )
        instrumental_stem = instrumental_row.scalar_one_or_none()
        instrumental_path = (
            blob_store.local_path(instrumental_stem.blob_sha256) if instrumental_stem else None
        )

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()

    if vocals_stem is None or instrumental_path is None or analysis is None or analysis.f0_blob_sha256 is None:
        await _mark_stage_failed(
            song_uuid, "Stems, analysis row, or F0 blob is missing for note-grid assembly."
        )
        return

    blob_store = LocalBlobStore(settings.blob_root)
    with blob_store.open(analysis.analysis_blob_sha256) as f:
        artifact = json.loads(f.read())
    with blob_store.open(analysis.f0_blob_sha256) as f:
        f0_hz, confidence = unpack_f0_blob(f.read())

    words = artifact.get("lyrics", {}).get("words", [])
    vocable_events = artifact.get("lyrics", {}).get("vocable_events", [])
    beats = artifact.get("beats", [])
    key_tonic = artifact.get("key", {}).get("tonic")
    key_mode = artifact.get("key", {}).get("mode")
    key_confidence = artifact.get("key", {}).get("confidence")

    import time

    # Found via the 8-song validation pass (PROGRESS.md Day 4 follow-up):
    # `note_grid`'s own `stage_results` entry never carried `duration_ms`,
    # unlike every other stage — the plan's own acceptance check 7
    # explicitly names `note_grid` alongside `f0` as needing it. No GPU
    # work happens in this stage (pure numpy/soundfile, same as
    # `run_rms_vad`), so there is no `vram_peak_mb` to measure here.
    t0 = time.monotonic()
    try:
        (
            notes,
            key_tonic_from_notes,
            key_mode_from_notes,
            key_confidence_from_notes,
            key_tonic_resolved,
            key_mode_resolved,
            key_confidence_low,
        ) = await asyncio.to_thread(
            build_note_grid,
            f0_hz,
            confidence,
            analysis.frame_rate_hz or 100.0,
            words,
            vocable_events,
            beats,
            key_tonic,
            key_mode,
            key_confidence,
        )
        peaks = await asyncio.to_thread(compute_peaks, str(instrumental_path))
    except Exception as exc:  # noqa: BLE001
        await _mark_stage_failed(song_uuid, f"Note-grid/peaks assembly failed: {exc}")
        return
    duration_ms = int((time.monotonic() - t0) * 1000)

    import io

    peaks_blob_ref = blob_store.put(
        io.BytesIO(pack_peaks_blob(peaks)), content_type="application/json"
    )

    note_dicts = [
        {
            "start_s": n.start_s,
            "end_s": n.end_s,
            "midi": n.midi,
            "midi_raw": n.midi_raw,
            "confidence": n.confidence,
            "syllable_index": n.syllable_index,
            "word_index": n.word_index,
            "is_vocable": n.is_vocable,
        }
        for n in notes
    ]

    chart = assemble_chart(
        duration_s=artifact.get("duration_s") or vocals_stem.duration_s,
        bpm=artifact.get("bpm"),
        key_tonic=key_tonic,
        key_mode=key_mode,
        key_tonic_from_notes=key_tonic_from_notes,
        key_mode_from_notes=key_mode_from_notes,
        key_confidence_from_notes=key_confidence_from_notes,
        key_tonic_resolved=key_tonic_resolved,
        key_mode_resolved=key_mode_resolved,
        key_confidence_low=key_confidence_low,
        sections=artifact.get("sections", []),
        beats=beats,
        downbeats=artifact.get("downbeats", []),
        words=words,
        notes=note_dicts,
        vocable_events=vocable_events,
        vocals_sha256=vocals_stem.blob_sha256,
        instrumental_sha256=instrumental_stem.blob_sha256,
        peaks_sha256=peaks_blob_ref.sha256,
    )
    chart_blob_ref = _store_json_blob(blob_store, chart)

    async with session_scope() as db:
        await record_blob(db, peaks_blob_ref)
        await record_blob(db, chart_blob_ref)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == song_uuid)
        )
        analysis = analysis_row.scalar_one_or_none()
        if analysis is not None:
            analysis.chart_blob_sha256 = chart_blob_ref.sha256
            analysis.peaks_blob_sha256 = peaks_blob_ref.sha256
            analysis.note_count = len(notes)
            analysis.key_tonic_from_notes = key_tonic_from_notes
            analysis.key_mode_from_notes = key_mode_from_notes
            analysis.key_confidence_from_notes = key_confidence_from_notes
            analysis.key_tonic_resolved = key_tonic_resolved
            analysis.key_mode_resolved = key_mode_resolved
            analysis.key_confidence_low = key_confidence_low
            analysis.model_versions = {**analysis.model_versions, "note_grid": "derivative-peak-segmentation-v1"}

        ingest_job = await _get_ingest_job(db, song_uuid)
        if ingest_job is not None:
            ingest_job.note_grid_status = IngestJobStatus.SUCCEEDED
            ingest_job.stage_results = {
                **ingest_job.stage_results,
                "note_grid": {
                    "model": "derivative-peak-segmentation-v1",
                    "note_count": len(notes),
                    "duration_ms": duration_ms,
                    "vram_peak_mb": None,
                },
            }
            # Terminal — see this function's docstring.
            ingest_job.status = IngestJobStatus.SUCCEEDED
            ingest_job.message = "Karaoke chart ready."
            ingest_job.completed_at = datetime.now(UTC)
        await db.commit()

    logger.info(
        "note_grid.succeeded",
        song_id=song_id,
        note_count=len(notes),
        duration_ms=duration_ms,
        key_tonic_from_notes=key_tonic_from_notes,
        key_mode_from_notes=key_mode_from_notes,
    )

    # T5: fire-and-forget, deferred AFTER status=SUCCEEDED — a CLAP
    # failure must never fail an ingest job (see run_clap_embedding).
    await app.configure_task(name=_CLAP_EMBEDDING_TASK_NAME, queue="gpu", lock="gpu:separation").defer_async(
        song_id=song_id
    )


@app.task(queue="gpu", lock="gpu:separation")
async def run_clap_embedding(song_id: str) -> None:
    """Tue Oct 6 (T5): a 512-d CLAP vector per song (elums/ingest/clap.py),
    deferred fire-and-forget by `run_note_grid` AFTER the ingest job is
    already `SUCCEEDED`. Deliberately swallows every exception — a CLAP
    failure must never fail (or re-fail) an ingest job that has already
    succeeded; this stage is not reflected in `ingest_jobs` at all.
    """
    song_uuid = uuid.UUID(song_id)

    async with session_scope() as db:
        song = await db.get(Song, song_uuid)
        if song is None:
            logger.warning("clap_embedding.song_missing", song_id=song_id)
            return
        blob_store = LocalBlobStore(settings.blob_root)
        instrumental_row = await db.execute(
            select(Stem).where(Stem.song_id == song_uuid, Stem.kind == StemKind.INSTRUMENTAL)
        )
        instrumental_stem = instrumental_row.scalar_one_or_none()
        instrumental_path = (
            blob_store.local_path(instrumental_stem.blob_sha256) if instrumental_stem else None
        )

    if instrumental_path is None:
        logger.warning("clap_embedding.instrumental_missing", song_id=song_id)
        return

    try:
        vector = await asyncio.to_thread(embed_audio, str(instrumental_path), settings.model_root)
    except ClapEmbeddingError as exc:
        logger.warning("clap_embedding.failed", song_id=song_id, reason=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 — log and move on, never raise out of this task
        logger.warning("clap_embedding.failed", song_id=song_id, reason=str(exc))
        return

    async with session_scope() as db:
        stmt = insert(SongEmbedding).values(
            song_id=song_uuid, embedding=vector.tolist(), model_version="laion/larger_clap_music_and_speech"
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["song_id"],
            set_={"embedding": vector.tolist(), "model_version": "laion/larger_clap_music_and_speech"},
        )
        await db.execute(stmt)
        await db.commit()

    logger.info("clap_embedding.succeeded", song_id=song_id)
