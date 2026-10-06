"""Tue Oct 6 (T2's acceptance check 9 / M1 acceptance check 9):
deterministic-layer unit tests for elums/ingest/notes.py — segmentation,
syllable clipping, beat snapping, key quantization — on synthetic F0.
No model, no torch, no librosa; "numpy" is the only non-stdlib import,
same precedent elums/ingest/syllables.py and elums/ingest/vad.py set.
"""

from __future__ import annotations

import numpy as np
import pytest

from elums.ingest.notes import (
    MIN_NOTE_DURATION_S,
    _quantize_to_key,
    _snap_onset_to_beat,
    build_note_grid,
)

FRAME_RATE_HZ = 100.0


def _constant_pitch_track(midi: float, duration_s: float, confidence: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    n_frames = int(round(duration_s * FRAME_RATE_HZ))
    f0_hz = np.full(n_frames, 440.0 * 2 ** ((midi - 69) / 12.0), dtype=np.float32)
    conf = np.full(n_frames, confidence, dtype=np.float32)
    return f0_hz, conf


def _two_note_track(midi_a: float, midi_b: float, duration_each_s: float) -> tuple[np.ndarray, np.ndarray]:
    f0_a, conf_a = _constant_pitch_track(midi_a, duration_each_s)
    f0_b, conf_b = _constant_pitch_track(midi_b, duration_each_s)
    return np.concatenate([f0_a, f0_b]), np.concatenate([conf_a, conf_b])


# --- segmentation / syllable clipping -----------------------------------


def test_build_note_grid_single_steady_pitch_syllable_yields_one_note() -> None:
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)  # C4, steady
    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": 1.0}]}]

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].syllable_index == 0
    assert notes[0].word_index == 0
    assert not notes[0].is_vocable
    assert notes[0].midi_raw == pytest.approx(60.0, abs=0.5)


def test_build_note_grid_never_crosses_a_syllable_boundary() -> None:
    # Two syllables, a pitch jump exactly at the syllable boundary — the
    # boundary alone is enough to force a split even without the pitch
    # jump, but this also confirms notes stay inside their own span.
    f0_hz, confidence = _two_note_track(midi_a=60, midi_b=64, duration_each_s=0.5)
    words = [
        {
            "syllables": [
                {"text": "HEL", "start_s": 0.0, "end_s": 0.5},
                {"text": "LO", "start_s": 0.5, "end_s": 1.0},
            ]
        }
    ]

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    for note in notes:
        if note.syllable_index == 0:
            assert note.start_s >= 0.0 and note.end_s <= 0.5 + 1e-9
        else:
            assert note.start_s >= 0.5 - 1e-9 and note.end_s <= 1.0 + 1e-9


def test_build_note_grid_pitch_jump_within_one_syllable_splits_into_two_notes() -> None:
    f0_hz, confidence = _two_note_track(midi_a=60, midi_b=67, duration_each_s=0.5)
    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": 1.0}]}]

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert len(notes) == 2
    assert notes[0].midi_raw == pytest.approx(60.0, abs=0.5)
    assert notes[1].midi_raw == pytest.approx(67.0, abs=0.5)


def test_build_note_grid_drops_segments_shorter_than_the_minimum() -> None:
    # A single-frame blip (10ms) in the middle of a steady note — too
    # short to be its own note (MIN_NOTE_DURATION_S = 80ms).
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)
    blip_frame = 50
    f0_hz[blip_frame] = 440.0 * 2 ** ((72 - 69) / 12.0)  # one wild frame

    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": 1.0}]}]
    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    # The blip itself (1 frame = 10ms < 80ms) must not survive as its own
    # note — total note count stays small (1 or 2, from splitting around
    # the blip), not 3 separate notes each counted.
    assert all(n.end_s - n.start_s >= MIN_NOTE_DURATION_S - 1e-9 for n in notes)


def test_build_note_grid_unvoiced_gap_produces_no_note() -> None:
    voiced, conf = _constant_pitch_track(midi=60, duration_s=0.5)
    unvoiced = np.zeros(int(0.5 * FRAME_RATE_HZ), dtype=np.float32)
    unvoiced_conf = np.zeros_like(unvoiced)
    f0_hz = np.concatenate([voiced, unvoiced])
    confidence = np.concatenate([conf, unvoiced_conf])

    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": 1.0}]}]
    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].end_s <= 0.5 + 1e-9


def test_build_note_grid_vocable_events_are_unconstrained_spans() -> None:
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)
    vocable_events = [{"start_s": 0.0, "end_s": 1.0}]

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, [], vocable_events, beats=[], key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].is_vocable
    assert notes[0].syllable_index is None
    assert notes[0].word_index is None


# --- note count plausibility (M1 acceptance check 6 style) --------------


def test_build_note_grid_note_count_is_plausible_not_thousands() -> None:
    # A few dozen short syllables, each steady pitch — should yield one
    # note per syllable, in the low hundreds at most for a real song.
    rng_duration = 0.2
    words = []
    f0_parts = []
    conf_parts = []
    for i in range(40):
        midi = 60 + (i % 5)
        f0, conf = _constant_pitch_track(midi, rng_duration)
        f0_parts.append(f0)
        conf_parts.append(conf)
        start_s = i * rng_duration
        words.append({"syllables": [{"text": "LA", "start_s": start_s, "end_s": start_s + rng_duration}]})

    f0_hz = np.concatenate(f0_parts)
    confidence = np.concatenate(conf_parts)

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert 0 < len(notes) < 1000
    assert len(notes) == 40


