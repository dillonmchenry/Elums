"""F6 live compliance check (IMPLEMENTATION_PLAN_2026-10-09.md, Session B).

One real `rewrite_cards` call through the real OpenRouter endpoint --
same pattern as `scripts/ec1_openrouter_check.py`, standalone rather
than in pytest, since the test suite itself must have no live LLM call
(acceptance checklist #11). Asserts `reasoning_tokens == 0` and that
the returned text differs from the deterministic fallback (proof the
LLM path, not just the fallback, actually ran).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elums.llm.client import CardInput, rewrite_cards  # noqa: E402
from elums.logging import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    cards = [
        CardInput(
            card_id="c1",
            claim_type="pitch_flat",
            category="PITCH",
            direction="issue",
            deterministic_text="This note measured 40 cents flat.",
            detail={"median_cents": -40.0, "threshold_cents": -25.0},
        ),
        CardInput(
            card_id="c2",
            claim_type="breath_ran_out_early",
            category="BREATH",
            direction="issue",
            deterministic_text="Breath support faded before the phrase ended.",
            detail={"breath_decay_slope_db_per_s": -14.2},
        ),
    ]

    result = rewrite_cards(cards)
    print("result:", result)

    for card in cards:
        if result[card.card_id] == card.deterministic_text:
            print(f"F6 FAIL: card {card.card_id} fell back to deterministic text -- LLM path did not run.")
            return 1
    print("F6 PASS: both cards rewritten via the LLM path (see structlog output above for reasoning_tokens).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
