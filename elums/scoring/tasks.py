"""The scoring job — Wed Oct 7 (W4 of IMPLEMENTATION_PLAN_2026-10-07.md).

Registered through elums/jobs/gpu_app.py ONLY (imports elums.ingest.f0,
which imports torch — same reasoning as elums/ingest/tasks.py's module
docstring; the torch-free api/worker images must never import this
module). Shares the `gpu:separation` lock — RMVPE's forward pass over the
take audio is GPU-bound, identical reasoning to `run_f0`.

Orchestrates the karaoke-path-only pipeline SecondPass §4 describes:
extract the take's own F0 (reusing elums/ingest/f0.py verbatim — the
take is audio, same as a vocal stem), find the offset against the
chart's expected-voiced mask (elums/scoring/align.py), estimate the
global octave shift (elums/scoring/measure.py), measure every note
side-agnostically, blend the overall score (elums/scoring/score.py), and
persist a `Performance` row plus its own f0 blob and one JSON analysis
blob (§4's "one versioned analysis blob per performance" tiering rule —
same split SongAnalysis already draws for the song side).
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import uuid

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.blobs.service import record_blob
from elums.blobs.store import LocalBlobStore
from elums.config import settings
from elums.db import session_scope
from elums.ingest.f0 import F0ExtractionError, extract_f0, pack_f0_blob
from elums.jobs.app import app
from elums.models.performance import Performance, PerformanceStatus
from elums.models.song_analysis import SongAnalysis
from elums.scoring.align import find_offset
from elums.scoring.loudness import compute_rms_db, median_db
from elums.scoring.measure import estimate_octave_shift, hz_to_cents_relative, measure_note
from elums.scoring.score import alignment_sanity_check, arrival_consistency, blend_overall_score

logger = structlog.get_logger()


async def _get_performance(db: AsyncSession, performance_id: uuid.UUID) -> Performance | None:
    return await db.get(Performance, performance_id)


async def _mark_failed(performance_id: uuid.UUID, message: str) -> None:
    async with session_scope() as db:
        performance = await _get_performance(db, performance_id)
        if performance is None:
            return
        performance.status = PerformanceStatus.FAILED
        performance.error_message = message
        await db.commit()
    logger.error("scoring.failed", performance_id=str(performance_id), reason=message)


def _chart_voiced_mask(notes: list[dict], duration_s: float, frame_rate_hz: float) -> np.ndarray:
    """A chart's "expected-voiced" mask: True wherever any (non-vocable)
    note is sounding, at the F0 track's own frame rate — this IS the
    reference `find_offset` aligns the take against, since the chart has
    no raw reference signal of its own."""
    n_frames = max(1, int(round(duration_s * frame_rate_hz)))
    mask = np.zeros(n_frames, dtype=bool)
    for note in notes:
        start_idx = max(0, int(round(note["start_s"] * frame_rate_hz)))
        end_idx = min(n_frames, int(round(note["end_s"] * frame_rate_hz)))
        if end_idx > start_idx:
            mask[start_idx:end_idx] = True
    return mask


@app.task(queue="gpu", lock="gpu:separation")
async def run_scoring(performance_id: str) -> None:
    performance_uuid = uuid.UUID(performance_id)

    async with session_scope() as db:
        performance = await _get_performance(db, performance_uuid)
        if performance is None:
            logger.warning("scoring.performance_missing", performance_id=performance_id)
            return
        if performance.audio_blob_sha256 is None:
            await _mark_failed(performance_uuid, "Performance has no uploaded audio blob.")
            return

        performance.status = PerformanceStatus.SCORING
        await db.commit()

        blob_store = LocalBlobStore(settings.blob_root)
        audio_path = blob_store.local_path(performance.audio_blob_sha256)

        analysis_row = await db.execute(
            select(SongAnalysis).where(SongAnalysis.song_id == performance.song_id)
        )
        song_analysis = analysis_row.scalar_one_or_none()

    if audio_path is None or song_analysis is None or song_analysis.chart_blob_sha256 is None:
        await _mark_failed(performance_uuid, "Take audio or the song's chart is missing.")
        return

    blob_store = LocalBlobStore(settings.blob_root)
    with blob_store.open(song_analysis.chart_blob_sha256) as f:
        chart = json.loads(f.read())
    notes = [n for n in chart.get("notes", []) if not n.get("is_vocable")]
    duration_s = float(chart.get("duration_s") or 0.0)

    t0 = time.monotonic()
    try:
        f0_track = await asyncio.to_thread(extract_f0, str(audio_path), settings.model_root)
    except F0ExtractionError as exc:
        await _mark_failed(performance_uuid, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        await _mark_failed(performance_uuid, f"F0 extraction on the take failed: {exc}")
        return

    frame_rate_hz = f0_track.frame_rate_hz
    f0_hz = f0_track.f0_hz.astype(np.float64)
    confidence = f0_track.confidence.astype(np.float64)

    # --- RMS loudness (§3.4) over the same take, read directly as audio ---
    rms_db: np.ndarray | None = None
    rms_frame_rate_hz: float | None = None
    anchor_db: float | None = None
    try:
        import librosa

        audio, sr = await asyncio.to_thread(librosa.load, str(audio_path), sr=None, mono=True)
        rms_db = compute_rms_db(audio, sample_rate=sr)
        rms_frame_rate_hz = sr / max(1, int(round(sr * 0.010)))
        anchor_db = median_db(rms_db)
    except Exception as exc:  # noqa: BLE001 — loudness is supplementary, never fails scoring
        logger.warning("scoring.loudness_failed", performance_id=performance_id, reason=str(exc))

    # --- Alignment: voicing-mask grid search against the chart (§4.1a) ---
    chart_voiced = _chart_voiced_mask(notes, duration_s, frame_rate_hz)
    user_voiced = f0_hz > 0
    offset_result = find_offset(user_voiced, chart_voiced, frame_rate_hz)

    # --- Global octave shift (§4.2): per-note raw-pitch residual median ---
    residuals_semitones: list[float] = []
    for note in notes:
        start_idx = max(0, int(round((note["start_s"] + offset_result.offset_s) * frame_rate_hz)))
        end_idx = min(f0_hz.shape[0], int(round((note["end_s"] + offset_result.offset_s) * frame_rate_hz)))
        if end_idx <= start_idx:
            continue
        window = f0_hz[start_idx:end_idx]
        if not np.any(window > 0):
            continue
        cents = hz_to_cents_relative(window, note["midi"])
        voiced_cents = cents[~np.isnan(cents)]
        if voiced_cents.size == 0:
            continue
        residuals_semitones.append(float(np.median(voiced_cents)) / 100.0)
    octave_shift_semitones = estimate_octave_shift(residuals_semitones)

    # --- Per-note measurement, side-agnostic (§4.3/§4.4) ------------------
    measurements = []
    for i, note in enumerate(notes):
        shifted_start = note["start_s"] + offset_result.offset_s
        shifted_end = note["end_s"] + offset_result.offset_s
        measurement = measure_note(
            note_index=i,
            f0_hz=f0_hz,
            confidence=confidence,
            frame_rate_hz=frame_rate_hz,
            note_start_s=shifted_start,
            note_end_s=shifted_end,
            target_midi=note["midi"],
            octave_shift_semitones=octave_shift_semitones,
            rms_db=rms_db,
            rms_frame_rate_hz=rms_frame_rate_hz,
            median_rms_db=anchor_db,
        )
        measurements.append(measurement)
    duration_ms = int((time.monotonic() - t0) * 1000)
    vram_peak_mb = f0_track.vram_peak_mb

    # --- Aggregate summary (W4's frozen queryable fields) -----------------
    in_tune_values = [m.pct_in_tune for m in measurements if m.pct_in_tune is not None]
    median_cents_values = [m.median_cents for m in measurements if m.median_cents is not None]
    arrival_values = [m.arrival_offset_ms for m in measurements if m.arrival_offset_ms is not None]
    voiced_coverages = [m.voiced_coverage for m in measurements]

    pct_in_tune_overall = float(np.mean(in_tune_values)) if in_tune_values else 0.0
    median_cents_overall = float(np.median(median_cents_values)) if median_cents_values else None
    arrival_offset_ms_median = float(np.median(arrival_values)) if arrival_values else None
    mean_voiced_coverage = float(np.mean(voiced_coverages)) if voiced_coverages else 0.0

    score_overall = blend_overall_score(
        pct_in_tune=pct_in_tune_overall,
        arrival_consistency=arrival_consistency(arrival_values),
    )
    alignment_warning = (not offset_result.sufficient) or alignment_sanity_check(
        voiced_coverage=mean_voiced_coverage, pct_in_tune=pct_in_tune_overall
    )

    # --- Persist: f0 blob, analysis blob (one per performance, §4), row ---
    f0_blob_bytes = pack_f0_blob(f0_track.f0_hz, f0_track.confidence)
    f0_blob_ref = blob_store.put(io.BytesIO(f0_blob_bytes), content_type="application/octet-stream")

    analysis_payload = {
        "offset_s": offset_result.offset_s,
        "voiced_overlap_s": offset_result.voiced_overlap_s,
        "octave_shift_semitones": octave_shift_semitones,
        "notes": [
            {
                "note_index": m.note_index,
                "median_cents": m.median_cents,
                "pct_in_tune": m.pct_in_tune,
                "drift_cents_per_s": m.drift_cents_per_s,
                "voiced_coverage": m.voiced_coverage,
                "mean_voicing_confidence": m.mean_voicing_confidence,
                "note_octave_offset": m.note_octave_offset,
                "arrival_offset_ms": m.arrival_offset_ms,
                "core_start_s": m.core_start_s,
                "core_end_s": m.core_end_s,
                "user_rms_db": m.user_rms_db,
                "user_rms_relative_db": m.user_rms_relative_db,
                "vibrato_rate_hz": m.vibrato_rate_hz,
                "vibrato_extent_cents": m.vibrato_extent_cents,
                "scoop_cents": m.scoop_cents,
                "envelope_shape": m.envelope_shape,
            }
            for m in measurements
        ],
    }
    analysis_blob_ref = blob_store.put(
        io.BytesIO(json.dumps(analysis_payload).encode("utf-8")), content_type="application/json"
    )

    async with session_scope() as db:
        await record_blob(db, f0_blob_ref)
        await record_blob(db, analysis_blob_ref)

        performance = await _get_performance(db, performance_uuid)
        if performance is not None:
            performance.f0_blob_sha256 = f0_blob_ref.sha256
            performance.analysis_blob_sha256 = analysis_blob_ref.sha256
            performance.score_overall = score_overall
            performance.pct_in_tune = pct_in_tune_overall
            performance.median_cents = median_cents_overall
            performance.arrival_offset_ms_median = arrival_offset_ms_median
            performance.octave_shift_semitones = octave_shift_semitones
            performance.alignment_warning = alignment_warning
            performance.offset_s = offset_result.offset_s
            performance.model_versions = {**performance.model_versions, "f0": "rmvpe", "scoring": "karaoke-path-v1"}
            performance.status = PerformanceStatus.SUCCEEDED
        await db.commit()

    logger.info(
        "scoring.succeeded",
        performance_id=performance_id,
        score_overall=score_overall,
        pct_in_tune=pct_in_tune_overall,
        octave_shift_semitones=octave_shift_semitones,
        alignment_warning=alignment_warning,
        duration_ms=duration_ms,
        vram_peak_mb=vram_peak_mb,
    )
