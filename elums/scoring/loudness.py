"""Loudness — Wed Oct 7 (W4 of IMPLEMENTATION_PLAN_2026-10-07.md).

SecondPass §3.4: per-frame RMS dBFS at 10ms, `median_db` anchored above a
-60 dB floor. Side-agnostic and DB-free (pure numpy), same precedent as
elums/scoring/measure.py: the reference side (Friday) calls the exact
same functions over the vocal stem at ingest.
"""

from __future__ import annotations

import numpy as np

FRAME_MS = 10
FLOOR_DB = -60.0


def compute_rms_db(audio: np.ndarray, sample_rate: int, frame_ms: int = FRAME_MS) -> np.ndarray:
    """One RMS dBFS value per `frame_ms` window, floored at `FLOOR_DB`
    (true digital silence has no dB value — the floor stands in for it
    rather than returning -inf and poisoning any downstream median/mean)."""
    frame_len = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    n_samples = audio.shape[0]
    if n_samples == 0:
        return np.zeros(0, dtype=np.float64)
    n_frames = int(np.ceil(n_samples / frame_len))
    out = np.full(n_frames, FLOOR_DB, dtype=np.float64)
    audio64 = audio.astype(np.float64)
    for i in range(n_frames):
        chunk = audio64[i * frame_len : (i + 1) * frame_len]
        if chunk.size == 0:
            continue
        rms = float(np.sqrt(np.mean(chunk**2)))
        db = 20.0 * np.log10(rms) if rms > 0 else FLOOR_DB
        out[i] = max(db, FLOOR_DB)
    return out


def median_db(rms_db: np.ndarray, floor_db: float = FLOOR_DB) -> float | None:
    """Median over frames strictly ABOVE the floor — true silence (or a
    track that never exceeds the floor) must not drag the "how loud is
    this performance" summary number down to a meaningless constant;
    `None` when nothing qualifies, not a fabricated -60.0."""
    above_floor = rms_db[rms_db > floor_db]
    if above_floor.size == 0:
        return None
    return float(np.median(above_floor))


def relative_db(frame_db: float, anchor_db: float | None) -> float | None:
    """A single frame's loudness relative to the take's own median —
    device-independent (§6.3's own instruction: never compare absolute
    SPL across devices, only within-take relative loudness)."""
    if anchor_db is None:
        return None
    return frame_db - anchor_db
