"""F4/F5 (IMPLEMENTATION_PLAN_2026-10-09.md, Session B) -- detector
algebra + evidence/confidence/selection, over synthetic frozen-payload
fixtures only. Deterministic layers, same precedent as
tests/test_coaching_dimensions.py: no model, no GPU, no live LLM call.
"""

from __future__ import annotations

import pytest

from elums.coaching.algebra import CATEGORIES, generate_claims, registry_names
from elums.coaching.config import CoachingConfig, load_coaching_config
from elums.coaching.selection import compute_confidence, select_cards


@pytest.fixture()
def cfg() -> CoachingConfig:
    return load_coaching_config()


def _note(note_index: int, **overrides) -> dict:
    base = {
        "note_index": note_index,
        "median_cents": 0.0,
        "pct_in_tune": 0.95,
        "drift_cents_per_s": 0.0,
        "voiced_coverage": 0.9,
        "arrival_offset_ms": 0.0,
        "core_start_s": float(note_index),
        "core_end_s": float(note_index) + 0.8,
        "user_rms_db": -12.0,
        "user_rms_relative_db": 0.0,
        "vibrato_rate_hz": None,
        "vibrato_extent_cents": None,
        "scoop_cents": None,
        "envelope_shape": None,
        "onset_type": None,
        "onset_rise_time_s": None,
        "breath_ran_out_early": False,
        "breath_decay_slope_db_per_s": None,
        "dynamic_arc": None,
        "formant_stability_std_hz": None,
        "formant_std_hz_by_formant": None,
    }
    base.update(overrides)
    return base


def _payload(notes: list[dict], **top_level) -> dict:
    payload = {
        "offset_s": 0.0,
        "voiced_overlap_s": 10.0,
        "octave_shift_semitones": 0,
        "has_reference_comparison": False,
        "has_technique_comparison": False,
        "technique_section_density": None,
        "breath_events": [],
        "notes": notes,
    }
    payload.update(top_level)
    return payload


class TestRegistry:
    def test_every_registered_detector_has_a_valid_category(self, cfg):
        assert registry_names()  # non-empty
        from elums.coaching.algebra import REGISTRY

        for spec in REGISTRY.values():
            assert spec.category in CATEGORIES

    def test_renaming_a_claim_type_is_visible_via_the_registry(self, cfg):
        assert "pitch_flat" in registry_names()
        assert "breath_support_issue" in registry_names()
        assert "registration_strain" in registry_names()


