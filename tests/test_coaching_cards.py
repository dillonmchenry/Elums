"""F4->F5->F6 wiring (elums/coaching/cards.py) -- the published
card schema Session C consumes. `use_llm=False` throughout: no live
LLM call in the suite (acceptance checklist #11); F6's own repair/
fallback behavior is covered by tests/test_llm_client.py.
"""

from __future__ import annotations

from elums.coaching.cards import build_cards
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