# --- beat snapping --------------------------------------------------------


def test_snap_onset_to_beat_snaps_within_half_a_beat() -> None:
    beats = [0.0, 1.0, 2.0, 3.0]
    assert _snap_onset_to_beat(1.1, beats) == pytest.approx(1.0)
    assert _snap_onset_to_beat(0.9, beats) == pytest.approx(1.0)


def test_snap_onset_to_beat_leaves_far_onsets_untouched() -> None:
    # Irregular spacing (as if the beat tracker lost one beat) — nearest
    # beat is 1.0 (0.9 away), but the LOCAL interval around it is still
    # 1.0s (0.0 -> 1.0), so 0.9 is past the half-beat threshold and must
    # stay put, even though 1.9 is also closer to 1.0 than to 3.0.
    beats = [0.0, 1.0, 3.0]
    assert _snap_onset_to_beat(1.9, beats) == pytest.approx(1.9)


def test_snap_onset_to_beat_with_no_beats_is_a_no_op() -> None:
    assert _snap_onset_to_beat(1.234, []) == pytest.approx(1.234)


def test_build_note_grid_never_snaps_a_note_below_the_minimum_duration() -> None:
    # Found directly against a real song (T6): a beat landing just
    # before a note's end snapped the onset forward and produced a
    # ~1ms note. A beat 70ms before the note's end (within the 0.5s
    # half-beat window on this 1.0s grid) must NOT be applied, since the
    # resulting note would be shorter than MIN_NOTE_DURATION_S (80ms).
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)
    words = [{"syllables": [{"text": "LA", "start_s": 0.93, "end_s": 1.93}]}]
    beats = [1.0]  # 70ms before the syllable's end — inside the snap window

    # Shift the pitch track to start at 0.93s to line up with the syllable.
    import numpy as np

    pad = np.zeros(93, dtype=np.float32)
    f0_hz = np.concatenate([pad, f0_hz])
    confidence = np.concatenate([pad, confidence])

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=beats, key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].end_s - notes[0].start_s >= MIN_NOTE_DURATION_S


def test_build_note_grid_never_snaps_a_note_before_its_own_syllable_start() -> None:
    # Found directly against a real song (T6, 98/221 violations on the
    # first full real-song run): a beat just before a syllable's own
    # start — within the half-beat snap window — pulled the note's onset
    # BEFORE the syllable boundary entirely. The snap must be rejected,
    # not just clamped, since the point of beat-snapping is to align an
    # onset that's already inside the span, not relocate it outside.
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)
    words = [{"syllables": [{"text": "LA", "start_s": 0.2, "end_s": 1.2}]}]
    beats = [0.05]  # 150ms before the syllable start — inside a 1.0s half-beat window

    import numpy as np

    pad = np.zeros(20, dtype=np.float32)
    f0_hz = np.concatenate([pad, f0_hz])
    confidence = np.concatenate([pad, confidence])

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=beats, key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].start_s >= 0.2 - 1e-9


def test_build_note_grid_clamps_frame_rounding_overshoot_at_the_span_end() -> None:
    # Found directly against a real song (T6): a non-10ms-aligned syllable
    # boundary let independent start/end frame rounding in `_segment_span`
    # overshoot the syllable's own end_s by ~9ms on 7/221 notes. A
    # syllable ending at a fractional frame (not a clean multiple of
    # 1/FRAME_RATE_HZ) reproduces it directly.
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=1.0)
    syllable_end_s = 0.9951  # deliberately not frame-aligned (100Hz grid)
    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": syllable_end_s}]}]

    notes, _, _, _ = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert len(notes) == 1
    assert notes[0].end_s <= syllable_end_s + 1e-9


# --- key quantization -----------------------------------------------------


def test_quantize_to_key_leaves_in_key_note_untouched() -> None:
    # MIDI 60 = C, in C major.
    assert _quantize_to_key(60.3, key_tonic="C", key_mode="major") == 60


def test_quantize_to_key_shifts_out_of_key_note_to_nearest_scale_degree() -> None:
    # MIDI 61 = C#, not in C major — nearest in-key pitch classes are C
    # (60) and D (62), equidistant; tie-break is deterministic (lower).
    quantized = _quantize_to_key(61.0, key_tonic="C", key_mode="major")
    assert quantized in (60, 62)


def test_quantize_to_key_with_no_key_returns_rounded_raw_midi() -> None:
    assert _quantize_to_key(60.6, key_tonic=None, key_mode=None) == 61


# --- key cross-check -------------------------------------------------------


def test_build_note_grid_returns_a_key_tonic_from_notes() -> None:
    # All notes are C (midi 60, 72, ...) — the histogram cross-check
    # should land on C, mirroring elums/ingest/key.py's own correlation.
    f0_hz, confidence = _constant_pitch_track(midi=60, duration_s=2.0)
    words = [{"syllables": [{"text": "LA", "start_s": 0.0, "end_s": 2.0}]}]

    _, key_tonic_from_notes, _, key_confidence_from_notes = build_note_grid(
        f0_hz, confidence, FRAME_RATE_HZ, words, [], beats=[], key_tonic=None, key_mode=None
    )

    assert key_tonic_from_notes in {"C", "A"}  # KS major/minor profiles both peak near a pure pitch class
    assert key_confidence_from_notes >= 0.0
