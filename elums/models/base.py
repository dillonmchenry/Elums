"""Declarative base + the ID convention used by every table from here on.

Convention: every table's primary key is a server-generated UUIDv7
(`uuidv7()`, native to Postgres 18 — see ELUMS_TECHNICAL_APPROACH.md §4),
not a client-generated UUID4 and not a bigserial. UUIDv7 is time-ordered,
so it indexes like a bigserial but is safe to hand to the client directly
(no enumeration, no sequential-ID leakage) and never collides across the
local box and the VM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )


def uuidv7_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
