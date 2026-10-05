"""Syllable grouping, reconciliation, and the vocable fallback — Mon Oct
5 (L3 of IMPLEMENTATION_PLAN_2026-10-05.md). Pure, deterministic,
DB/model-free — unit-tested directly on synthetic input per the plan's
acceptance check 9: "deterministic layers only... No model in a unit
test." `elums/ingest/align.py`'s `WordSpan`/`CharSpan` are the only
inputs this module needs from the alignment stage.
"""

from __future__ import annotations

from dataclasses import dataclass

from elums.ingest.align import CharSpan, WordSpan

# §2's energy-gated fallback: any voiced span at least this long with no
# overlapping WordSpan gets a wordless syllable event.
VOCABLE_MIN_DURATION_S = 0.3


@dataclass(frozen=True)
class SyllableSpan:
    text: str
    start_s: float
    end_s: float
    char_spans: list[CharSpan]


@dataclass(frozen=True)
class ReconciledWord:
    text: str  # reference text where LRCLIB anchored this word, else the ASR text
    # None only transiently, for a gap word at the very start/end of the
    # song with no anchor on one side to interpolate from — reconcile_lyrics
    # filters these out of its own return value before returning.
    start_s: float | None
    end_s: float | None
    syllables: list[SyllableSpan]
    is_interpolated: bool  # True if start_s/end_s came from interpolation, not a real CTC span
    # The ASR WordSpan this reconciled word was anchored to (None when
    # interpolated) — kept so the caller can run group_syllables against
    # its real char spans rather than losing that detail at reconciliation.
    matched_span: WordSpan | None = None


@dataclass(frozen=True)
class VocableEvent:
    start_s: float
    end_s: float


def group_syllables(word: WordSpan, hyphenator) -> list[SyllableSpan]:  # noqa: ANN001 — pyphen.Pyphen
    """Split points from the hyphenation dictionary, boundaries from the
    CTC char spans — never an even time split (the specific UltraSinger
    failure the plan calls out). A word with no char spans (can only
    happen for interpolated/reconciled words with no real alignment)
    returns no syllables; callers must not call this for those."""
    if not word.char_spans:
        return []

    split_positions = set(hyphenator.positions(word.text))
    syllables: list[SyllableSpan] = []
    current: list[CharSpan] = []

    for i, char_span in enumerate(word.char_spans):
        current.append(char_span)
        # pyphen's positions are character counts from the start of the
        # word at which a hyphen may be inserted — i.e. after the
        # (position)th character, 1-indexed from the split's own
        # perspective ("hel-lo" -> position 3 means split after index 2,
        # 0-indexed) matches `i + 1 == position`.
        if (i + 1) in split_positions:
            syllables.append(
                SyllableSpan(
                    text="".join(c.char for c in current),
                    start_s=current[0].start_s,
                    end_s=current[-1].end_s,
                    char_spans=list(current),
                )
            )
            current = []

    if current:
        syllables.append(
            SyllableSpan(
                text="".join(c.char for c in current),
                start_s=current[0].start_s,
                end_s=current[-1].end_s,
                char_spans=list(current),
            )
        )

    return syllables


def _normalize_word(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalpha() or ch == "'")


