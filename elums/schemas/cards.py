"""F7 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): the HTTP-facing
mirror of `elums.coaching.cards.CardPublic` — a plain pydantic model so
FastAPI can declare `response_model` and the OpenAPI client can
generate a typed `CardSchema`. Field-for-field identical to
`CardPublic`; this module adds no behavior of its own.
"""

from __future__ import annotations

from pydantic import BaseModel


class CardSchema(BaseModel):
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
