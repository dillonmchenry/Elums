"""F4 -- composable detector algebra (Session B, IMPLEMENTATION_PLAN_2026-10-09.md).

Per ELUMS_TECHNICAL_APPROACH.md §6.4(b): a small algebra --
{dimension} x {direction} x {scope} x {absolute | reference-relative}
x {co-occurrence} -- searched per performance rather than a fixed list
of ~60 hand-written detectors. Every claim keeps the measurements that
fired it in `detail`, so a claim is always a checkable statement about
numbers, never an assertion.

Reads ONLY fields from Session A's frozen payload (PROGRESS.md Day 7
§7/§11) -- never re-derives a measurement, never reaches into an f0
blob. This module has no GPU/torch/librosa import, same "deterministic
layers only" discipline as elums/coaching/dimensions/*.

**The registry is a cross-session contract** (§6.6): claim `type` names
here are read by F5's selection, Session C's card UI, and Saturday's
challenge generation. Renaming one after this session commits silently
breaks all three -- see the registry's own docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from elums.coaching.config import CoachingConfig

# Mirrors elums/technique/model.py's `TECHNIQUE_LABELS` exactly.
# **Not imported directly**: that module imports torch at module scope
# (needed for `TechniqueHead`), and this module must stay torch-free
# -- same "deterministic layers only" discipline as
# elums/coaching/dimensions/*, which never import a GPU-only module
# either. Known duplication, same pattern model.py's own docstring
# already documents for its training-script twin; keep these six
# names in sync with model.py's tuple if that ever changes.
TECHNIQUE_LABELS: tuple[str, ...] = (
    "mix_tech",
    "falsetto_tech",
    "breathy_tech",
    "pharyngeal_tech",
    "vibrato_tech",
    "glissando_tech",
)

# VocalCoachBench's 7 categories, adopted wholesale per §6.4 -- both the
# display grouping and the coverage checklist.
CATEGORIES = ("PITCH", "RHYTHM", "DICTION", "BREATH", "VOCALIZATION", "TECHNIQUE", "EXPRESSION")


@dataclass(frozen=True)
class Claim:
    """One verified, checkable observation. `evidence` is the raw
    [0, 1] strength of the underlying predicate -- F5 turns this into a
    display confidence (coverage-weighted, comparative-boosted,
    inverted for absence claims). `detail` carries every number the
    predicate read, so "a claim's detail numbers reproduce its own
    predicate" (the plan's own validation bar) is always true by
    construction: nothing here is derived after the fact.
    """

    type: str
    category: str
    scope: str  # "note" | "section" | "overall"
    basis: str  # "absolute" | "reference"
    direction: str  # "issue" | "affirming" | "neutral"
    start_s: float
    end_s: float
    evidence: float
    detail: dict
    note_index: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    category: str
    basis: str
    direction: str
    scope: str
    fn: Callable[..., Claim | None]


# name -> DetectorSpec. **Cross-session contract -- do not rename after
# commit** (§6.6: Saturday's challenge generation validates detector
# names against this exact registry and drops unknowns).
REGISTRY: dict[str, DetectorSpec] = {}


def register(name: str, category: str, basis: str, direction: str, scope: str):
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r} for detector {name!r}")

    def deco(fn: Callable[..., Claim | None]) -> Callable[..., Claim | None]:
        REGISTRY[name] = DetectorSpec(name=name, category=category, basis=basis, direction=direction, scope=scope, fn=fn)
        return fn

    return deco


def registry_names() -> frozenset[str]:
    """What §6.6 validates LLM-proposed/generated detector names against."""
    return frozenset(REGISTRY.keys())


def _note_window(note: dict) -> tuple[float, float]:
    return float(note.get("core_start_s", 0.0)), float(note.get("core_end_s", 0.0))


# ---------------------------------------------------------------------------
# Dimension x direction, note scope, absolute basis
# ---------------------------------------------------------------------------


@register("pitch_flat", "PITCH", "absolute", "issue", "note")
def _pitch_flat(note: dict, cfg: CoachingConfig) -> Claim | None:
    cents = note.get("median_cents")
    if cents is None or cents > -cfg.pitch_flat_cents_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(cents) / (2.0 * cfg.pitch_flat_cents_threshold))
    return Claim(
        type="pitch_flat",
        category="PITCH",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"median_cents": cents, "threshold_cents": -cfg.pitch_flat_cents_threshold},
        note_index=note["note_index"],
    )


@register("pitch_sharp", "PITCH", "absolute", "issue", "note")
def _pitch_sharp(note: dict, cfg: CoachingConfig) -> Claim | None:
    cents = note.get("median_cents")
    if cents is None or cents < cfg.pitch_sharp_cents_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, cents / (2.0 * cfg.pitch_sharp_cents_threshold))
    return Claim(
        type="pitch_sharp",
        category="PITCH",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"median_cents": cents, "threshold_cents": cfg.pitch_sharp_cents_threshold},
        note_index=note["note_index"],
    )


@register("pitch_in_tune", "PITCH", "absolute", "affirming", "note")
def _pitch_in_tune(note: dict, cfg: CoachingConfig) -> Claim | None:
    pct = note.get("pct_in_tune")
    if pct is None or pct < 0.9:
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="pitch_in_tune",
        category="PITCH",
        scope="note",
        basis="absolute",
        direction="affirming",
        start_s=start_s,
        end_s=end_s,
        evidence=float(pct),
        detail={"pct_in_tune": pct},
        note_index=note["note_index"],
    )


@register("pitch_drifting_flat", "PITCH", "absolute", "issue", "note")
def _pitch_drifting_flat(note: dict, cfg: CoachingConfig) -> Claim | None:
    drift = note.get("drift_cents_per_s")
    if drift is None or drift > -cfg.pitch_drift_cents_per_s_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(drift) / (3.0 * cfg.pitch_drift_cents_per_s_threshold))
    return Claim(
        type="pitch_drifting_flat",
        category="PITCH",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"drift_cents_per_s": drift},
        note_index=note["note_index"],
    )


@register("timing_late", "RHYTHM", "absolute", "issue", "note")
def _timing_late(note: dict, cfg: CoachingConfig) -> Claim | None:
    arrival_ms = note.get("arrival_offset_ms")
    if arrival_ms is None or arrival_ms < cfg.timing_late_ms_threshold:
        return None
    start_s, end_s = _note_window(note)
    # §6.2's own instruction: late weighted harder than early.
    evidence = min(1.0, (arrival_ms / cfg.timing_late_ms_threshold - 1.0) * cfg.timing_late_weight / 2.0 + 0.4)
    return Claim(
        type="timing_late",
        category="RHYTHM",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=max(0.0, min(1.0, evidence)),
        detail={"arrival_offset_ms": arrival_ms, "threshold_ms": cfg.timing_late_ms_threshold},
        note_index=note["note_index"],
    )


@register("timing_early", "RHYTHM", "absolute", "issue", "note")
def _timing_early(note: dict, cfg: CoachingConfig) -> Claim | None:
    arrival_ms = note.get("arrival_offset_ms")
    if arrival_ms is None or arrival_ms > -cfg.timing_early_ms_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(arrival_ms) / (2.0 * cfg.timing_early_ms_threshold))
    return Claim(
        type="timing_early",
        category="RHYTHM",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"arrival_offset_ms": arrival_ms, "threshold_ms": -cfg.timing_early_ms_threshold},
        note_index=note["note_index"],
    )


def _vibrato_technique_gated(note: dict, cfg: CoachingConfig) -> float | None:
    """§11.2(5)'s cross-check: the DSP vibrato detector only fires if
    the learned technique score agrees. Returns the gating score, or
    `None` if the technique partition isn't present for this note (in
    which case the DSP measurement is used ungated -- the degraded
    mode §6's own fallback sanctions when F3 is unavailable)."""
    technique = note.get("technique")
    if not technique or technique.get("status") != "ok":
        return None
    per_label = technique.get("per_label", {})
    vibrato = per_label.get("vibrato_tech")
    if vibrato is None:
        return None
    return float(vibrato.get("user_score", 0.0))


