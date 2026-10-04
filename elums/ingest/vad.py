"""RMS-VAD vocal-activity segmentation — Sun Oct 4 (N2 of
IMPLEMENTATION_PLAN_2026-10-04.md). Deliberately crude: on an isolated
vocal stem (Saturday's Mel-Band RoFormer output), energy is close to a
sufficient statistic — a trained VAD built for speech-in-noise solves a
problem separation already removed. The crudeness is the point; these
segment boundaries exist to make Monday's Whisper pass more accurate
(ELUMS_TECHNICAL_APPROACH.md §5's finding that the WER gain comes from
better segment boundaries, not cleaner audio — not from VAD precision for
its own sake.

Thresholds are the schedule's own numbers verbatim (threshold 0.1, min
silence 1.0 s, max segment 30 s), kept as module constants rather than
scattered through call sites because Monday's Whisper batching consumes
these exact boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

RMS_THRESHOLD = 0.1  # fraction of this stem's own peak RMS, not an absolute level —
# raw dBFS/RMS varies by upload gain, and a per-track relative threshold is what
# makes this robust across arbitrary uploads (the same reasoning SecondPass's
# loudness median-anchoring uses, §3.4 of the STARS technical context).
MIN_SILENCE_S = 1.0
MAX_SEGMENT_S = 30.0

_FRAME_LENGTH = 2048
_HOP_LENGTH = 512


@dataclass(frozen=True)
class VocalSegment:
    start_s: float
    end_s: float


def _split_long_segment(start_s: float, end_s: float) -> list[VocalSegment]:
    """Hard-caps a segment at MAX_SEGMENT_S by chopping into equal-ish
    chunks — simple and sufficient; the schedule names this as a cap, not
    as "split at the best internal silence," so there is no claim here
    beyond what was asked for."""
    duration = end_s - start_s
    if duration <= MAX_SEGMENT_S:
        return [VocalSegment(start_s=start_s, end_s=end_s)]

    n_chunks = int(np.ceil(duration / MAX_SEGMENT_S))
    chunk_len = duration / n_chunks
    return [
        VocalSegment(start_s=start_s + i * chunk_len, end_s=start_s + (i + 1) * chunk_len)
        for i in range(n_chunks)
    ]


def segment_vocal_activity(vocals_path: str) -> list[VocalSegment]:
    y, sr = librosa.load(vocals_path, sr=None, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=_FRAME_LENGTH, hop_length=_HOP_LENGTH)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=_HOP_LENGTH)

    peak = float(rms.max()) if len(rms) else 0.0
    if peak <= 0.0:
        return []  # silent or empty stem — nothing to segment, not an error

    voiced = rms > (RMS_THRESHOLD * peak)

    # Contiguous True runs -> raw (start, end) pairs.
    raw_segments: list[tuple[float, float]] = []
    run_start: float | None = None
    for i, is_voiced in enumerate(voiced):
        if is_voiced and run_start is None:
            run_start = float(times[i])
        elif not is_voiced and run_start is not None:
            raw_segments.append((run_start, float(times[i])))
            run_start = None
    if run_start is not None:
        raw_segments.append((run_start, float(times[-1])))

    if not raw_segments:
        return []

    # Merge runs separated by less than MIN_SILENCE_S of silence.
    merged: list[tuple[float, float]] = [raw_segments[0]]
    for start, end in raw_segments[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end < MIN_SILENCE_S:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    segments: list[VocalSegment] = []
    for start, end in merged:
        segments.extend(_split_long_segment(start, end))
    return segments
