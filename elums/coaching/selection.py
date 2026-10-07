"""F5 -- evidence, confidence, diverse selection (Session B,
IMPLEMENTATION_PLAN_2026-10-09.md).

Takes the unranked `Claim` list F4's algebra produces and turns it
into the final, bounded, diverse card set:

- comparative confidence bounded by the WEAKER of user- and
  reference-side coverage;
- a x1.3 comparative boost on top of that bound;
- inverted certainty for absence claims (confidence that something is
  truly absent rises with coverage, not with "evidence of presence");
- one guaranteed affirming card, if any exists;
- per-type and per-category caps;
- chronological display sort;
- low-confidence suppression.

Deterministic, no model, no GPU -- same discipline as algebra.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from elums.coaching.algebra import Claim
from elums.coaching.config import CoachingConfig

# Claim types whose `evidence` measures the strength of an ABSENCE
# (e.g. "no vibrato detected where the reference has it" is actually
# a presence-of-absence claim already -- these are the ones whose
# raw evidence is better read as "how sure are we nothing is there,"
# which §5.3 says should rise with coverage rather than the predicate
# threshold distance used elsewhere).
ABSENCE_CLAIM_TYPES = frozenset({"vibrato_missing_vs_reference"})


@dataclass(frozen=True)
class SelectedCard:
    claim: Claim
    confidence: float


def _coverage_for(claim: Claim, note: dict | None) -> tuple[float, float | None]:
    """(user_coverage, ref_coverage | None) for the note this claim is
    scoped to. `voiced_coverage`/`ref_voiced_coverage` are Session A's
    frozen per-note fields; section/overall-scope claims (no single
    note) get full coverage by convention -- they're aggregates over
    many notes already, not a single noisy measurement."""
    if note is None:
        return 1.0, 1.0 if claim.basis == "reference" else None
    user_coverage = float(note.get("voiced_coverage", 1.0))
    ref_coverage = float(note["ref_voiced_coverage"]) if note.get("ref_voiced_coverage") is not None else None
    return user_coverage, ref_coverage


def compute_confidence(claim: Claim, note: dict | None, cfg: CoachingConfig) -> float:
    """Evidence -> display confidence, per §5.3's formulas."""
    user_coverage, ref_coverage = _coverage_for(claim, note)

    if claim.type in ABSENCE_CLAIM_TYPES:
        # Inverted certainty: confident the thing is absent exactly
        # when coverage is high (we had a clean enough signal to be
        # sure) -- NOT when the presence-evidence score is high, since
        # that scale doesn't apply to an absence claim at all.
        bound = min(user_coverage, ref_coverage if ref_coverage is not None else user_coverage)
        confidence = bound
    elif claim.basis == "reference":
        bound = min(user_coverage, ref_coverage if ref_coverage is not None else user_coverage)
        confidence = min(1.0, claim.evidence * bound * cfg.comparative_confidence_boost)
    else:
        confidence = claim.evidence * user_coverage

    return max(0.0, min(1.0, confidence))


def _overlaps(a: SelectedCard, b: SelectedCard) -> bool:
    return a.claim.type == b.claim.type and not (a.claim.end_s <= b.claim.start_s or b.claim.end_s <= a.claim.start_s)


def select_cards(
    claims: list[Claim],
    notes_by_index: dict[int, dict],
    cfg: CoachingConfig,
) -> list[SelectedCard]:
    """Diversity-aware round-robin selection: ranks every claim by
    confidence, then walks categories round-robin (so one loud
    category can't crowd out the other six), applying per-type and
    per-category caps and skipping same-type cards that overlap in
    time. Guarantees at least one affirming card if the candidate pool
    has one. Final order is chronological (`start_s`), not rank
    order -- rank only decides WHICH cards survive."""
    scored: list[SelectedCard] = []
    for claim in claims:
        note = notes_by_index.get(claim.note_index) if claim.note_index is not None else None
        confidence = compute_confidence(claim, note, cfg)
        if confidence < cfg.min_confidence_to_surface:
            continue
        scored.append(SelectedCard(claim=claim, confidence=confidence))

    by_category: dict[str, list[SelectedCard]] = {}
    for card in scored:
        by_category.setdefault(card.claim.category, []).append(card)
    for cards in by_category.values():
        cards.sort(key=lambda c: c.confidence, reverse=True)

    selected: list[SelectedCard] = []
    type_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    category_cursors: dict[str, int] = {cat: 0 for cat in by_category}

    categories_cycle = list(by_category.keys())
    progressed = True
    while progressed and len(selected) < cfg.max_cards_total:
        progressed = False
        for category in categories_cycle:
            if len(selected) >= cfg.max_cards_total:
                break
            if category_counts.get(category, 0) >= cfg.max_cards_per_category:
                continue
            cursor = category_cursors[category]
            pool = by_category[category]
            while cursor < len(pool):
                candidate = pool[cursor]
                cursor += 1
                if type_counts.get(candidate.claim.type, 0) >= cfg.max_cards_per_type:
                    continue
                if any(_overlaps(candidate, existing) for existing in selected):
                    continue
                selected.append(candidate)
                type_counts[candidate.claim.type] = type_counts.get(candidate.claim.type, 0) + 1
                category_counts[category] = category_counts.get(category, 0) + 1
                progressed = True
                break
            category_cursors[category] = cursor

    if cfg.guaranteed_affirming_cards > 0 and not any(c.claim.direction == "affirming" for c in selected):
        affirming_candidates = sorted(
            (c for c in scored if c.claim.direction == "affirming"),
            key=lambda c: c.confidence,
            reverse=True,
        )
        if affirming_candidates:
            best = affirming_candidates[0]
            if len(selected) >= cfg.max_cards_total:
                selected.pop()  # make room -- the guarantee outranks the raw cap
            selected.append(best)

    selected.sort(key=lambda c: c.claim.start_s)
    return selected