@register("vibrato_present", "VOCALIZATION", "absolute", "affirming", "note")
def _vibrato_present(note: dict, cfg: CoachingConfig) -> Claim | None:
    rate = note.get("vibrato_rate_hz")
    if rate is None:
        return None
    gate = _vibrato_technique_gated(note, cfg)
    if gate is not None and gate < cfg.vibrato_technique_gate_threshold:
        return None
    start_s, end_s = _note_window(note)
    in_band = cfg.vibrato_band_min_hz <= rate <= cfg.vibrato_band_max_hz
    return Claim(
        type="vibrato_present",
        category="VOCALIZATION",
        scope="note",
        basis="absolute",
        direction="affirming" if in_band else "neutral",
        start_s=start_s,
        end_s=end_s,
        evidence=1.0 if in_band else 0.6,
        detail={
            "vibrato_rate_hz": rate,
            "vibrato_extent_cents": note.get("vibrato_extent_cents"),
            "band_hz": [cfg.vibrato_band_min_hz, cfg.vibrato_band_max_hz],
            "technique_gate_score": gate,
        },
        note_index=note["note_index"],
    )


@register("onset_glottal", "TECHNIQUE", "absolute", "issue", "note")
def _onset_glottal(note: dict, cfg: CoachingConfig) -> Claim | None:
    if note.get("onset_type") != "glottal":
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="onset_glottal",
        category="TECHNIQUE",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=0.7,
        detail={"onset_type": "glottal", "onset_rise_time_s": note.get("onset_rise_time_s")},
        note_index=note["note_index"],
    )


