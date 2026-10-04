from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class Session(TimestampMixin, Base):
    """Plain FastAPI sessions, exactly as specified in
    ELUMS_TECHNICAL_APPROACH.md's auth section: a 32-byte
    `secrets.token_urlsafe` token handed to the client, SHA-256 hashed at
    rest here (never the raw token — this table is not useful to an
    attacker who reads the DB), revoked by DELETE (no `revoked_at`
    column: a dead session is a deleted row, not a soft-deleted one)."""

    __tablename__ = "sessions"

    id = uuidv7_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")
