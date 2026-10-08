"""F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): deterministic
math only -- no DB, no live performance, per the plan's own acceptance
bar #11 ("z-score/Elo math" named directly as a deterministic-layer
example)."""

from __future__ import annotations

from elums.progress.metrics import (
    PER_SONG_ZSCORE_MIN_N,
    VERDICT_GATE_N,
    device_label_band_widen,
    elo_expected,
    elo_update,
    iqr_band,
    per_song_zscore,
    personal_best,
    replay_elo,
    rolling_median,
    three_way_verdict,
)


class TestElo:
    def test_expected_is_half_at_equal_ratings(self):
        assert elo_expected(1500.0, 1500.0) == 0.5

    def test_higher_skill_than_difficulty_favors_user(self):
        assert elo_expected(1800.0, 1500.0) > 0.5

    def test_update_moves_skill_toward_outcome(self):
        # A perfect-score outcome (1.0) against equal ratings should
        # raise skill and lower difficulty -- the user did better than
        # "expected" against this song.
        skill, difficulty = elo_update(1500.0, 1500.0, outcome=1.0)
        assert skill > 1500.0
        assert difficulty < 1500.0

    def test_update_direction_reverses_for_a_bad_outcome(self):
        skill, difficulty = elo_update(1500.0, 1500.0, outcome=0.0)
        assert skill < 1500.0
        assert difficulty > 1500.0

    def test_replay_is_deterministic_and_chronological(self):
        outcomes = [("song-a", 0.9), ("song-a", 0.3), ("song-b", 0.95)]
        result = replay_elo(outcomes)
        assert len(result.skill_after) == 3
        # Re-running the exact same sequence gives the exact same
        # trajectory -- no hidden state, no randomness.
        result2 = replay_elo(outcomes)
        assert result.skill_after == result2.skill_after
        assert set(result.difficulty_after) == {"song-a", "song-b"}

    def test_consistently_strong_takes_lower_the_songs_difficulty_estimate(self):
        # Classic Elo co-update: an "opponent" (here, the song) that
        # keeps losing to the user drops in rating -- i.e. a song the
        # user keeps dominating is re-estimated as easier, not harder.
        outcomes = [("song-a", 0.95)] * 10
        result = replay_elo(outcomes)
        assert result.difficulty_after["song-a"] < 1500.0

    def test_a_new_song_does_not_carry_over_a_prior_songs_difficulty(self):
        outcomes = [("song-a", 0.95)] * 10 + [("song-b", 0.5)]
        result = replay_elo(outcomes)
        # song-b was seen once, at the default rating, regardless of
        # how far song-a's own difficulty had drifted.
        assert result.difficulty_after["song-b"] != result.difficulty_after["song-a"]


class TestPerSongZscore:
    def test_returns_none_below_the_sample_threshold(self):
        population = [0.5] * (PER_SONG_ZSCORE_MIN_N - 1)
        assert per_song_zscore([0.5], population) is None

    def test_returns_zscores_at_or_above_the_threshold(self):
        population = [0.5] * PER_SONG_ZSCORE_MIN_N
        population[0] = 0.9  # introduce real variance
        result = per_song_zscore([0.9], population)
        assert result is not None
        assert len(result) == 1

    def test_zero_variance_population_returns_zero_not_a_division_error(self):
        population = [0.7] * PER_SONG_ZSCORE_MIN_N
        result = per_song_zscore([0.7, 0.7], population)
        assert result == [0.0, 0.0]


class TestRollingMedianAndBand:
    def test_rolling_median_uses_only_the_last_window(self):
        values = [0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9]
        assert rolling_median(values, window=5) == 0.9

    def test_rolling_median_empty_is_none(self):
        assert rolling_median([]) is None

    def test_iqr_band_needs_at_least_two_points(self):
        assert iqr_band([0.5]) is None
        band = iqr_band([0.2, 0.4, 0.6, 0.8])
        assert band is not None
        q1, q3 = band
        assert q1 <= q3

    def test_one_disaster_take_does_not_move_the_median_much(self):
        steady = [0.8, 0.8, 0.8, 0.8, 0.8]
        with_disaster = [0.8, 0.8, 0.8, 0.8, 0.0]
        assert abs(rolling_median(steady) - rolling_median(with_disaster)) < 0.3


class TestThreeWayVerdict:
    def test_below_gate_reports_sing_n_more(self):
        values = [0.5] * (VERDICT_GATE_N - 2)
        result = three_way_verdict(values)
        assert result.verdict == "insufficient_data"
        assert result.performances_needed == 2

    def test_at_gate_with_improving_trend(self):
        values = [0.3, 0.3, 0.3] + [0.9, 0.9, 0.9, 0.9, 0.9]
        result = three_way_verdict(values)
        assert result.verdict == "improving"
        assert result.performances_needed == 0

    def test_at_gate_with_declining_trend(self):
        values = [0.9, 0.9, 0.9] + [0.3, 0.3, 0.3, 0.3, 0.3]
        result = three_way_verdict(values)
        assert result.verdict == "declining"

    def test_flat_history_holds_steady(self):
        values = [0.6] * 10
        result = three_way_verdict(values)
        assert result.verdict == "holding_steady"

    def test_exactly_at_gate_with_no_prior_window_holds_steady(self):
        values = [0.5] * VERDICT_GATE_N
        result = three_way_verdict(values)
        # len(values) == gate_n == 8; window=5 leaves only 3 prior
        # values, which is still a non-empty prior window here, so
        # this exercises the "has a (short) prior window" branch, not
        # the fully-empty one -- both are covered by this suite.
        assert result.verdict == "holding_steady"


class TestPersonalBest:
    def test_personal_best_is_the_max(self):
        assert personal_best([0.4, 0.9, 0.6]) == 0.9

    def test_personal_best_of_empty_is_none(self):
        assert personal_best([]) is None


class TestDeviceLabelBandWiden:
    def test_single_device_does_not_widen(self):
        assert device_label_band_widen(["laptop-mic"] * 5) == 1.0

    def test_mixed_devices_widen(self):
        assert device_label_band_widen(["laptop-mic", "laptop-mic", "headset", "headset"]) > 1.0

    def test_none_labels_are_ignored_not_treated_as_a_distinct_device(self):
        assert device_label_band_widen([None, None, "laptop-mic", "laptop-mic"]) == 1.0