@register("onset_balanced", "TECHNIQUE", "absolute", "affirming", "note")
def _onset_balanced(note: dict, cfg: CoachingConfig) -> Claim | None:
    if note.get("onset_type") != "balanced":
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="onset_balanced",
        category="TECHNIQUE",
        scope="note",
        basis="absolute",
        direction="affirming",
        start_s=start_s,
        end_s=end_s,
        evidence=0.7,
        detail={"onset_type": "balanced"},
        note_index=note["note_index"],
    )


@register("breath_ran_out_early", "BREATH", "absolute", "issue", "note")
def _breath_ran_out_early(note: dict, cfg: CoachingConfig) -> Claim | None:
    if not note.get("breath_ran_out_early"):
        return None
    start_s, end_s = _note_window(note)
    slope = note.get("breath_decay_slope_db_per_s")
    evidence = min(1.0, abs(slope) / 10.0) if slope is not None else 0.5
    return Claim(
        type="breath_ran_out_early",
        category="BREATH",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"breath_decay_slope_db_per_s": slope},
        note_index=note["note_index"],
    )


@register("formant_instability", "DICTION", "absolute", "issue", "note")
def _formant_instability(note: dict, cfg: CoachingConfig) -> Claim | None:
    std = note.get("formant_stability_std_hz")
    if std is None or std < cfg.formant_instability_std_hz_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, std / (2.0 * cfg.formant_instability_std_hz_threshold))
    return Claim(
        type="formant_instability",
        category="DICTION",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"formant_stability_std_hz": std, "threshold_hz": cfg.formant_instability_std_hz_threshold},
        note_index=note["note_index"],
    )


_ARC_DIRECTIONS = {"falling": "issue", "arc_down": "issue", "rising": "affirming", "arc_up": "affirming"}


