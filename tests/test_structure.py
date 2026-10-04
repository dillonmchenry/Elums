"""N4's "tests on the logic, not the models" unit tests (SecondPass's own
principle, carried over from Day 1) for elums/ingest/key.py and
elums/ingest/vad.py — the two N2 deliverables with real, deterministic
math behind them (Krumhansl-Schmuckler correlation; RMS-threshold run
detection and the MAX_SEGMENT_S cap), as opposed to elums/ingest/structure.py
(all-in-one-infer's harmonix-all ensemble), which has no such logic to
unit-test in isolation — that one is only exercised end-to-end, by
tests/test_separation.py's `gpu`-marked live-stack test.

Marked `gpu` for the same reason as tests/test_separation.py: both
elums.ingest.key and elums.ingest.vad `import librosa` at module scope,
and librosa lives only in the "gpu" dependency group (pyproject.toml),
never in "dev" — the host pytest environment does not have it. Run via
`docker compose exec gpu-worker python -m pytest tests/test_structure.py`,
or `pytest -m gpu` on the VM once that distinction matters.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gpu

# Both only live in the "gpu" dependency group (pyproject.toml) — never
# "dev" — so a bare `import numpy` at module scope would break collection
# entirely on the host pytest environment, not just skip these tests.
np = pytest.importorskip("numpy")
librosa = pytest.importorskip("librosa")

from elums.ingest.key import _correlate_all_candidates  # noqa: E402
from elums.ingest.vad import (  # noqa: E402
    MAX_SEGMENT_S,
    MIN_SILENCE_S,
    _split_long_segment,
)


# --- elums/ingest/key.py --------------------------------------------------


def test_correlate_all_candidates_returns_all_24_sorted_best_first() -> None:
    chroma = np.zeros(12)
    chroma[0] = 1.0  # a pure C
    candidates = _correlate_all_candidates(chroma)

    assert len(candidates) == 24
    tonics = {(t, m) for t, m, _ in candidates}
    assert len(tonics) == 24  # 12 tonics x 2 modes, no duplicates

    scores = [score for _, _, score in candidates]
    assert scores == sorted(scores, reverse=True)


def test_correlate_all_candidates_prefers_c_major_profile_shape_on_c_rooted_chroma() -> None:
    # The KS major profile's own shape, rooted at C — feeding it back in
    # verbatim should make ("C", "major") win outright, not just place
    # well; this is the sanity check that the correlation math (centering,
    # Pearson normalization, the 12-way np.roll per mode) is wired
    # correctly, independent of any audio or model.
    from elums.ingest.key import _MAJOR_PROFILE

    candidates = _correlate_all_candidates(np.asarray(_MAJOR_PROFILE))
    best_tonic, best_mode, best_corr = candidates[0]

    assert (best_tonic, best_mode) == ("C", "major")
    assert best_corr == pytest.approx(1.0, abs=1e-9)


def test_correlate_all_candidates_rotation_tracks_the_rotated_tonic() -> None:
    # Rotating the profile by N semitones should make tonic N the winner —
    # exercises np.roll's direction/offset convention actually matches
    # _PITCH_CLASSES' indexing, not just that *some* candidate wins.
    from elums.ingest.key import _MAJOR_PROFILE, _PITCH_CLASSES

    for rotation in (1, 5, 11):
        rotated_profile = np.roll(np.asarray(_MAJOR_PROFILE), rotation)
        candidates = _correlate_all_candidates(rotated_profile)
        best_tonic, best_mode, _ = candidates[0]
        assert (best_tonic, best_mode) == (_PITCH_CLASSES[rotation], "major")


# --- elums/ingest/vad.py ---------------------------------------------------


def test_split_long_segment_leaves_short_segments_untouched() -> None:
    segments = _split_long_segment(0.0, MAX_SEGMENT_S - 1.0)
    assert len(segments) == 1
    assert segments[0].start_s == 0.0
    assert segments[0].end_s == pytest.approx(MAX_SEGMENT_S - 1.0)


def test_split_long_segment_caps_at_max_segment_s() -> None:
    # A 95s run with a 30s cap must become 4 equal ~23.75s chunks, not 3
    # chunks of 30s + one short leftover — _split_long_segment's own
    # docstring says "equal-ish chunks", not "greedy 30s slices".
    total_duration = 95.0
    segments = _split_long_segment(10.0, 10.0 + total_duration)

    assert len(segments) == 4
    for seg in segments:
        assert seg.end_s - seg.start_s <= MAX_SEGMENT_S
        assert seg.end_s - seg.start_s == pytest.approx(total_duration / 4)

    # Contiguous and gap-free, start to end.
    assert segments[0].start_s == pytest.approx(10.0)
    assert segments[-1].end_s == pytest.approx(10.0 + total_duration)
    for prev, nxt in zip(segments, segments[1:]):
        assert prev.end_s == pytest.approx(nxt.start_s)


def test_split_long_segment_exactly_at_the_cap_is_not_split() -> None:
    segments = _split_long_segment(0.0, MAX_SEGMENT_S)
    assert len(segments) == 1


def test_segment_vocal_activity_merges_runs_closer_than_min_silence(tmp_path) -> None:
    # Build a synthetic "vocal stem" with two loud bursts separated by a
    # gap shorter than MIN_SILENCE_S — segment_vocal_activity's merge step
    # (elums/ingest/vad.py) must stitch them into one segment, not two.
    import soundfile as sf

    from elums.ingest.vad import segment_vocal_activity

    sr = 22050
    gap_s = MIN_SILENCE_S * 0.5
    burst_s = 2.0
    total_s = burst_s + gap_s + burst_s
    t = np.linspace(0, total_s, int(total_s * sr), endpoint=False)

    tone = 0.8 * np.sin(2 * np.pi * 220.0 * t)
    burst1_end = int(burst_s * sr)
    gap_end = int((burst_s + gap_s) * sr)
    tone[burst1_end:gap_end] = 0.0  # silence in the gap only

    wav_path = tmp_path / "synthetic_vocals.wav"
    sf.write(str(wav_path), tone.astype(np.float32), sr)

    segments = segment_vocal_activity(str(wav_path))

    assert len(segments) == 1
    assert segments[0].start_s == pytest.approx(0.0, abs=0.2)
    assert segments[0].end_s == pytest.approx(total_s, abs=0.2)


def test_segment_vocal_activity_on_silence_returns_no_segments(tmp_path) -> None:
    import soundfile as sf

    from elums.ingest.vad import segment_vocal_activity

    sr = 22050
    silence = np.zeros(sr * 2, dtype=np.float32)
    wav_path = tmp_path / "silence.wav"
    sf.write(str(wav_path), silence, sr)

    assert segment_vocal_activity(str(wav_path)) == []
