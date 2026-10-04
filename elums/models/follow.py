from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin


class Follow(TimestampMixin, Base):
    """The social graph — "follows" per ELUMS_TECHNICAL_APPROACH.md's table
    list ("Users, sessions, follows, groups"). Directed, no self-follows,
    composite PK (no separate id: the pair is the identity)."""

    __tablename__ = "follows"
    __table_args__ = (CheckConstraint("follower_id != followee_id", name="ck_follows_no_self_follow"),)

    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