@register("dynamic_arc_shape", "EXPRESSION", "absolute", "neutral", "note")
def _dynamic_arc_shape(note: dict, cfg: CoachingConfig) -> Claim | None:
    arc = note.get("dynamic_arc")
    if arc is None or arc not in _ARC_DIRECTIONS:
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="dynamic_arc_shape",
        category="EXPRESSION",
        scope="note",
        basis="absolute",
        direction=_ARC_DIRECTIONS[arc],
        start_s=start_s,
        end_s=end_s,
        evidence=0.65,
        detail={"dynamic_arc": arc},
        note_index=note["note_index"],
    )


# ---------------------------------------------------------------------------
# Reference-relative (basis="reference") -- requires `ref_*` fields.
# Comparative confidence is bounded by the weaker coverage side; F5
# applies the actual arithmetic. Here we only gate on field presence.
# ---------------------------------------------------------------------------


@register("louder_than_reference", "EXPRESSION", "reference", "neutral", "note")
def _louder_than_reference(note: dict, cfg: CoachingConfig) -> Claim | None:
    delta = note.get("rms_delta_db")
    if delta is None or delta < cfg.rms_delta_loud_db_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, delta / (2.0 * cfg.rms_delta_loud_db_threshold))
    return Claim(
        type="louder_than_reference",
        category="EXPRESSION",
        scope="note",
        basis="reference",
        direction="neutral",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"rms_delta_db": delta},
        note_index=note["note_index"],
    )


@register("quieter_than_reference", "EXPRESSION", "reference", "neutral", "note")
def _quieter_than_reference(note: dict, cfg: CoachingConfig) -> Claim | None:
    delta = note.get("rms_delta_db")
    if delta is None or delta > cfg.rms_delta_quiet_db_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(delta) / abs(2.0 * cfg.rms_delta_quiet_db_threshold))
    return Claim(
        type="quieter_than_reference",
        category="EXPRESSION",
        scope="note",
        basis="reference",
        direction="neutral",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"rms_delta_db": delta},
        note_index=note["note_index"],
    )


@register("vibrato_missing_vs_reference", "VOCALIZATION", "reference", "issue", "note")
def _vibrato_missing_vs_reference(note: dict, cfg: CoachingConfig) -> Claim | None:
    ref_rate = note.get("ref_vibrato_rate_hz")
    user_rate = note.get("vibrato_rate_hz")
    if ref_rate is None or user_rate is not None:
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="vibrato_missing_vs_reference",
        category="VOCALIZATION",
        scope="note",
        basis="reference",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=0.6,
        detail={"ref_vibrato_rate_hz": ref_rate, "user_vibrato_rate_hz": None},
        note_index=note["note_index"],
    )


@register("onset_type_mismatch", "TECHNIQUE", "reference", "neutral", "note")
def _onset_type_mismatch(note: dict, cfg: CoachingConfig) -> Claim | None:
    ref_onset = note.get("ref_onset_type")
    user_onset = note.get("onset_type")
    if ref_onset is None or user_onset is None or ref_onset == user_onset:
        return None
    start_s, end_s = _note_window(note)
    return Claim(
        type="onset_type_mismatch",
        category="TECHNIQUE",
        scope="note",
        basis="reference",
        direction="neutral",
        start_s=start_s,
        end_s=end_s,
        evidence=0.55,
        detail={"ref_onset_type": ref_onset, "user_onset_type": user_onset},
        note_index=note["note_index"],
    )


@register("formant_stability_worse_than_reference", "DICTION", "reference", "issue", "note")
def _formant_stability_worse(note: dict, cfg: CoachingConfig) -> Claim | None:
    deltas = note.get("formant_std_delta_hz_by_formant")
    if not deltas:
        return None
    # `compare_formant_consistency` fills a `None` entry per formant
    # where either side lacks that formant (formants.py's own
    # docstring) -- `deltas` itself being truthy only means at least
    # one formant had both sides, not that every entry is a float.
    # Found live (Session C, F7): a real scored take's third-formant
    # entry was `None`, and bare `max(deltas)` tried to compare it
    # against a float.
    real_deltas = [d for d in deltas if d is not None]
    if not real_deltas:
        return None
    worst = max(real_deltas)
    if worst < cfg.formant_delta_worse_hz_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, worst / (2.0 * cfg.formant_delta_worse_hz_threshold))
    return Claim(
        type="formant_stability_worse_than_reference",
        category="DICTION",
        scope="note",
        basis="reference",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"formant_std_delta_hz_by_formant": deltas, "worst_delta_hz": worst},
        note_index=note["note_index"],
    )