class TestPrimitiveDetectors:
    def test_flat_note_fires_pitch_flat_with_matching_detail(self, cfg):
        notes = [_note(0, median_cents=-40.0)]
        claims = generate_claims(_payload(notes), cfg)
        flat = [c for c in claims if c.type == "pitch_flat"]
        assert len(flat) == 1
        assert flat[0].detail["median_cents"] == -40.0
        assert flat[0].category == "PITCH"

    def test_in_tune_note_does_not_also_fire_flat_or_sharp(self, cfg):
        notes = [_note(0, median_cents=5.0)]
        claims = generate_claims(_payload(notes), cfg)
        assert not any(c.type in ("pitch_flat", "pitch_sharp") for c in claims)

    def test_late_arrival_fires_timing_late(self, cfg):
        notes = [_note(0, arrival_offset_ms=120.0)]
        claims = generate_claims(_payload(notes), cfg)
        assert any(c.type == "timing_late" for c in claims)

    def test_breath_co_occurrence_requires_both_legs(self, cfg):
        # Flattening alone -- no fade -- should NOT fire the composite.
        notes = [_note(0, drift_cents_per_s=-30.0, dynamic_arc="rising")]
        claims = generate_claims(_payload(notes), cfg)
        assert not any(c.type == "breath_support_issue" for c in claims)

        # Both legs together -- fires.
        notes = [_note(0, drift_cents_per_s=-30.0, dynamic_arc="falling")]
        claims = generate_claims(_payload(notes), cfg)
        support_claims = [c for c in claims if c.type == "breath_support_issue"]
        assert len(support_claims) == 1
        assert support_claims[0].detail["drift_cents_per_s"] == -30.0
        assert support_claims[0].detail["dynamic_arc"] == "falling"

    def test_registration_strain_needs_high_sharp_and_loud_together(self, cfg):
        notes = [
            _note(0, median_cents=40.0, user_rms_relative_db=5.0),
            _note(1, median_cents=40.0, user_rms_relative_db=5.0),
            _note(2, median_cents=0.0, user_rms_relative_db=0.0),
        ]
        chart_notes = [{"midi": 72}, {"midi": 72}, {"midi": 50}]
        claims = generate_claims(_payload(notes), cfg, chart_notes=chart_notes)
        strain = [c for c in claims if c.type == "registration_strain"]
        # Both high notes clear the 75th percentile threshold computed
        # over [72, 72, 50]; the low note never can.
        assert len(strain) == 2
        assert all(c.note_index in (0, 1) for c in strain)

    def test_vibrato_gated_off_by_low_technique_score(self, cfg):
        note = _note(0, vibrato_rate_hz=5.5)
        note["technique"] = {"status": "ok", "per_label": {"vibrato_tech": {"user_score": 0.02}}}
        claims = generate_claims(_payload([note]), cfg)
        assert not any(c.type == "vibrato_present" for c in claims)

    def test_vibrato_passes_gate_with_sufficient_technique_score(self, cfg):
        note = _note(0, vibrato_rate_hz=5.5)
        note["technique"] = {"status": "ok", "per_label": {"vibrato_tech": {"user_score": 0.4}}}
        claims = generate_claims(_payload([note]), cfg)
        assert any(c.type == "vibrato_present" for c in claims)

    def test_comparative_claim_absent_without_ref_fields(self, cfg):
        notes = [_note(0, user_rms_db=-6.0)]  # no rms_delta_db key at all
        claims = generate_claims(_payload(notes), cfg)
        assert not any(c.basis == "reference" for c in claims)

    def test_comparative_claim_present_with_ref_fields(self, cfg):
        notes = [_note(0, **{"rms_delta_db": 6.0})]
        claims = generate_claims(_payload(notes), cfg)
        assert any(c.type == "louder_than_reference" for c in claims)

    def test_section_technique_density_claim_needs_real_spread(self, cfg):
        density = {
            "verse": {"vibrato_tech": 0.1},
            "chorus": {"vibrato_tech": 0.8},
        }
        claims = generate_claims(_payload([], technique_section_density=density), cfg)
        drop = [c for c in claims if c.type == "section_technique_drop"]
        assert len(drop) == 1
        assert drop[0].detail["label"] == "vibrato_tech"
        assert drop[0].scope == "section"

    def test_breath_event_claims_come_from_top_level_list(self, cfg):
        events = [{"start_s": 1.0, "end_s": 1.3, "peak_db": -20.0}]
        claims = generate_claims(_payload([], breath_events=events), cfg)
        assert any(c.type == "breath_event" and c.start_s == 1.0 for c in claims)

    def test_claim_detail_reproduces_its_own_predicate(self, cfg):
        """A spot-check matching the plan's own acceptance bar: the
        detail dict's numbers are exactly what the predicate branched
        on, not a post-hoc summary."""
        notes = [_note(0, median_cents=-60.0)]
        claims = generate_claims(_payload(notes), cfg)
        flat = next(c for c in claims if c.type == "pitch_flat")
        assert flat.detail["median_cents"] == notes[0]["median_cents"]
        assert flat.detail["median_cents"] <= -flat.detail["threshold_cents"]


class TestFiveOfSevenCategories:
    def test_a_realistic_take_spans_at_least_five_categories(self, cfg):
        notes = [
            _note(0, median_cents=-40.0),  # PITCH
            _note(1, arrival_offset_ms=90.0),  # RHYTHM
            _note(2, formant_stability_std_hz=300.0),  # DICTION
            _note(3, breath_ran_out_early=True, breath_decay_slope_db_per_s=-12.0),  # BREATH
            _note(4, onset_type="glottal"),  # TECHNIQUE
            _note(5, dynamic_arc="falling"),  # EXPRESSION
        ]
        notes[5]["vibrato_rate_hz"] = 5.0  # VOCALIZATION
        claims = generate_claims(_payload(notes), cfg)
        categories_hit = {c.category for c in claims}
        assert len(categories_hit) >= 5, categories_hit


