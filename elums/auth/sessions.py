"""Session issuance/lookup — the exact scheme from
ELUMS_TECHNICAL_APPROACH.md's auth section: a 32-byte `secrets.token_urlsafe`
token handed to the client, SHA-256 hashed at rest, revoked by DELETE."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from elums.models.session import Session

SESSION_TOKEN_BYTES = 32
SESSION_TTL = timedelta(days=30)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_session(db: DbSession, user_id: uuid.UUID) -> tuple[Session, str]:
    """Returns (session row, raw token) — the raw token is only ever
    available here, right after generation; only its hash is persisted."""
    raw_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    session = Session(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(UTC) + SESSION_TTL,
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def get_session_by_token(db: DbSession, raw_token: str) -> Session | None:
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(Session).where(Session.token_hash == token_hash, Session.expires_at > datetime.now(UTC))
    )
    return result.scalar_one_or_none()


async def delete_session(db: DbSession, session: Session) -> None:
    await db.delete(session)
    await db.flush()