@register("breath_decay_worse_than_reference", "BREATH", "reference", "issue", "note")
def _breath_decay_worse(note: dict, cfg: CoachingConfig) -> Claim | None:
    user_slope = note.get("breath_decay_slope_db_per_s")
    ref_slope = note.get("ref_breath_decay_slope_db_per_s")
    if user_slope is None or ref_slope is None:
        return None
    delta = user_slope - ref_slope
    if delta > cfg.breath_decay_mismatch_db_per_s_threshold:
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(delta) / (2.0 * abs(cfg.breath_decay_mismatch_db_per_s_threshold)))
    return Claim(
        type="breath_decay_worse_than_reference",
        category="BREATH",
        scope="note",
        basis="reference",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"user_slope": user_slope, "ref_slope": ref_slope, "delta": delta},
        note_index=note["note_index"],
    )


# ---------------------------------------------------------------------------
# Co-occurrence composites -- §6.4(b)'s own examples, implemented as
# compositions of the primitive predicates above rather than separate
# hand-written functions, per the plan's instruction ("Note that
# SecondPass's most interesting detectors already WERE compositions").
# ---------------------------------------------------------------------------


@register("breath_support_issue", "BREATH", "absolute", "issue", "note")
def _breath_support_issue(note: dict, cfg: CoachingConfig) -> Claim | None:
    """pitch flattening AND volume fading together (§6.4(b))."""
    drift = note.get("drift_cents_per_s")
    arc = note.get("dynamic_arc")
    flattening = drift is not None and drift < -cfg.pitch_drift_cents_per_s_threshold
    fading = arc in ("falling", "arc_down")
    if not (flattening and fading):
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, abs(drift) / (3.0 * cfg.pitch_drift_cents_per_s_threshold))
    return Claim(
        type="breath_support_issue",
        category="BREATH",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=evidence,
        detail={"drift_cents_per_s": drift, "dynamic_arc": arc},
        note_index=note["note_index"],
    )


@register("registration_strain", "VOCALIZATION", "absolute", "issue", "note")
def _registration_strain(note: dict, cfg: CoachingConfig, high_note_threshold_midi: float | None) -> Claim | None:
    """high note AND sharp AND loud (§6.4(b)). `high_note_threshold_midi`
    is the take's own note-range percentile (self-relative, computed
    once per performance by `generate_claims` -- no absolute vocal
    range assumption)."""
    cents = note.get("median_cents")
    relative_db = note.get("user_rms_relative_db")
    target_midi = note.get("target_midi")
    if cents is None or relative_db is None or target_midi is None or high_note_threshold_midi is None:
        return None
    is_high = target_midi >= high_note_threshold_midi
    is_sharp = cents > cfg.pitch_sharp_cents_threshold
    is_loud = relative_db > cfg.loud_relative_db_threshold
    if not (is_high and is_sharp and is_loud):
        return None
    start_s, end_s = _note_window(note)
    evidence = min(1.0, (cents / (2 * cfg.pitch_sharp_cents_threshold) + relative_db / (2 * cfg.loud_relative_db_threshold)) / 2.0)
    return Claim(
        type="registration_strain",
        category="VOCALIZATION",
        scope="note",
        basis="absolute",
        direction="issue",
        start_s=start_s,
        end_s=end_s,
        evidence=max(0.0, evidence),
        detail={"median_cents": cents, "user_rms_relative_db": relative_db, "target_midi": target_midi, "high_note_threshold_midi": high_note_threshold_midi},
        note_index=note["note_index"],
    )


