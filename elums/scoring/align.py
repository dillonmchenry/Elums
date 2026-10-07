"""Offset search — Wed Oct 7 (W4 of IMPLEMENTATION_PLAN_2026-10-07.md).

SecondPass §4.1a: a voicing-mask grid search over ±1.5s in 20ms steps
against the chart's own expected-voiced mask, requiring >=1.0s of voiced
overlap at the winning candidate. Deliberately NOT audio cross-correlation
(GCC-PHAT is §7.4's duet-alignment tool, over raw signal; this is a
karaoke take against a *chart*, which has no raw reference signal to
correlate against, only voiced/unvoiced spans) — two boolean frame masks,
nothing else. DB-free, pure, numpy-only, same "tests on the logic" style
as elums/ingest/notes.py.

Sign convention: `offset_s` is how much LATE the user started relative to
the chart (positive = user's recording began after the chart's own
clock) — i.e. `user_voiced[t]` lines up with `chart_voiced[t - offset_s]`.
To realign the user's track onto the chart's timeline, subtract
`offset_s` from every user timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SEARCH_RANGE_S = 1.5
STEP_S = 0.02
MIN_OVERLAP_S = 1.0


@dataclass(frozen=True)
class OffsetResult:
    offset_s: float
    voiced_overlap_s: float
    sufficient: bool  # False if even the best candidate didn't reach MIN_OVERLAP_S


def _shifted_later(mask: np.ndarray, shift_frames: int, length: int) -> np.ndarray:
    """Returns `mask` delayed by `shift_frames` (may be negative, meaning
    advanced/earlier), zero-padded to `length`."""
    out = np.zeros(length, dtype=bool)
    if shift_frames >= 0:
        usable = min(mask.shape[0], length - shift_frames)
        if usable > 0:
            out[shift_frames : shift_frames + usable] = mask[:usable]
    else:
        src_start = -shift_frames
        usable = min(mask.shape[0] - src_start, length)
        if usable > 0:
            out[:usable] = mask[src_start : src_start + usable]
    return out


def find_offset(user_voiced: np.ndarray, chart_voiced: np.ndarray, frame_rate_hz: float) -> OffsetResult:
    """Grid-searches candidate `offset_s` values; for each, delays
    `chart_voiced` by that many frames (equivalent to advancing the user
    track to compensate for starting late) and scores the voiced-AND-voiced
    overlap against the (unshifted) user mask. The candidate with the
    highest overlap wins; if its overlap is still under `MIN_OVERLAP_S`,
    `sufficient=False` is returned so the caller's alignment sanity check
    can act on it rather than trusting a meaningless offset."""
    step_frames = max(1, round(STEP_S * frame_rate_hz))
    max_shift_frames = round(SEARCH_RANGE_S * frame_rate_hz)
    length = max(user_voiced.shape[0], chart_voiced.shape[0])
    user_padded = _shifted_later(user_voiced, 0, length)

    best_overlap_s = -1.0
    best_offset_s = 0.0
    for shift_frames in range(-max_shift_frames, max_shift_frames + 1, step_frames):
        # offset_s = shift_frames / frame_rate_hz means the user started
        # that many seconds late -> chart_voiced delayed by shift_frames
        # lines back up with the user's own (unshifted) timeline.
        chart_shifted = _shifted_later(chart_voiced, shift_frames, length)
        overlap_s = float(np.count_nonzero(user_padded & chart_shifted)) / frame_rate_hz
        if overlap_s > best_overlap_s:
            best_overlap_s = overlap_s
            best_offset_s = shift_frames / frame_rate_hz

    return OffsetResult(
        offset_s=best_offset_s,
        voiced_overlap_s=best_overlap_s,
        sufficient=best_overlap_s >= MIN_OVERLAP_S,
    )
