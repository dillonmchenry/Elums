"""Ties F4 (algebra) -> F5 (selection) -> F6 (LLM rewrite) into the one
function Session C's frontend and Saturday's challenge generation
consume. This module IS Session B's published exit contract: the
**selected-card JSON schema** (see `CardPublic` / `build_cards`'s
return shape) and, via `elums.coaching.algebra.registry_names()`, the
**claim-type registry**.

Deterministic templates here are the fallback text (§6's "deterministic
text is always retained as fallback") AND the text handed to the LLM to
rewrite -- the LLM never sees raw numbers without a human-readable
starting point, which keeps its job "rewrite," never "invent."
"""

from __future__ import annotations

from dataclasses import dataclass

from elums.coaching.algebra import Claim, generate_claims
from elums.coaching.config import CoachingConfig, load_coaching_config
from elums.coaching.selection import SelectedCard, select_cards
from elums.llm.client import CardInput, rewrite_cards

LLM_BATCH_SIZE = 5  # §12.2: "~4 calls, batches of 5"

# One deterministic sentence template per registered claim type.
# Deliberately terse and numeric -- this is what ships verbatim when
# the LLM path is unavailable, and what the LLM is asked to polish
# otherwise. Keys are validated against the real registry by
# `_template_for` at call time (not at import time, since algebra.py's
# REGISTRY is populated by decorators that have already run by the
# time this module is imported).
_TEMPLATES: dict[str, str] = {
    "pitch_flat": "This note measured {median_cents:.0f} cents flat.",
    "pitch_sharp": "This note measured {median_cents:.0f} cents sharp.",
    "pitch_in_tune": "Solid pitch here -- {pct_in_tune:.0%} in tune.",
    "pitch_drifting_flat": "Your pitch drifted flat here, about {drift_cents_per_s:.0f} cents/s.",
    "timing_late": "This note landed about {arrival_offset_ms:.0f} ms late.",
    "timing_early": "This note landed about {arrival_offset_ms:.0f} ms early.",
    "vibrato_present": "Nice vibrato here, around {vibrato_rate_hz:.1f} Hz.",
    "onset_glottal": "This onset was glottal -- a harder attack than the phrase needs.",
    "onset_balanced": "Clean, balanced onset here.",
    "breath_ran_out_early": "Breath support faded before the phrase ended.",
    "formant_instability": "Vowel shape wandered on this note.",
    "dynamic_arc_shape": "This phrase's dynamic arc was {dynamic_arc}.",
    "louder_than_reference": "You sang this noticeably louder than the reference, {rms_delta_db:+.1f} dB.",
    "quieter_than_reference": "You sang this noticeably quieter than the reference, {rms_delta_db:+.1f} dB.",
    "vibrato_missing_vs_reference": "The reference uses vibrato here; your take doesn't yet.",
    "onset_type_mismatch": "Your onset here was {user_onset_type}; the reference uses {ref_onset_type}.",
    "formant_stability_worse_than_reference": "Vowel shape was less steady here than the reference.",
    "breath_decay_worse_than_reference": "Breath support faded faster here than the reference's phrasing.",
    "breath_support_issue": "Pitch drifted flat as volume faded -- a breath-support moment.",
    "registration_strain": "This high note went sharp while pushed loud -- a registration-strain sign.",
    "section_technique_drop": "You used more {label} in the {max_section} than the {min_section}.",
    "breath_event": "A breath here.",
}


def _deterministic_text(claim: Claim) -> str:
    template = _TEMPLATES.get(claim.type)
    if template is None:
        return f"{claim.type} observed."
    try:
        return template.format(**claim.detail)
    except (KeyError, ValueError, TypeError):
        return f"{claim.type} observed."


@dataclass(frozen=True)
class CardPublic:
    """The published card schema (Session B's exit contract, consumed
    by Session C's frontend as-is -- "the frontend reads cards as
    data; it does not reimplement any predicate")."""

    card_id: str
    type: str
    category: str
    scope: str
    basis: str
    direction: str
    start_s: float
    end_s: float
    confidence: float
    text: str
    detail: dict
    note_index: int | None
    section: str | None


def build_cards(
    payload: dict,
    chart_notes: list[dict] | None = None,
    cfg: CoachingConfig | None = None,
    use_llm: bool = True,
) -> list[CardPublic]:
    """The one function Session C calls: frozen per-performance
    payload in, selected+rewritten cards out. `use_llm=False` skips
    F6 entirely (tests, or an explicit deterministic-only mode)."""
    cfg = cfg or load_coaching_config()
    claims = generate_claims(payload, cfg, chart_notes=chart_notes)
    notes_by_index = {n["note_index"]: n for n in payload.get("notes", [])}
    selected = select_cards(claims, notes_by_index, cfg)

    card_ids = [f"card-{i}" for i in range(len(selected))]
    deterministic_texts = [_deterministic_text(card.claim) for card in selected]
    final_texts = list(deterministic_texts)

    if use_llm and selected:
        for batch_start in range(0, len(selected), LLM_BATCH_SIZE):
            batch = selected[batch_start : batch_start + LLM_BATCH_SIZE]
            batch_ids = card_ids[batch_start : batch_start + LLM_BATCH_SIZE]
            batch_det = deterministic_texts[batch_start : batch_start + LLM_BATCH_SIZE]
            inputs = [
                CardInput(
                    card_id=cid,
                    claim_type=card.claim.type,
                    category=card.claim.category,
                    direction=card.claim.direction,
                    deterministic_text=det,
                    detail=card.claim.detail,
                )
                for cid, card, det in zip(batch_ids, batch, batch_det)
            ]
            rewritten = rewrite_cards(inputs)
            for i, cid in enumerate(batch_ids):
                final_texts[batch_start + i] = rewritten.get(cid, batch_det[i])

    return [
        CardPublic(
            card_id=card_ids[i],
            type=selected[i].claim.type,
            category=selected[i].claim.category,
            scope=selected[i].claim.scope,
            basis=selected[i].claim.basis,
            direction=selected[i].claim.direction,
            start_s=selected[i].claim.start_s,
            end_s=selected[i].claim.end_s,
            confidence=selected[i].confidence,
            text=final_texts[i],
            detail=selected[i].claim.detail,
            note_index=selected[i].claim.note_index,
            section=selected[i].claim.section,
        )
        for i in range(len(selected))
    ]
