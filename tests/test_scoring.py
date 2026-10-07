"""Wed Oct 7 (W4's acceptance check 9): deterministic-layer unit tests
for elums/scoring/* over synthetic f0 — offset search, octave folding,
arrival edge-margin rejection, core-window shifting, median-anchored
loudness, score blending. No model, no torch — same "tests on the logic,
not the models" precedent as tests/test_notes.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from elums.scoring.align import MIN_OVERLAP_S, find_offset
from elums.scoring.loudness import FLOOR_DB, compute_rms_db, median_db
from elums.scoring.measure import (
    core_window,
    detect_arrival,
    estimate_octave_shift,
    fold_octave_cents,
    measure_note,
)
from elums.scoring.score import alignment_sanity_check, arrival_consistency, blend_overall_score

FRAME_RATE_HZ = 100.0


# --- align.py: offset search -----------------------------------------------


def test_find_offset_recovers_a_known_late_start() -> None:
    # Chart is voiced for 2s starting at t=0; the user recording started
    # 300ms late, so the user's own voiced span is at t=0.3..2.3 on their
    # own clock. find_offset should recover offset_s ~= +0.3 (user late).
    chart_voiced = np.zeros(300, dtype=bool)
    chart_voiced[0:200] = True
    user_voiced = np.zeros(300, dtype=bool)
    user_voiced[30:230] = True

    result = find_offset(user_voiced, chart_voiced, FRAME_RATE_HZ)

    assert result.offset_s == pytest.approx(0.3, abs=0.04)
    assert result.sufficient


def test_find_offset_recovers_a_known_early_start() -> None:
    chart_voiced = np.zeros(300, dtype=bool)
    chart_voiced[100:300] = True
    user_voiced = np.zeros(300, dtype=bool)
    user_voiced[80:280] = True  # user started 200ms early relative to chart

    result = find_offset(user_voiced, chart_voiced, FRAME_RATE_HZ)

    assert result.offset_s == pytest.approx(-0.2, abs=0.04)
    assert result.sufficient


def test_find_offset_insufficient_overlap_on_silence() -> None:
    chart_voiced = np.zeros(300, dtype=bool)
    chart_voiced[0:200] = True
    user_voiced = np.zeros(300, dtype=bool)  # user never sang anything

    result = find_offset(user_voiced, chart_voiced, FRAME_RATE_HZ)

    assert not result.sufficient
    assert result.voiced_overlap_s < MIN_OVERLAP_S


# --- measure.py: octave folding ---------------------------------------------


def test_fold_octave_cents_folds_large_residual_into_band() -> None:
    cents = np.array([1300.0, -1300.0, 700.0, -700.0, np.nan])
    folded = fold_octave_cents(cents)

    assert folded[0] == pytest.approx(100.0)
    assert folded[1] == pytest.approx(-100.0)
    assert folded[2] == pytest.approx(-500.0)
    assert folded[3] == pytest.approx(500.0)
    assert np.isnan(folded[4])


def test_estimate_octave_shift_rounds_to_nearest_whole_octave() -> None:
    assert estimate_octave_shift([-12.2, -11.8, -12.0]) == -12
    assert estimate_octave_shift([0.3, -0.2, 0.1]) == 0
    assert estimate_octave_shift([]) == 0


def test_measure_note_octave_down_take_still_scores_in_tune_after_shift() -> None:
    # User sings a full octave below the chart's target the whole note —
    # applying octave_shift_semitones=-12 before measuring should bring
    # pct_in_tune back up near 1.0.
    duration_s = 1.0
    n_frames = int(duration_s * FRAME_RATE_HZ)
    target_midi = 69  # A4, 440 Hz
    user_hz = 440.0 * 2 ** ((target_midi - 12 - 69) / 12.0)  # one octave down
    f0_hz = np.full(n_frames, user_hz, dtype=np.float64)
    confidence = np.full(n_frames, 0.9, dtype=np.float64)

    measurement = measure_note(
        note_index=0,
        f0_hz=f0_hz,
        confidence=confidence,
        frame_rate_hz=FRAME_RATE_HZ,
        note_start_s=0.0,
        note_end_s=duration_s,
        target_midi=target_midi,
        octave_shift_semitones=-12,
    )

    assert measurement.pct_in_tune == pytest.approx(1.0, abs=1e-6)
    assert abs(measurement.median_cents) < 5.0


# --- measure.py: arrival edge-margin rejection -----------------------------


def test_detect_arrival_rejects_onset_too_close_to_far_edge() -> None:
    # Voicing starts only 10ms before the note ends (under the 20ms
    # margin) — this is bleed from the NEXT note's onset, not a real
    # arrival for THIS note, and must be rejected (None).
    mask = np.zeros(100, dtype=bool)
    mask[99] = True  # one frame before end, inside [0.0, 1.0)s window at 100Hz

    arrival = detect_arrival(mask, FRAME_RATE_HZ, note_start_s=0.0, note_end_s=1.0, mode="onset")

    assert arrival is None


def test_detect_arrival_accepts_a_clean_mid_window_onset() -> None:
    mask = np.zeros(100, dtype=bool)
    mask[30:] = True  # voicing starts 300ms into the window

    arrival = detect_arrival(mask, FRAME_RATE_HZ, note_start_s=0.0, note_end_s=1.0, mode="onset")

    assert arrival == pytest.approx(300.0, abs=1e-6)


def test_detect_arrival_continuation_mode_accepts_zero_offset() -> None:
    mask = np.ones(100, dtype=bool)  # already voiced from the previous note

    arrival = detect_arrival(mask, FRAME_RATE_HZ, note_start_s=0.0, note_end_s=1.0, mode="continuation")

    assert arrival == pytest.approx(0.0, abs=1e-6)


def test_detect_arrival_no_voicing_returns_none() -> None:
    mask = np.zeros(100, dtype=bool)

    arrival = detect_arrival(mask, FRAME_RATE_HZ, note_start_s=0.0, note_end_s=1.0, mode="onset")

    assert arrival is None


# --- measure.py: core-window shifting --------------------------------------


def test_core_window_trims_both_sides_and_shifts_by_arrival() -> None:
    start, end = core_window(note_start_s=1.0, note_end_s=2.0, arrival_offset_s=0.1)

    assert start == pytest.approx(1.1 + 0.05)
    assert end == pytest.approx(2.0 - 0.05)


def test_core_window_collapses_to_midpoint_when_too_short_to_trim() -> None:
    start, end = core_window(note_start_s=1.0, note_end_s=1.08, arrival_offset_s=0.0)

    assert start == end
    assert 1.0 <= start <= 1.08


# --- loudness.py: median-anchored loudness ---------------------------------


def test_compute_rms_db_floors_true_silence() -> None:
    silence = np.zeros(4800, dtype=np.float32)  # 100ms of pure silence at 48kHz
    rms_db = compute_rms_db(silence, sample_rate=48000)

    assert np.all(rms_db == FLOOR_DB)


def test_median_db_ignores_floored_silent_frames() -> None:
    rms_db = np.array([FLOOR_DB, FLOOR_DB, -20.0, -18.0, -22.0])

    result = median_db(rms_db)

    assert result == pytest.approx(-20.0)


def test_median_db_returns_none_when_everything_is_silent() -> None:
    rms_db = np.full(10, FLOOR_DB)

    assert median_db(rms_db) is None


# --- score.py: score blending -----------------------------------------------


def test_blend_overall_score_matches_the_named_fallback_formula() -> None:
    result = blend_overall_score(pct_in_tune=0.8, arrival_consistency=0.5)

    assert result == pytest.approx(0.95 * 0.8 + 0.05 * 0.5)


def test_arrival_consistency_perfect_timing_is_one() -> None:
    assert arrival_consistency([0.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_arrival_consistency_empty_is_zero_not_undefined() -> None:
    assert arrival_consistency([]) == pytest.approx(0.0)


def test_alignment_sanity_check_flags_sang_but_never_in_tune() -> None:
    assert alignment_sanity_check(voiced_coverage=0.8, pct_in_tune=0.02) is True


def test_alignment_sanity_check_silent_take_is_not_flagged() -> None:
    # Low voiced_coverage means the user didn't really sing — a low
    # pct_in_tune there is expected, not a sign of bad alignment.
    assert alignment_sanity_check(voiced_coverage=0.05, pct_in_tune=0.0) is False


def test_alignment_sanity_check_honest_good_take_is_not_flagged() -> None:
    assert alignment_sanity_check(voiced_coverage=0.8, pct_in_tune=0.75) is False
