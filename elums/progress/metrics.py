"""F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): pure
progress-tracking math per ELUMS_TECHNICAL_APPROACH.md §6.5. No DB, no
`Performance` import -- same "deterministic layers only" discipline
`elums/coaching/dimensions/*` already established, so this is
unit-testable without ever touching a database (the plan's own
acceptance bar #11 names "z-score/Elo math" directly as an example).

Difficulty normalization, in priority order per §6.5:

1. **Per-song z-score**, once a song has >= `PER_SONG_ZSCORE_MIN_N`
   scored performances across all users -- genuinely
   difficulty-controlled, but needs a sample size this project's own
   seed data never reaches today (§6's own admission: "the 20+
   performances per song z-scoring wants do not exist and will not
   today").
2. **Elo-style online song-difficulty / user-skill co-update** as the
   shrinkage fallback below that threshold -- precedent PMC8336693's
   "inferring game difficulty curves from player-vs-level outcomes."
   This is the *operating* path for every song in this project's own
   data, not merely the fallback (§6's own instruction: "say so
   explicitly in the UI copy").

Then, over whichever normalized sequence results: a rolling median of
the last 5 (not the mean -- robust to one disaster take), a displayed
IQR uncertainty band, and a three-way verdict gated at >= 8
performances.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Literal

ELO_K_FACTOR = 16.0
ELO_INITIAL_RATING = 1500.0
PER_SONG_ZSCORE_MIN_N = 20
ROLLING_MEDIAN_WINDOW = 5
VERDICT_GATE_N = 8


def elo_expected(skill: float, difficulty: float) -> float:
    """Standard Elo expected-outcome function, logistic in the
    skill-minus-difficulty gap (400-point scale, chess's own
    convention -- arbitrary, but well-understood, and nothing here
    depends on the exact constant)."""
    return 1.0 / (1.0 + 10.0 ** ((difficulty - skill) / 400.0))


def elo_update(skill: float, difficulty: float, outcome: float, k: float = ELO_K_FACTOR) -> tuple[float, float]:
    """One online update step. `outcome` is `score_overall` (continuous,
    [0, 1]) treated as a soft win/loss degree, not a binary coin flip
    -- Elo's math tolerates a continuous outcome in [0, 1] directly
    (it is exactly the same range `expected` already produces).
    Skill moves toward matching its own song's difficulty; difficulty
    moves the opposite direction by construction -- the co-update
    that lets a song's difficulty estimate improve as more people
    sing it, with no separate difficulty-fitting pass."""
    expected = elo_expected(skill, difficulty)
    delta = k * (outcome - expected)
    return skill + delta, difficulty - delta


@dataclass(frozen=True)
class EloReplayResult:
    skill_after: list[float]  # one value per performance, same order as input
    difficulty_after: dict[str, float]  # final per-song difficulty, by song_id


def replay_elo(outcomes: list[tuple[str, float]]) -> EloReplayResult:
    """Replays one user's performances in chronological order,
    starting every unseen song (and the user's own skill) at
    `ELO_INITIAL_RATING`. Recomputed fresh from full history on every
    call -- same "recompute, don't cache" precedent as F7's cards
    endpoint (PROGRESS.md Day 7 Session B §9.3) -- so there is no
    persisted rating column, no backfill job if `ELO_K_FACTOR` ever
    changes, and no stale-rating-vs-stale-checkpoint hazard to track
    (the exact class of bug Session A's §11 flags for the technique
    checkpoint)."""
    skill = ELO_INITIAL_RATING
    difficulty: dict[str, float] = {}
    skill_after: list[float] = []
    for song_id, outcome in outcomes:
        d = difficulty.get(song_id, ELO_INITIAL_RATING)
        skill, d = elo_update(skill, d, outcome)
        difficulty[song_id] = d
        skill_after.append(skill)
    return EloReplayResult(skill_after=skill_after, difficulty_after=difficulty)


def per_song_zscore(scores: list[float], song_population: list[float]) -> list[float] | None:
    """§6.5's first-priority path: once a song has
    `PER_SONG_ZSCORE_MIN_N` or more scored performances (across every
    user, not just one), a z-score against that song's own
    distribution is a genuinely difficulty-controlled measure --
    stronger than Elo's online approximation, but it needs a sample
    size this project's seed data doesn't reach (§6's own admission).
    Returns `None` (not a column of zeros) below the threshold, so a
    caller never silently treats an unmet precondition as "zero
    deviation." `scores` is the subsequence to score; `song_population`
    is the full population to compute mean/std from -- kept separate
    so this works whether `scores` is one user's own takes of the
    song or the full population itself."""
    n = len(song_population)
    if n < PER_SONG_ZSCORE_MIN_N:
        return None
    mean = sum(song_population) / n
    variance = sum((s - mean) ** 2 for s in song_population) / n
    std = variance**0.5
    if std == 0:
        return [0.0 for _ in scores]
    return [(s - mean) / std for s in scores]


def rolling_median(values: list[float], window: int = ROLLING_MEDIAN_WINDOW) -> float | None:
    """Median of the last `window` values -- robust to one disaster
    take, per §6.5's own reasoning for median over mean."""
    if not values:
        return None
    return median(values[-window:])


def iqr_band(values: list[float], window: int = ROLLING_MEDIAN_WINDOW) -> tuple[float, float] | None:
    """(Q1, Q3) of the last `window` values -- the displayed
    uncertainty band §6.5 asks for instead of a bare point estimate.
    Needs at least 2 points to mean anything; `None` below that."""
    recent = values[-window:]
    if len(recent) < 2:
        return None
    ordered = sorted(recent)
    n = len(ordered)
    q1 = ordered[max(0, (n - 1) // 4)]
    q3 = ordered[min(n - 1, (3 * (n - 1)) // 4)]
    return (q1, q3)


Verdict = Literal["improving", "holding_steady", "declining", "insufficient_data"]


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    performances_needed: int  # 0 once the gate is cleared


def three_way_verdict(values: list[float], gate_n: int = VERDICT_GATE_N, flat_epsilon: float = 1e-9) -> VerdictResult:
    """§6.5's gated verdict: below `gate_n` performances, say "sing N
    more" rather than guessing ("the gate is a feature... it builds
    trust"). At or above it, compares the median of the most recent
    `ROLLING_MEDIAN_WINDOW` values against the median of the window
    immediately before it; a flat/no-prior-window case degrades to
    "holding_steady" rather than erroring."""
    if len(values) < gate_n:
        return VerdictResult(verdict="insufficient_data", performances_needed=gate_n - len(values))

    recent = values[-ROLLING_MEDIAN_WINDOW:]
    prior = values[: len(values) - len(recent)][-ROLLING_MEDIAN_WINDOW:]
    if not prior:
        return VerdictResult(verdict="holding_steady", performances_needed=0)
    diff = median(recent) - median(prior)
    if diff > flat_epsilon:
        return VerdictResult(verdict="improving", performances_needed=0)
    if diff < -flat_epsilon:
        return VerdictResult(verdict="declining", performances_needed=0)
    return VerdictResult(verdict="holding_steady", performances_needed=0)


def personal_best(scores: list[float]) -> float | None:
    """§6.5's hero metric: within-song comparison eliminates
    difficulty confounding by construction and needs zero statistics."""
    return max(scores) if scores else None


def device_label_band_widen(device_labels: list[str | None], widen_factor: float = 1.5) -> float:
    """§6.3/§6.5: widen the displayed uncertainty band when a user's
    recent sessions span more than one `device_label` -- a mic/room
    change is a real source of extra variance the band should
    reflect, not attribute to the user's own singing. Returns a plain
    multiplier (1.0 = no widening) for the caller to apply to
    `iqr_band`'s own (q1, q3); `None` labels are ignored (unlabeled
    sessions aren't evidence of a device change)."""
    recent = [d for d in device_labels[-ROLLING_MEDIAN_WINDOW:] if d is not None]
    if len(set(recent)) > 1:
        return widen_factor
    return 1.0
