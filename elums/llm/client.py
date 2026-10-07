"""F6 -- LLM card rewriting (Session B, IMPLEMENTATION_PLAN_2026-10-09.md).

One call site only, per §6's reduction 3: card summary rewriting,
batches of <=5 verified claims (§12.2). Everything else listed in
§12.2's ten call sites (section narratives, performance summary,
hypothesis proposal, etc.) is explicitly cut from today's scope.

Per §12.1:
  - model `qwen/qwen3.8-27b`, the only compliant 27B-class endpoint
    that accepts `reasoning: {enabled: false}` without a 400;
  - non-thinking sampling set: temperature=0.7, top_p=0.80, top_k=20,
    presence_penalty=1.5 (OpenRouter's reported defaults are the
    THINKING set -- using those here would be wrong);
  - `provider: {require_parameters: true}` plus a strict
    `response_format` JSON Schema, validated client-side regardless
    (three of sixteen endpoints silently drop structured output);
  - a 2-3 attempt repair loop feeding the validation error back.

Plain httpx + pydantic v2, not the `instructor` package -- this
project's own dependency discipline is "explicit pin per need" (see
pyproject.toml's comments throughout), and the repair loop `instructor`
would provide is ~30 lines without it. Documented here as a deliberate
substitution, not a silent deviation from the plan's own wording.

**The LLM never produces a number that reaches a score.** This client
only ever rewrites `deterministic_text` the caller already computed;
the JSON schema has no numeric field for exactly that reason (§6.4/
§12.4's fairness requirement).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from elums.config import settings

logger = structlog.get_logger()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen3.8-27b"
MAX_REPAIR_ATTEMPTS = 2  # first attempt + up to 2 repairs = 3 total, per §12.1

SAMPLING: dict[str, float | int] = {
    "temperature": 0.7,
    "top_p": 0.80,
    "top_k": 20,
    "presence_penalty": 1.5,
}

# §12.2: "structure every prompt so the invariant block comes first" --
# this is the large constant prefix every call shares, worth more to
# prefix-caching than any later optimization once providers honor it.
INVARIANT_PREFIX = (
    "You are Elums' singing coach copy writer. You rewrite ALREADY-VERIFIED "
    "numeric observations about one sung take into short, encouraging, "
    "specific coaching sentences. You never invent a fact, a number, or a "
    "claim that is not present in the JSON you are given, and you never "
    "produce a number yourself. One sentence per card, plain and direct, "
    "second person ('you'), no clinical jargon, no emoji."
)


class CardRewrite(BaseModel):
    card_id: str
    text: str


class CardRewriteBatch(BaseModel):
    cards: list[CardRewrite]


def _batch_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "card_id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["card_id", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["cards"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class CardInput:
    """What the caller (Session C's card assembly, or a test fixture)
    hands in per card: the claim's stable type/category/direction
    (never rewritten, only used as context) plus the `detail` dict
    F4's algebra already produced, and the deterministic fallback text
    that ships if the LLM path is unavailable or fails validation."""

    card_id: str
    claim_type: str
    category: str
    direction: str
    deterministic_text: str
    detail: dict


def _build_messages(cards: list[CardInput], repair_error: str | None) -> list[dict]:
    claims_payload = [
        {
            "card_id": c.card_id,
            "claim_type": c.claim_type,
            "category": c.category,
            "direction": c.direction,
            "measurements": c.detail,
        }
        for c in cards
    ]
    user_content = (
        "Rewrite each of these verified observations into one short coaching "
        "sentence. Return exactly one entry per card_id, in the same order.\n\n"
        + json.dumps(claims_payload)
    )
    messages = [
        {"role": "system", "content": INVARIANT_PREFIX},
        {"role": "user", "content": user_content},
    ]
    if repair_error:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Your previous reply failed validation: {repair_error}. "
                    "Reply again with ONLY schema-conformant JSON, nothing else."
                ),
            }
        )
    return messages


def _request(messages: list[dict], api_key: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "reasoning": {"enabled": False},
        **SAMPLING,
        "provider": {"require_parameters": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "card_rewrite_batch", "strict": True, "schema": _batch_schema()},
        },
    }
    resp = httpx.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


def rewrite_cards(cards: list[CardInput], request_fn=_request) -> dict[str, str]:
    """Rewrites a batch (<=5 per §12.2) of verified claims into coaching
    copy. Returns `{card_id: text}`, falling back to each card's own
    `deterministic_text` for any card the LLM path couldn't produce --
    no key set, every network attempt failed, or every repair attempt
    still failed schema validation. **Never raises** -- this is the
    "no 500s" contract the plan's own validation bar names.

    `request_fn` is swappable for tests (no live LLM call in the suite,
    per the acceptance checklist) -- production callers never pass it.
    """
    fallback = {c.card_id: c.deterministic_text for c in cards}
    if not cards:
        return fallback

    api_key = settings.openrouter_api_key
    if not api_key:
        logger.info("llm.card_rewrite.no_key", card_count=len(cards))
        return fallback

    repair_error: str | None = None
    last_reason = "unknown"
    for attempt in range(1 + MAX_REPAIR_ATTEMPTS):
        messages = _build_messages(cards, repair_error)
        t0 = time.monotonic()
        try:
            data = request_fn(messages, api_key)
        except httpx.HTTPError as exc:
            # A transport failure isn't a schema problem -- burning
            # repair attempts on it would just repeat the same failure.
            last_reason = str(exc)
            logger.warning("llm.card_rewrite.request_failed", attempt=attempt, reason=last_reason)
            break
        duration_ms = int((time.monotonic() - t0) * 1000)

        usage = data.get("usage", {})
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens")
        logger.info(
            "llm.card_rewrite.call",
            attempt=attempt,
            model=MODEL,
            duration_ms=duration_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=reasoning_tokens,
        )

        try:
            content = data["choices"][0]["message"]["content"]
            parsed = CardRewriteBatch.model_validate_json(content)
        except (KeyError, IndexError, ValidationError, ValueError) as exc:
            repair_error = str(exc)
            last_reason = repair_error
            logger.warning("llm.card_rewrite.validation_failed", attempt=attempt, reason=repair_error)
            continue

        result = dict(fallback)
        for card in parsed.cards:
            if card.card_id in result:
                result[card.card_id] = card.text
        return result

    logger.warning("llm.card_rewrite.fallback_to_deterministic", card_count=len(cards), reason=last_reason)
    return fallback
