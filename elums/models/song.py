"""The song catalog — M7. One row per uploaded track; `source_blob_sha256`
points at the original upload in the BlobStore. `IngestJob` (M4) gains a
`song_id` FK here, since M8's separation task takes a `song_id`, not an
ingest-job id — see IMPLEMENTATION_PLAN_2026-10-03.md M8's `separate(song_id)`
task signature.

`visibility` is deliberately the whole authorization model for M7's blob
byte-path: `/internal/blob-authz` allows anonymous reads of any blob
reachable from a `PUBLIC` song, and owner-only reads otherwise. No
per-follower sharing tier yet — that is a credible later addition, not
today's scope.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class SongVisibility(str, enum.Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class Song(TimestampMixin, Base):
    __tablename__ = "songs"
    __table_args__ = (
        # Re-uploading identical bytes as the same user returns the
        # existing song (free, from content addressing) rather than
        # creating a duplicate catalog entry — per the implementation
        # plan's M7 upload-validation note. Different users uploading the
        # same bytes still get their own song (their own title/visibility),
        # sharing only the underlying blob.
        UniqueConstraint("uploaded_by_user_id", "source_blob_sha256", name="uq_songs_owner_blob"),
    )

    id = uuidv7_pk()

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_blob_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("blobs.sha256"), nullable=False, index=True
    )
    visibility: Mapped[SongVisibility] = mapped_column(
        Enum(SongVisibility, name="song_visibility", native_enum=True),
        nullable=False,
        default=SongVisibility.PRIVATE,
    )
