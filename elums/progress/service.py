"""F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): the DB-aware half
of progress tracking. elums/progress/metrics.py stays import-free of
this module in the other direction -- no DB import there -- same split
elums/coaching/algebra.py vs elums/coaching/cards.py already draws for
F4 vs F7. Computed fresh on every request, same "recompute, don't
cache" precedent as F7's cards endpoint (PROGRESS.md Day 7 Session B
decision #3): no persisted Elo-rating column, so a metrics.py constant
change takes effect immediately with no backfill.

Scoped to one user's performances of one song, per the "personal best
on this song" framing in the architecture doc -- within-song
comparison eliminates difficulty confounding by construction. A
cross-song dashboard (aggregating a user's Elo skill trajectory across
every song they've sung) is a credible later addition, not built here
-- flagged in PROGRESS.md, not silently out of scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.models.performance import Performance, PerformanceStatus
from elums.progress import metrics


@dataclass(frozen=True)
class DimensionTrend:
    verdict: metrics.Verdict
    performances_needed: int
    rolling_median: float | None
    iqr_band: tuple[float, float] | None
    band_widen_factor: float


@dataclass(frozen=True)
class SongProgressSummary:
    performance_count: int
    normalization: str  # "elo" | "per_song_zscore"
    overall: DimensionTrend | None
    dimensions: dict[str, DimensionTrend]
    personal_best_score_overall: float | None
    device_label_consistent: bool


async def _load_user_song_performances(
    db: AsyncSession, user_id: uuid.UUID, song_id: uuid.UUID
) -> list[Performance]:
    result = await db.execute(
        select(Performance)
        .where(
            Performance.user_id == user_id,
            Performance.song_id == song_id,
            Performance.status == PerformanceStatus.SUCCEEDED,
        )
        # Secondary sort by `id` (UUIDv7, time-ordered by construction --
        # see elums/models/base.py's docstring) breaks ties when several
        # rows share the same `created_at`: Postgres's `now()` returns
        # the SAME value for every statement inside one transaction, so
        # a batch-seeded set of rows (elums/seed.py's demo performances)
        # would otherwise sort arbitrarily, scrambling the "chronological
        # order" every verdict/rolling-median computation here assumes.
        .order_by(Performance.created_at.asc(), Performance.id.asc())
    )
    return list(result.scalars().all())


async def _song_score_population(db: AsyncSession, song_id: uuid.UUID) -> list[float]:
    # Every scored performance of this song, across ALL users -- the
    # per-song z-score path needs the song's own full distribution,
    # not just this one user's takes of it.
    result = await db.execute(
        select(Performance.score_overall).where(
            Performance.song_id == song_id,
            Performance.status == PerformanceStatus.SUCCEEDED,
            Performance.score_overall.is_not(None),
        )
    )
    return [row[0] for row in result.all()]


def _dimension_trend(values: list[float], widen_factor: float = 1.0) -> DimensionTrend:
    verdict_result = metrics.three_way_verdict(values)
    return DimensionTrend(
        verdict=verdict_result.verdict,
        performances_needed=verdict_result.performances_needed,
        rolling_median=metrics.rolling_median(values),
        iqr_band=metrics.iqr_band(values),
        band_widen_factor=widen_factor,
    )


async def compute_song_progress(
    db: AsyncSession, user_id: uuid.UUID, song_id: uuid.UUID
) -> SongProgressSummary:
    # End to end: load this user's own takes of this song, normalize
    # for difficulty (Elo is the operating path; per-song z-score
    # overrides it only once THIS song clears
    # metrics.PER_SONG_ZSCORE_MIN_N across every user -- no song does
    # today), then rolling median/IQR/verdict over the normalized
    # sequence, plus per-dimension trends computed directly from the
    # already difficulty-neutral raw measurements (a given cents-off
    # or ms-off deviation means the same thing regardless of which
    # song produced it, so those skip Elo entirely).
    performances = await _load_user_song_performances(db, user_id, song_id)

    scores = [p.score_overall for p in performances if p.score_overall is not None]

    normalization = "elo"
    normalized_scores = metrics.replay_elo([(str(song_id), s) for s in scores]).skill_after
    if scores:
        population = await _song_score_population(db, song_id)
        z = metrics.per_song_zscore(scores, population)
        if z is not None:
            normalized_scores = z
            normalization = "per_song_zscore"

    device_labels = [p.device_label for p in performances]
    widen = metrics.device_label_band_widen(device_labels)

    overall_trend = _dimension_trend(normalized_scores, widen) if normalized_scores else None

    dimensions: dict[str, DimensionTrend] = {}
    pct_values = [p.pct_in_tune for p in performances if p.pct_in_tune is not None]
    if pct_values:
        dimensions["pct_in_tune"] = _dimension_trend(pct_values, widen)
    # Lower absolute cents/ms is better -- negated so "higher is
    # better" holds uniformly for every dimension three_way_verdict
    # compares, without teaching that function direction-awareness.
    cents_values = [-abs(p.median_cents) for p in performances if p.median_cents is not None]
    if cents_values:
        dimensions["pitch_accuracy"] = _dimension_trend(cents_values, widen)
    arrival_values = [
        -abs(p.arrival_offset_ms_median) for p in performances if p.arrival_offset_ms_median is not None
    ]
    if arrival_values:
        dimensions["timing_accuracy"] = _dimension_trend(arrival_values, widen)

    return SongProgressSummary(
        performance_count=len(performances),
        normalization=normalization,
        overall=overall_trend,
        dimensions=dimensions,
        personal_best_score_overall=metrics.personal_best(scores),
        device_label_consistent=widen == 1.0,
    )
