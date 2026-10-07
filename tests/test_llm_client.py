"""F6 (IMPLEMENTATION_PLAN_2026-10-09.md, Session B) -- elums/llm/client.py's
repair loop and fallback behavior. No live LLM call (acceptance
checklist #11) -- `rewrite_cards`'s `request_fn` is swapped for a fake
that never touches the network, same spirit as
tests/test_coaching_dimensions.py's "deterministic layers only."
"""

from __future__ import annotations

import json

import pytest

from elums.llm.client import CardInput, rewrite_cards


@pytest.fixture()
def one_card() -> list[CardInput]:
    return [
        CardInput(
            card_id="c1",
            claim_type="pitch_flat",
            category="PITCH",
            direction="issue",
            deterministic_text="This note measured 40 cents flat.",
            detail={"median_cents": -40.0},
        )
    ]


def _ok_response(cards: list[CardInput]) -> dict:
    content = json.dumps({"cards": [{"card_id": c.card_id, "text": f"LLM: {c.deterministic_text}"} for c in cards]})
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 0}},
    }


class TestUnsetKeyDegradesCleanly:
    def test_no_key_returns_deterministic_text_without_calling_request_fn(self, one_card, monkeypatch):
        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "")
        calls = []

        def spy(messages, api_key):
            calls.append((messages, api_key))
            raise AssertionError("should never be called when the key is unset")

        result = rewrite_cards(one_card, request_fn=spy)
        assert result == {"c1": one_card[0].deterministic_text}
        assert calls == []


class TestHappyPath:
    def test_valid_response_overrides_the_deterministic_text(self, one_card, monkeypatch):
        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "fake-key")

        def fake_request(messages, api_key):
            return _ok_response(one_card)

        result = rewrite_cards(one_card, request_fn=fake_request)
        assert result["c1"].startswith("LLM:")


class TestRepairLoop:
    def test_one_malformed_response_then_a_repair_recovers(self, one_card, monkeypatch):
        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "fake-key")
        attempts = []

        def fake_request(messages, api_key):
            attempts.append(messages)
            if len(attempts) == 1:
                return {
                    "choices": [{"message": {"content": "not json at all"}}],
                    "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
                }
            return _ok_response(one_card)

        result = rewrite_cards(one_card, request_fn=fake_request)
        assert len(attempts) == 2
        assert result["c1"].startswith("LLM:")
        # The repair attempt's message list carries the validation error back.
        assert any("failed validation" in m["content"] for m in attempts[1] if m["role"] == "user")

    def test_every_repair_attempt_failing_falls_back_to_deterministic_text(self, one_card, monkeypatch):
        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "fake-key")
        attempts = []

        def always_malformed(messages, api_key):
            attempts.append(messages)
            return {
                "choices": [{"message": {"content": "still not json"}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
            }

        result = rewrite_cards(one_card, request_fn=always_malformed)
        assert len(attempts) == 3  # first attempt + 2 repairs, per MAX_REPAIR_ATTEMPTS
        assert result == {"c1": one_card[0].deterministic_text}

    def test_a_schema_violation_missing_required_field_triggers_repair(self, one_card, monkeypatch):
        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "fake-key")
        attempts = []

        def fake_request(messages, api_key):
            attempts.append(messages)
            if len(attempts) == 1:
                content = json.dumps({"cards": [{"card_id": "c1"}]})  # missing "text"
                return {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"completion_tokens_details": {"reasoning_tokens": 0}},
                }
            return _ok_response(one_card)

        result = rewrite_cards(one_card, request_fn=fake_request)
        assert len(attempts) == 2
        assert result["c1"].startswith("LLM:")


class TestNetworkFailureDoesNotRaise:
    def test_a_transport_error_falls_back_without_burning_repair_attempts(self, one_card, monkeypatch):
        import httpx

        monkeypatch.setattr("elums.config.settings.openrouter_api_key", "fake-key")
        attempts = []

        def failing_request(messages, api_key):
            attempts.append(messages)
            raise httpx.ConnectError("no network")

        result = rewrite_cards(one_card, request_fn=failing_request)
        assert len(attempts) == 1  # transport failure breaks immediately, doesn't retry as a "repair"
        assert result == {"c1": one_card[0].deterministic_text}


class TestEmptyBatch:
    def test_no_cards_returns_empty_without_any_request(self):
        result = rewrite_cards([], request_fn=lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")))
        assert result == {}
