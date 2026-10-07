"""`CoachingConfig` -- F4/F5 (Session B, IMPLEMENTATION_PLAN_2026-10-09.md).

Per §3's settled decision: "Thresholds are config-as-data -- new
config/coaching.yaml behind a CoachingConfig. elums/config.py stays
infrastructure-only." This module is the one place every detector
algebra threshold and selection cap lives, loaded once from
config/coaching.yaml (repo-root relative, same discipline as
config/models.yaml elsewhere in the project).

Deliberately NOT a pydantic-settings `BaseSettings` (those read from
the environment/.env, which is elums/config.py's job) -- plain
pydantic `BaseModel.model_validate` over parsed YAML, since these are
product thresholds, not infrastructure.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

COACHING_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "coaching.yaml"


class CoachingConfig(BaseModel):
    pitch_flat_cents_threshold: float
    pitch_sharp_cents_threshold: float
    pitch_drift_cents_per_s_threshold: float

    timing_early_ms_threshold: float
    timing_late_ms_threshold: float
    timing_late_weight: float

    vibrato_band_min_hz: float
    vibrato_band_max_hz: float
    vibrato_technique_gate_threshold: float

    loud_relative_db_threshold: float
    quiet_relative_db_threshold: float
    rms_delta_loud_db_threshold: float
    rms_delta_quiet_db_threshold: float

    registration_strain_high_note_percentile: float

    technique_label_present_threshold: float

    formant_instability_std_hz_threshold: float
    formant_delta_worse_hz_threshold: float

    breath_decay_mismatch_db_per_s_threshold: float

    comparative_confidence_boost: float
    min_confidence_to_surface: float
    max_cards_per_type: int
    max_cards_per_category: int
    max_cards_total: int
    guaranteed_affirming_cards: int


@lru_cache(maxsize=1)
def load_coaching_config(path: Path | None = None) -> CoachingConfig:
    target = path or COACHING_CONFIG_PATH
    with target.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return CoachingConfig.model_validate(raw)
