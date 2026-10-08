"""F4->F5->F6 wiring (elums/coaching/cards.py) -- the published
card schema Session C consumes. `use_llm=False` throughout: no live
LLM call in the suite (acceptance checklist #11); F6's own repair/
fallback behavior is covered by tests/test_llm_client.py.
"""

from __future__ import annotations

from elums.coaching.cards import apply_section_seek_times, build_cards
from elums.coaching.config import load_coaching_config


def _note(note_index: int, **overrides) -> dict:
    base = {
        "note_index": note_index,
        "median_cents": -40.0,
        "pct_in_tune": 0.5,
        "drift_cents_per_s": 0.0,
        "voiced_coverage": 0.9,
        "arrival_offset_ms": 0.0,
        "core_start_s": float(note_index),
        "core_end_s": float(note_index) + 0.8,
        "user_rms_db": -12.0,
        "user_rms_relative_db": 0.0,
    }
    base.update(overrides)
    return base


class TestCardSchema:
    def test_cards_round_trip_registry_names_only(self):
        from elums.coaching.algebra import registry_names

        notes = [_note(0), _note(1, median_cents=5.0, pct_in_tune=0.95)]
        cards = build_cards({"notes": notes, "breath_events": []}, use_llm=False)
        assert cards
        names = registry_names()
        for card in cards:
            assert card.type in names

    def test_deterministic_text_is_non_empty_and_numeric_grounded(self):
        notes = [_note(0)]
        cards = build_cards({"notes": notes, "breath_events": []}, use_llm=False)
        flat_card = next(c for c in cards if c.type == "pitch_flat")
        assert "-40" in flat_card.text
        assert flat_card.detail["median_cents"] == -40.0

    def test_no_llm_mode_never_imports_or_calls_rewrite(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("rewrite_cards should not be called when use_llm=False")

        monkeypatch.setattr("elums.coaching.cards.rewrite_cards", boom)
        notes = [_note(0)]
        cards = build_cards({"notes": notes, "breath_events": []}, use_llm=False)
        assert cards


class TestSectionSeekTimes:
    """F7 (Session C): §9.2's owner decision -- section-scope cards seek
    to the chart's own section start time, matched by label."""

    def test_section_card_resolves_to_matching_section_start(self):
        payload = {
            "notes": [],
            "breath_events": [],
            "technique_section_density": {
                "verse": {"vibrato_tech": 0.05},
                "chorus": {"vibrato_tech": 0.9},
            },
        }
        cards = build_cards(payload, use_llm=False)
        drop_cards = [c for c in cards if c.type == "section_technique_drop"]
        assert drop_cards
        sections = [
            {"label": "verse", "start_s": 0.0, "end_s": 30.0},
            {"label": "chorus", "start_s": 30.0, "end_s": 60.0},
        ]
        resolved = apply_section_seek_times(drop_cards, sections)
        card = resolved[0]
        assert card.start_s == sections[1 if card.section == "chorus" else 0]["start_s"]
        assert card.end_s == card.start_s

    def test_note_scope_cards_are_untouched(self):
        notes = [_note(0)]
        cards = build_cards({"notes": notes, "breath_events": []}, use_llm=False)
        resolved = apply_section_seek_times(cards, [{"label": "verse", "start_s": 5.0, "end_s": 10.0}])
        for original, after in zip(cards, resolved):
            assert original.start_s == after.start_s
            assert original.end_s == after.end_s

    def test_unmatched_section_label_leaves_card_unchanged(self):
        payload = {
            "notes": [],
            "breath_events": [],
            "technique_section_density": {
                "verse": {"vibrato_tech": 0.05},
                "chorus": {"vibrato_tech": 0.9},
            },
        }
        cards = build_cards(payload, use_llm=False)
        drop_cards = [c for c in cards if c.type == "section_technique_drop"]
        resolved = apply_section_seek_times(drop_cards, [])  # no sections known at all
        assert resolved[0].start_s == drop_cards[0].start_s == 0.0