class TestConfidenceAndSelection:
    def test_comparative_confidence_bounded_by_weaker_coverage_side(self, cfg):
        note_good_user = _note(0, **{"rms_delta_db": 6.0, "ref_voiced_coverage": 0.95})
        note_good_user["voiced_coverage"] = 0.95
        note_poor_ref = {**note_good_user, "ref_voiced_coverage": 0.2}

        claims_good = generate_claims(_payload([note_good_user]), cfg)
        claims_poor = generate_claims(_payload([note_poor_ref]), cfg)
        claim_good = next(c for c in claims_good if c.type == "louder_than_reference")
        claim_poor = next(c for c in claims_poor if c.type == "louder_than_reference")

        conf_good = compute_confidence(claim_good, note_good_user, cfg)
        conf_poor = compute_confidence(claim_poor, note_poor_ref, cfg)
        assert conf_poor < conf_good

    def test_removing_reference_side_degrades_to_absolute_only_without_erroring(self, cfg):
        notes = [_note(0, median_cents=-40.0)]
        claims = generate_claims(_payload(notes), cfg)
        notes_by_index = {0: notes[0]}
        selected = select_cards(claims, notes_by_index, cfg)
        assert all(c.claim.basis == "absolute" for c in selected)

    def test_no_two_same_type_cards_overlap_in_time(self, cfg):
        notes = [_note(i, median_cents=-40.0) for i in range(6)]
        claims = generate_claims(_payload(notes), cfg)
        notes_by_index = {n["note_index"]: n for n in notes}
        selected = select_cards(claims, notes_by_index, cfg)
        same_type: dict[str, list] = {}
        for card in selected:
            same_type.setdefault(card.claim.type, []).append(card)
        for cards in same_type.values():
            for a in cards:
                for b in cards:
                    if a is b:
                        continue
                    assert a.claim.end_s <= b.claim.start_s or b.claim.end_s <= a.claim.start_s

    def test_a_strong_and_weak_take_give_visibly_different_card_sets(self, cfg):
        strong_notes = [_note(i, median_cents=5.0, pct_in_tune=0.97) for i in range(6)]
        weak_notes = [_note(i, median_cents=-45.0, pct_in_tune=0.4) for i in range(6)]

        strong_claims = generate_claims(_payload(strong_notes), cfg)
        weak_claims = generate_claims(_payload(weak_notes), cfg)

        strong_selected = select_cards(strong_claims, {n["note_index"]: n for n in strong_notes}, cfg)
        weak_selected = select_cards(weak_claims, {n["note_index"]: n for n in weak_notes}, cfg)

        strong_types = {c.claim.type for c in strong_selected}
        weak_types = {c.claim.type for c in weak_selected}
        assert strong_types != weak_types
        assert "pitch_flat" in weak_types
        assert "pitch_flat" not in strong_types

    def test_guaranteed_affirming_card_present_when_one_exists(self, cfg):
        notes = [_note(0, median_cents=-40.0), _note(1, median_cents=2.0, pct_in_tune=0.95)]
        claims = generate_claims(_payload(notes), cfg)
        selected = select_cards(claims, {n["note_index"]: n for n in notes}, cfg)
        assert any(c.claim.direction == "affirming" for c in selected)

    def test_low_confidence_claims_are_suppressed(self, cfg):
        # voiced_coverage near zero should push an absolute claim's
        # confidence below the surfacing floor even though evidence is high.
        note = _note(0, median_cents=-200.0)
        note["voiced_coverage"] = 0.01
        claims = generate_claims(_payload([note]), cfg)
        selected = select_cards(claims, {0: note}, cfg)
        assert not any(c.claim.type == "pitch_flat" for c in selected)