# ---------------------------------------------------------------------------
# Section / overall scope, absolute basis -- technique density and
# breath-event list live at the top level of the payload, not per note.
# ---------------------------------------------------------------------------


def _technique_density_claims(payload: dict, cfg: CoachingConfig) -> list[Claim]:
    """"You kept the vibrato in the chorus but dropped it in the
    verses" -- computable only from `technique_section_density`
    (§4.6), a top-level field, never per-note. One claim per
    label-with-a-real-spread across sections."""
    density = payload.get("technique_section_density")
    if not density:
        return []
    claims: list[Claim] = []
    for label in TECHNIQUE_LABELS:
        section_values = {s: v.get(label, 0.0) for s, v in density.items() if isinstance(v, dict)}
        if len(section_values) < 2:
            continue
        max_section = max(section_values, key=section_values.get)
        min_section = min(section_values, key=section_values.get)
        spread = section_values[max_section] - section_values[min_section]
        if spread < cfg.technique_label_present_threshold:
            continue
        claims.append(
            Claim(
                type="section_technique_drop",
                category="VOCALIZATION",
                scope="section",
                basis="absolute",
                direction="neutral",
                start_s=0.0,
                end_s=0.0,
                evidence=min(1.0, spread),
                detail={
                    "label": label,
                    "max_section": max_section,
                    "max_value": section_values[max_section],
                    "min_section": min_section,
                    "min_value": section_values[min_section],
                },
                section=max_section,
            )
        )
    return claims


def _breath_event_claims(payload: dict) -> list[Claim]:
    events = payload.get("breath_events") or []
    claims: list[Claim] = []
    for event in events:
        claims.append(
            Claim(
                type="breath_event",
                category="BREATH",
                scope="overall",
                basis="absolute",
                direction="neutral",
                start_s=float(event["start_s"]),
                end_s=float(event["end_s"]),
                evidence=0.5,
                detail={"peak_db": event.get("peak_db")},
            )
        )
    return claims


def _high_note_threshold(midis: list[float], cfg: CoachingConfig) -> float | None:
    if not midis:
        return None
    import numpy as np

    return float(np.percentile(np.asarray(midis, dtype=np.float64), cfg.registration_strain_high_note_percentile))


def generate_claims(payload: dict, cfg: CoachingConfig, chart_notes: list[dict] | None = None) -> list[Claim]:
    """Searches the detector algebra over one performance's frozen
    analysis payload (Session A's exit contract) and returns every
    claim that fired -- unranked, unfiltered. F5 owns evidence ->
    confidence transformation and selection.

    `chart_notes` is optional and comes from the song's chart blob
    (already loaded by the scoring task, keyed by the same
    `note_index` ordering) -- it supplies `target_midi`, which is
    chart data rather than a Session A measurement, purely so
    `registration_strain`'s "high note" leg can be evaluated. Every
    other detector reads only Session A's frozen fields."""
    notes = payload.get("notes", [])
    claims: list[Claim] = []

    midi_by_index: dict[int, float] = {}
    if chart_notes:
        for i, cn in enumerate(chart_notes):
            if "midi" in cn:
                midi_by_index[i] = float(cn["midi"])
    high_note_threshold = _high_note_threshold(list(midi_by_index.values()), cfg)

    for note in notes:
        note = {**note, "target_midi": midi_by_index.get(note["note_index"])}
        for spec in REGISTRY.values():
            if spec.scope != "note":
                continue
            try:
                if spec.name == "registration_strain":
                    claim = spec.fn(note, cfg, high_note_threshold)
                else:
                    claim = spec.fn(note, cfg)
            except KeyError:
                claim = None
            if claim is not None:
                claims.append(claim)

    claims.extend(_technique_density_claims(payload, cfg))
    claims.extend(_breath_event_claims(payload))
    return claims
