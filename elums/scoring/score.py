"""Overall score blend + alignment sanity check — Wed Oct 7 (W4 of
IMPLEMENTATION_PLAN_2026-10-07.md).

SecondPass §5.5's own fallback rule: no technique head exists yet, so its
weight redistributes into pitch. Do not invent a new blend. §4.1c:
sang-but-nothing-in-tune sets `alignment_warning` rather than a confident
bad score.
"""

from __future__ import annotations

PITCH_WEIGHT = 0.95
ARRIVAL_WEIGHT = 0.05

# §4.1c: real voiced singing (not silence/noise) that almost never lands
# in tune is much more likely a bad alignment than a bad singer.
ALIGNMENT_WARNING_VOICED_COVERAGE_MIN = 0.3
ALIGNMENT_WARNING_PCT_IN_TUNE_MAX = 0.15


def blend_overall_score(pct_in_tune: float, arrival_consistency: float) -> float:
    """§5.5's fallback blend, verbatim: 0.95 * pct_in_tune + 0.05 *
    arrival_consistency. Both inputs are expected in [0, 1]; the result
    is too."""
    return PITCH_WEIGHT * pct_in_tune + ARRIVAL_WEIGHT * arrival_consistency


def arrival_consistency(arrival_offsets_ms: list[float]) -> float:
    """A simple, auditable consistency score: 1.0 minus the (clamped)
    mean absolute arrival offset scaled against §6.2's own 50ms
    green/200ms red timing bands — not a new invented metric, just the
    plan's named thresholds turned into a [0, 1] score the blend above
    can consume. Empty input (no onset-mode notes detected at all) is
    treated as 0.0 consistency, not an undefined value silently dropped
    from the overall score."""
    if not arrival_offsets_ms:
        return 0.0
    mean_abs_ms = sum(abs(ms) for ms in arrival_offsets_ms) / len(arrival_offsets_ms)
    return max(0.0, 1.0 - min(mean_abs_ms, 200.0) / 200.0)


def alignment_sanity_check(voiced_coverage: float, pct_in_tune: float) -> bool:
    """§4.1c: real singing (voiced_coverage above the threshold) that
    almost never lands in tune — banner it rather than present a
    confident bad score the alignment, not the singer, likely earned."""
    return (
        voiced_coverage > ALIGNMENT_WARNING_VOICED_COVERAGE_MIN
        and pct_in_tune < ALIGNMENT_WARNING_PCT_IN_TUNE_MAX
    )
