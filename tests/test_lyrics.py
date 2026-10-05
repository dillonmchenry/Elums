"""Mon Oct 5 (L3's acceptance check 9): deterministic-layer unit tests
for elums/ingest/syllables.py — syllable grouping, LCS reconciliation,
energy-gap vocable detection. No model, no torch, no librosa; runs on
the host `dev` environment same as elums/ingest/vad.py's math-only tests
would if that module didn't also import librosa at module scope.
"""

from __future__ import annotations

import pyphen
import pytest

from elums.ingest.align import CharSpan, WordSpan
from elums.ingest.syllables import (
    VOCABLE_MIN_DURATION_S,
    detect_vocable_events,
    group_syllables,
    reconcile_lyrics,
)

_HYPHENATOR = pyphen.Pyphen(lang="en_US")


def _word(text: str, start_s: float, char_dur: float = 0.1) -> WordSpan:
    """Builds a WordSpan with evenly-spaced (but distinct, non-degenerate)
    char spans — good enough for exercising grouping logic without a real
    CTC run."""
    char_spans = []
    t = start_s
    for ch in text:
        char_spans.append(CharSpan(char=ch, start_s=t, end_s=t + char_dur, score=0.0))
        t += char_dur
    return WordSpan(text=text, start_s=char_spans[0].start_s, end_s=char_spans[-1].end_s, char_spans=char_spans, score=0.0)


# --- group_syllables --------------------------------------------------


def test_group_syllables_splits_on_hyphenation_points_not_evenly() -> None:
    word = _word("HELLO", start_s=0.0)
    syllables = group_syllables(word, _HYPHENATOR)

    assert [s.text for s in syllables] == ["HEL", "LO"]
    # Boundaries come from the char spans' own timing, not an even split —
    # "HEL" is 3 chars (0.3s), "LO" is 2 chars (0.2s): unequal durations.
    assert syllables[0].end_s == pytest.approx(0.3)
    assert syllables[1].end_s - syllables[1].start_s == pytest.approx(0.2)


def test_group_syllables_single_syllable_word_returns_one_span() -> None:
    word = _word("WORLD", start_s=0.0)
    syllables = group_syllables(word, _HYPHENATOR)

    assert len(syllables) == 1
    assert syllables[0].text == "WORLD"


def test_group_syllables_on_word_with_no_char_spans_returns_empty() -> None:
    word = WordSpan(text="LA", start_s=0.0, end_s=0.0, char_spans=[], score=0.0)
    assert group_syllables(word, _HYPHENATOR) == []


# --- reconcile_lyrics ---------------------------------------------------


def test_reconcile_lyrics_anchors_matching_words_to_asr_timing() -> None:
    word_spans = [_word("HELLO", 0.0), _word("WORLD", 1.0)]
    results = reconcile_lyrics(["Hello world"], word_spans)

    assert [r.text for r in results] == ["Hello", "world"]
    assert all(not r.is_interpolated for r in results)
    assert results[0].start_s == pytest.approx(word_spans[0].start_s)
    assert results[1].start_s == pytest.approx(word_spans[1].start_s)


def test_reconcile_lyrics_interpolates_an_unanchored_gap_between_two_anchors() -> None:
    # ASR missed the middle word ("my") entirely — ref has 3 words, ASR
    # only transcribed 2 ("hello"/"friend").
    word_spans = [_word("HELLO", 0.0), _word("FRIEND", 10.0)]
    results = reconcile_lyrics(["Hello my friend"], word_spans)

    assert [r.text for r in results] == ["Hello", "my", "friend"]
    assert results[1].is_interpolated
    # Interpolated inside the gap between the two anchors — a single gap
    # word occupies the whole gap, so its bounds meet (not cross) the
    # anchors' own end/start.
    assert word_spans[0].end_s <= results[1].start_s < results[1].end_s <= word_spans[1].start_s


def test_reconcile_lyrics_drops_unanchored_words_at_the_very_start() -> None:
    # Nothing precedes the first anchor to interpolate from.
    word_spans = [_word("WORLD", 5.0)]
    results = reconcile_lyrics(["Hello world"], word_spans)

    assert [r.text for r in results] == ["world"]


def test_reconcile_lyrics_keeps_reference_text_when_asr_disagrees() -> None:
    # ASR mis-transcribed "there" as "their" — LCS shouldn't match it, so
    # reconcile should NOT silently substitute the wrong ASR word in.
    word_spans = [_word("HELLO", 0.0), _word("THEIR", 1.0)]
    results = reconcile_lyrics(["Hello there"], word_spans)

    assert results[0].text == "Hello"
    # "there" has no ASR match ("THEIR" != "THERE") and no anchor after it
    # to interpolate toward, so it's dropped — not corrupted with the
    # wrong ASR word's text.
    assert [r.text for r in results] == ["Hello"]


# --- detect_vocable_events ----------------------------------------------


def test_detect_vocable_events_flags_voiced_span_with_no_overlapping_word() -> None:
    vad_segments = [(0.0, 1.0), (2.0, 2.5)]  # second segment is a 500ms "na na na" with no words
    word_spans = [_word("HELLO", 0.0)]

    events = detect_vocable_events(vad_segments, word_spans)

    assert len(events) == 1
    assert events[0].start_s == 2.0
    assert events[0].end_s == 2.5


def test_detect_vocable_events_ignores_spans_shorter_than_the_minimum() -> None:
    short_span = VOCABLE_MIN_DURATION_S - 0.05
    vad_segments = [(0.0, short_span)]
    assert detect_vocable_events(vad_segments, []) == []


def test_detect_vocable_events_count_is_plausible_not_hundreds() -> None:
    # Acceptance check: "vocable count plausible (a handful, not hundreds)".
    vad_segments = [(float(i * 2), float(i * 2 + 0.5)) for i in range(5)]
    word_spans = [_word("HELLO", 0.0)]  # only overlaps the first segment

    events = detect_vocable_events(vad_segments, word_spans)

    assert 0 < len(events) < 100
    assert len(events) == 4
