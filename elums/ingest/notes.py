"""Note grid — Tue Oct 6 (T2 of IMPLEMENTATION_PLAN_2026-10-06.md).
Deterministic segmentation over elums/ingest/f0.py's RMVPE track: no
model here, same "tests on the logic, not the models" precedent as
elums/ingest/vad.py and elums/ingest/syllables.py. DB-free and pure;
called from elums/ingest/tasks.py's `run_note_grid`.

Algorithm, per the plan's §5 and T2 section: convert F0 to cents, find
segment boundaries at derivative peaks and confidence troughs, clip every
segment to its syllable span (a note never crosses a syllable boundary —
`vocable_events` are the one exception, unconstrained spans per §5's
Whisper-deletion mitigation), drop segments under ~80ms, set pitch from
the voiced-frame median, snap onsets to the nearest beat only when within
half a beat, quantize pitch class to the detected key while recording the
pre-quantization MIDI for auditability.

**Frozen** (same section): `Note(start_s, end_s, midi, midi_raw,
confidence, syllable_index, word_index, is_vocable)`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_NOTE_DURATION_S = 0.08
# A jump of this many semitones between consecutive voiced frames is a
# "derivative peak" — the note almost certainly changed pitch here.
PITCH_JUMP_SEMITONES = 0.8
# A frame whose confidence drops to less than this fraction of the
# segment's running max confidence is a "confidence trough" — RMVPE
# losing track, usually at a note boundary.
CONFIDENCE_TROUGH_RATIO = 0.6

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR_SCALE_STEPS = {0, 2, 4, 5, 7, 9, 11}
_MINOR_SCALE_STEPS = {0, 2, 3, 5, 7, 8, 10}  # natural minor


@dataclass(frozen=True)
class Note:
    start_s: float
    end_s: float
    midi: int  # key-quantized pitch
    midi_raw: float  # voiced-frame median, pre-quantization — auditable
    confidence: float
    syllable_index: int | None
    word_index: int | None
    is_vocable: bool


def _hz_to_midi(f0_hz: np.ndarray) -> np.ndarray:
    """0 Hz (unvoiced) maps to NaN, never to a bogus negative-infinity
    MIDI value from log2(0)."""
    midi = np.full(f0_hz.shape, np.nan, dtype=np.float64)
    voiced = f0_hz > 0
    midi[voiced] = 69.0 + 12.0 * np.log2(f0_hz[voiced].astype(np.float64) / 440.0)
    return midi


def _voiced_runs(voiced: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as [start, end) index pairs."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, is_voiced in enumerate(voiced):
        if is_voiced and start is None:
            start = i
        elif not is_voiced and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(voiced)))
    return runs


def _split_run_at_boundaries(
    midi: np.ndarray, confidence: np.ndarray, run_start: int, run_end: int
) -> list[tuple[int, int]]:
    """Splits one contiguous voiced run at derivative peaks and
    confidence troughs. Returns [start, end) sub-ranges within
    [run_start, run_end)."""
    if run_end - run_start <= 1:
        return [(run_start, run_end)]

    boundaries = [run_start]
    running_max_conf = float(confidence[run_start])
    for i in range(run_start + 1, run_end):
        pitch_jump = abs(float(midi[i]) - float(midi[i - 1])) > PITCH_JUMP_SEMITONES
        running_max_conf = max(running_max_conf, float(confidence[i]))
        confidence_trough = (
            running_max_conf > 0 and float(confidence[i]) < CONFIDENCE_TROUGH_RATIO * running_max_conf
        )
        if pitch_jump or confidence_trough:
            boundaries.append(i)
            running_max_conf = float(confidence[i])
    boundaries.append(run_end)

    return [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1) if boundaries[i + 1] > boundaries[i]]


def _segment_span(
    f0_hz: np.ndarray,
    confidence: np.ndarray,
    frame_rate_hz: float,
    span_start_s: float,
    span_end_s: float,
) -> list[tuple[float, float, float, float]]:
    """Returns (start_s, end_s, midi_raw, confidence) for every note found
    inside [span_start_s, span_end_s) — never crossing it, since the
    caller already sliced the arrays to this window."""
    start_idx = max(0, int(round(span_start_s * frame_rate_hz)))
    end_idx = min(f0_hz.shape[0], int(round(span_end_s * frame_rate_hz)))
    if end_idx <= start_idx:
        return []

    f0_slice = f0_hz[start_idx:end_idx]
    conf_slice = confidence[start_idx:end_idx]
    midi_slice = _hz_to_midi(f0_slice)
    voiced = ~np.isnan(midi_slice)

    notes: list[tuple[float, float, float, float]] = []
    for run_start, run_end in _voiced_runs(voiced):
        for sub_start, sub_end in _split_run_at_boundaries(midi_slice, conf_slice, run_start, run_end):
            note_start_s = span_start_s + sub_start / frame_rate_hz
            note_end_s = span_start_s + sub_end / frame_rate_hz
            # `start_idx`/`end_idx` above are independently rounded to the
            # nearest frame (up to ~0.5 frames of slack each, ~10ms total
            # at 100Hz) — found directly against a real song (T6): 7/221
            # notes overshot their syllable's own end_s by ~9ms, a
            # frame-rounding artifact, not a segmentation error. Clamping
            # here enforces "never crosses a syllable boundary" exactly,
            # rather than relying on the rounding to land inside it.
            note_start_s = max(note_start_s, span_start_s)
            note_end_s = min(note_end_s, span_end_s)
            if note_end_s - note_start_s < MIN_NOTE_DURATION_S:
                continue
            midi_raw = float(np.median(midi_slice[sub_start:sub_end]))
            note_confidence = float(np.mean(conf_slice[sub_start:sub_end]))
            notes.append((note_start_s, note_end_s, midi_raw, note_confidence))
    return notes


def _snap_onset_to_beat(onset_s: float, beats: list[float]) -> float:
    """Snaps `onset_s` to the nearest beat only when within half the
    local beat interval — never dragged across an unrelated beat on a
    sparse/irregular grid."""
    if len(beats) < 2:
        return onset_s
    beats_arr = np.asarray(beats, dtype=np.float64)
    idx = int(np.argmin(np.abs(beats_arr - onset_s)))
    nearest_beat = float(beats_arr[idx])

    # Local beat interval: distance to the neighbouring beat on whichever
    # side nearest_beat sits relative to onset_s.
    if idx + 1 < len(beats_arr):
        interval_next = beats_arr[idx + 1] - beats_arr[idx]
    else:
        interval_next = beats_arr[idx] - beats_arr[idx - 1] if idx > 0 else None
    if idx > 0:
        interval_prev = beats_arr[idx] - beats_arr[idx - 1]
    else:
        interval_prev = interval_next

    local_interval = interval_prev if interval_prev else interval_next
    if not local_interval or local_interval <= 0:
        return onset_s

    if abs(onset_s - nearest_beat) <= 0.5 * local_interval:
        return nearest_beat
    return onset_s


def _quantize_to_key(midi_raw: float, key_tonic: str | None, key_mode: str | None) -> int:
    """Rounds to the nearest integer MIDI note, then shifts the pitch
    class (preserving octave) to the nearest in-key pitch class — never
    the other way around, so a note already in-key is never moved."""
    midi_round = int(round(midi_raw))
    if key_tonic is None or key_tonic not in _PITCH_CLASSES:
        return midi_round

    tonic_index = _PITCH_CLASSES.index(key_tonic)
    scale_steps = _MINOR_SCALE_STEPS if key_mode == "minor" else _MAJOR_SCALE_STEPS
    in_key_pcs = {(tonic_index + step) % 12 for step in scale_steps}

    octave, pc = divmod(midi_round, 12)
    if pc in in_key_pcs:
        return midi_round

    # Nearest in-key pitch class by circular distance; ties broken toward
    # the lower pitch class (arbitrary but deterministic).
    best_pc = min(in_key_pcs, key=lambda candidate: (min((candidate - pc) % 12, (pc - candidate) % 12), candidate))
    delta = best_pc - pc
    if delta > 6:
        delta -= 12
    elif delta < -6:
        delta += 12
    return octave * 12 + pc + delta


def _note_histogram_key_cross_check(
    notes_raw_midi: list[float], notes_duration_s: list[float]
) -> tuple[str, str, float]:
    """Builds a duration-weighted 12-bin pitch-class histogram from the
    (pre-quantization) note grid and runs it through the same
    Krumhansl-Schmuckler correlation elums/ingest/key.py uses for chroma —
    §5's documented cross-check for a near-tie KS result on the
    chroma-only estimate."""
    from elums.ingest.key_profiles import correlate_all_candidates

    histogram = np.zeros(12, dtype=np.float64)
    for midi_raw, duration_s in zip(notes_raw_midi, notes_duration_s):
        pc = int(round(midi_raw)) % 12
        histogram[pc] += duration_s

    if histogram.sum() <= 0:
        return "C", "major", 0.0

    candidates = correlate_all_candidates(histogram)
    best_tonic, best_mode, best_corr = candidates[0]
    second_corr = candidates[1][2]
    return best_tonic, best_mode, best_corr - second_corr


# Wed Oct 7 (W0 of IMPLEMENTATION_PLAN_2026-10-07.md): a margin (not a
# correlation) below this on BOTH sides means neither estimator is
# confident — surfaced via `key_confidence_low` rather than silently
# picking a winner anyway. Per the plan's own range (0.05-0.08),
# documented against `hot-n-cold`'s real 0.023/0.022 pair (Day 4 §10).
KEY_CONFIDENCE_LOW_THRESHOLD = 0.06


def _resolve_key(
    key_tonic: str | None,
    key_mode: str | None,
    key_confidence: float | None,
    key_tonic_from_notes: str,
    key_mode_from_notes: str,
    key_confidence_from_notes: float,
) -> tuple[str, str, bool]:
    """The higher-margin side wins the resolved key that `_quantize_to_key`
    consumes. Both raw estimates and both margins are kept on the model
    (`key_tonic`/`key_mode`/`key_confidence` from chroma,
    `key_tonic_from_notes`/`key_mode_from_notes`/`key_confidence_from_notes`
    from this module) for audit — this function only decides the winner,
    it never overwrites either raw value. `key_confidence_low` is true
    when the WINNING margin is still below the threshold: a low-confidence
    resolution is a real, surfaced fact, not a silently confident one."""
    chroma_confidence = key_confidence if key_confidence is not None else -1.0
    if key_tonic is not None and chroma_confidence >= key_confidence_from_notes:
        resolved_tonic, resolved_mode, winning_confidence = key_tonic, key_mode or "major", chroma_confidence
    else:
        resolved_tonic, resolved_mode, winning_confidence = (
            key_tonic_from_notes,
            key_mode_from_notes,
            key_confidence_from_notes,
        )
    confidence_low = winning_confidence < KEY_CONFIDENCE_LOW_THRESHOLD
    return resolved_tonic, resolved_mode, confidence_low


def build_note_grid(
    f0_hz: np.ndarray,
    confidence: np.ndarray,
    frame_rate_hz: float,
    words: list[dict],
    vocable_events: list[dict],
    beats: list[float],
    key_tonic: str | None,
    key_mode: str | None,
    key_confidence: float | None = None,
) -> tuple[list[Note], str, str, float, str, str, bool]:
    """`words`: the chart's `lyrics.words[]`, each with `syllables[]`
    (`{text, start_s, end_s}`). `vocable_events`: `{start_s, end_s}`
    dicts, treated as unconstrained spans (no syllable clipping).

    Returns `(notes, key_tonic_from_notes, key_mode_from_notes,
    key_confidence_from_notes, key_tonic_resolved, key_mode_resolved,
    key_confidence_low)`. `key_confidence` is the chroma estimator's own
    margin (`SongAnalysis.key_confidence`) — needed here (Wed Oct 7, W0)
    to decide which side's key the resolved value (and therefore
    `_quantize_to_key`) uses. Neither raw `key_tonic`/`key_mode` nor
    `key_tonic_from_notes`/`key_mode_from_notes` is ever overwritten by
    this resolution — both are returned unchanged for audit, per T2's
    original instruction.
    """
    # Each raw note carries its own span bounds (`span_start_s`) alongside
    # it — never crossing a syllable boundary (§5's own invariant) means
    # beat-snapping below must be clamped to the span it came from, not
    # just checked against the note's own end_s.
    raw_notes: list[tuple[float, float, float, float, float, int | None, int | None, bool]] = []

    for word_index, word in enumerate(words):
        for syllable_index, syllable in enumerate(word.get("syllables", [])):
            for start_s, end_s, midi_raw, note_conf in _segment_span(
                f0_hz, confidence, frame_rate_hz, syllable["start_s"], syllable["end_s"]
            ):
                raw_notes.append(
                    (start_s, end_s, midi_raw, note_conf, syllable["start_s"], syllable_index, word_index, False)
                )

    for vocable in vocable_events:
        for start_s, end_s, midi_raw, note_conf in _segment_span(
            f0_hz, confidence, frame_rate_hz, vocable["start_s"], vocable["end_s"]
        ):
            raw_notes.append((start_s, end_s, midi_raw, note_conf, vocable["start_s"], None, None, True))

    raw_notes.sort(key=lambda n: n[0])

    key_tonic_from_notes, key_mode_from_notes, key_confidence_from_notes = _note_histogram_key_cross_check(
        [n[2] for n in raw_notes], [n[1] - n[0] for n in raw_notes]
    )
    key_tonic_resolved, key_mode_resolved, key_confidence_low = _resolve_key(
        key_tonic, key_mode, key_confidence, key_tonic_from_notes, key_mode_from_notes, key_confidence_from_notes
    )

    notes: list[Note] = []
    for start_s, end_s, midi_raw, note_conf, span_start_s, syllable_index, word_index, is_vocable in raw_notes:
        snapped_start = _snap_onset_to_beat(start_s, beats)
        # Beat-snapping must never (a) pull a note back under the
        # minimum duration it already passed in `_segment_span`, or (b)
        # pull it before its own span's start — found directly against a
        # real song (T6): 98/221 notes on a first real run landed before
        # their syllable's own start_s, because the half-beat check in
        # `_snap_onset_to_beat` only looks at distance-to-beat, never at
        # the span (or resulting note length) it is snapping inside of.
        if (
            snapped_start >= end_s
            or snapped_start < span_start_s
            or end_s - snapped_start < MIN_NOTE_DURATION_S
        ):
            snapped_start = start_s
        quantized_midi = _quantize_to_key(midi_raw, key_tonic_resolved, key_mode_resolved)
        notes.append(
            Note(
                start_s=snapped_start,
                end_s=end_s,
                midi=quantized_midi,
                midi_raw=midi_raw,
                confidence=note_conf,
                syllable_index=syllable_index,
                word_index=word_index,
                is_vocable=is_vocable,
            )
        )

    return (
        notes,
        key_tonic_from_notes,
        key_mode_from_notes,
        key_confidence_from_notes,
        key_tonic_resolved,
        key_mode_resolved,
        key_confidence_low,
    )
