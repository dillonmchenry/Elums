"""Chart writer + peaks — Tue Oct 6 (T3 of
IMPLEMENTATION_PLAN_2026-10-06.md). DB-free and pure/blocking, mirroring
the rest of elums/ingest/: `compute_peaks` is a real (if small) DSP call,
`assemble_chart` is pure dict assembly. Called from
elums/ingest/tasks.py's `run_note_grid`, the new terminal stage.

Two separate blobs, deliberately: the chart (`assemble_chart`'s return
value, JSON) is the client-facing bundle `GET /api/songs/{id}` points at;
peaks (`compute_peaks`) is its own small blob, over the INSTRUMENTAL
(what the page actually plays) — EC-3's resolution: `audiowaveform` is
not apt-installable on the `python:3.13-slim` base, so peaks are computed
in Python (soundfile + numpy min/max per bucket) instead of shelling out
to a tool that doesn't exist in this image. Zero new system dependencies,
same client-visible behaviour.
"""

from __future__ import annotations

import json

import numpy as np

CHART_VERSION = 1
DEFAULT_PEAK_BUCKETS = 2000


def compute_peaks(instrumental_path: str, num_buckets: int = DEFAULT_PEAK_BUCKETS) -> dict:
    """Per-bucket (min, max) sample pairs, mono, normalized to [-1, 1] —
    exactly what wavesurfer v8's `peaks` option expects to skip its own
    client-side decode. `num_buckets` is independent of track length (a
    fixed-resolution overview, not fixed-duration-per-bucket), matching
    the schedule's "precomputed peaks, no client-side decode" intent.
    """
    import soundfile as sf

    audio, _sr = sf.read(instrumental_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # mono mixdown — peaks are a visual overview, not a stem

    n_samples = audio.shape[0]
    if n_samples == 0:
        return {"buckets": 0, "min": [], "max": []}

    bucket_count = min(num_buckets, n_samples)
    edges = np.linspace(0, n_samples, bucket_count + 1, dtype=np.int64)

    mins: list[float] = []
    maxs: list[float] = []
    for i in range(bucket_count):
        start, end = edges[i], max(edges[i + 1], edges[i] + 1)
        chunk = audio[start:end]
        mins.append(round(float(chunk.min()), 4))
        maxs.append(round(float(chunk.max()), 4))

    return {"buckets": bucket_count, "min": mins, "max": maxs}


def pack_peaks_blob(peaks: dict) -> bytes:
    return json.dumps(peaks).encode("utf-8")


def assemble_chart(
    *,
    duration_s: float,
    bpm: float | None,
    key_tonic: str | None,
    key_mode: str | None,
    key_tonic_from_notes: str | None,
    key_mode_from_notes: str | None,
    key_confidence_from_notes: float | None,
    sections: list[dict],
    beats: list[float],
    downbeats: list[float],
    words: list[dict],
    notes: list[dict],
    vocable_events: list[dict],
    vocals_sha256: str,
    instrumental_sha256: str,
    peaks_sha256: str,
) -> dict:
    """Assembles the one fetchable artifact `GET /api/songs/{id}` points
    at. Versioned from the first write (`CHART_VERSION`) so a later
    schema change is additive, not a silent break for already-ingested
    songs."""
    return {
        "version": CHART_VERSION,
        "duration_s": duration_s,
        "bpm": bpm,
        "key": {
            "tonic": key_tonic,
            "mode": key_mode,
            "tonic_from_notes": key_tonic_from_notes,
            "mode_from_notes": key_mode_from_notes,
            "confidence_from_notes": key_confidence_from_notes,
        },
        "sections": sections,
        "beats": beats,
        "downbeats": downbeats,
        "words": words,
        "notes": notes,
        "vocable_events": vocable_events,
        "stems": {
            "vocals_sha256": vocals_sha256,
            "instrumental_sha256": instrumental_sha256,
        },
        "peaks_sha256": peaks_sha256,
    }
