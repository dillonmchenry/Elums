from __future__ import annotations

from pydantic import BaseModel


class DimensionTrendSchema(BaseModel):
    verdict: str  # "improving" | "holding_steady" | "declining" | "insufficient_data"
    performances_needed: int
    rolling_median: float | None
    iqr_low: float | None
    iqr_high: float | None
    band_widen_factor: float


class SongProgressSchema(BaseModel):
    performance_count: int
    normalization: str  # "elo" | "per_song_zscore"
    overall: DimensionTrendSchema | None
    dimensions: dict[str, DimensionTrendSchema]
    personal_best_score_overall: float | None
    device_label_consistent: bool