def _lcs_matches(reference_words: list[str], asr_words: list[str]) -> list[tuple[int, int]]:
    """Longest common subsequence over normalized words — returns the
    list of (reference_index, asr_index) pairs on the matched run, in
    order. Standard DP table; reference/ASR transcripts are per-song
    line counts (tens to low hundreds of words), never large enough for
    O(n*m) to matter."""
    n, m = len(reference_words), len(asr_words)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if reference_words[i] == asr_words[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

    matches: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if reference_words[i] == asr_words[j]:
            matches.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return matches


def reconcile_lyrics(
    reference_lines: list[str], word_spans: list[WordSpan]
) -> list[ReconciledWord]:
    """Anchor-sequence reconciliation (§2 of the Oct 5 plan): LCS over
    normalized words anchors reference text onto ASR (CTC) timings;
    reference words that fall in an unmatched gap are interpolated
    linearly between the surrounding anchors (or dropped at the very
    start/end, where there is only one side to interpolate from — a
    word with no timing on either side has nothing to interpolate
    between). ASR words with no reference counterpart are not emitted at
    all: the reference line is what the final transcript should read,
    not a superset of both sources."""
    reference_words_raw = " ".join(reference_lines).split()
    reference_words_norm = [_normalize_word(w) for w in reference_words_raw]
    asr_words_norm = [_normalize_word(w.text) for w in word_spans]

    matches = _lcs_matches(reference_words_norm, asr_words_norm)
    match_by_ref_index = dict(matches)

    results: list[ReconciledWord] = []
    for ref_idx, raw_text in enumerate(reference_words_raw):
        if ref_idx in match_by_ref_index:
            asr_idx = match_by_ref_index[ref_idx]
            span = word_spans[asr_idx]
            results.append(
                ReconciledWord(
                    text=raw_text,
                    start_s=span.start_s,
                    end_s=span.end_s,
                    syllables=[],  # filled in by the caller via group_syllables
                    is_interpolated=False,
                    matched_span=span,
                )
            )
        else:
            results.append(
                ReconciledWord(text=raw_text, start_s=0.0, end_s=0.0, syllables=[], is_interpolated=True)
            )

    _interpolate_gaps(results)
    return [r for r in results if r.start_s is not None]


def _interpolate_gaps(results: list[ReconciledWord]) -> None:
    """Mutates interpolated words in place (dataclasses are frozen, so
    this rebuilds entries via index assignment on the list, not
    attribute mutation) — linear interpolation inside a run of
    unanchored words bounded by two anchored neighbors; runs at the
    start or end of the song (no anchor on one side) are left with
    start_s=end_s=0.0 and filtered out by the caller, since there is
    nothing to interpolate between."""
    i = 0
    n = len(results)
    while i < n:
        if not results[i].is_interpolated:
            i += 1
            continue
        gap_start = i
        while i < n and results[i].is_interpolated:
            i += 1
        gap_end = i  # exclusive

        prev_anchor = results[gap_start - 1] if gap_start > 0 else None
        next_anchor = results[gap_end] if gap_end < n else None

        if prev_anchor is None or next_anchor is None:
            for k in range(gap_start, gap_end):
                results[k] = ReconciledWord(
                    text=results[k].text, start_s=None, end_s=None, syllables=[], is_interpolated=True
                )
            continue

        span_start = prev_anchor.end_s
        span_end = next_anchor.start_s
        count = gap_end - gap_start
        step = (span_end - span_start) / (count + 1) if span_end > span_start else 0.0
        for k in range(gap_start, gap_end):
            offset = k - gap_start + 1
            start_s = span_start + step * (offset - 1) if step else span_start
            end_s = span_start + step * offset if step else span_start
            results[k] = ReconciledWord(
                text=results[k].text, start_s=start_s, end_s=end_s, syllables=[], is_interpolated=True
            )


def detect_vocable_events(
    vad_segments: list[tuple[float, float]], word_spans: list[WordSpan]
) -> list[VocableEvent]:
    """§2's energy-gated fallback: Whisper deletes over half of
    non-lexical vocables (the approach document's known failure mode).
    Any voiced span at least VOCABLE_MIN_DURATION_S long with no
    overlapping word gets a wordless event — Tuesday's note grid treats
    these as unconstrained syllable spans."""
    events: list[VocableEvent] = []
    for seg_start, seg_end in vad_segments:
        if seg_end - seg_start < VOCABLE_MIN_DURATION_S:
            continue
        overlaps = any(w.start_s < seg_end and w.end_s > seg_start for w in word_spans)
        if not overlaps:
            events.append(VocableEvent(start_s=seg_start, end_s=seg_end))
    return events
