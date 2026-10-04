"""Content-addressed blob metadata — M7. The bytes themselves live on disk
under `${BLOB_ROOT}` (see elums/blobs/store.py); this row is just the
sha256 -> (size, content_type) record Postgres needs so Caddy's
`/internal/blob-authz` and other callers never have to stat the
filesystem to answer "does this hash exist and what is it".

No `updated_at`: blobs are immutable by construction (same bytes always
hash to the same row), so there is nothing to update.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base


class Blob(Base):
    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
