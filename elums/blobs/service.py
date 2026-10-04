"""The DB-aware half of blob storage — upserts the `blobs` row after
`BlobStore.put` writes bytes to disk. Kept separate from `elums/blobs/store.py`
so that module stays a pure filesystem Protocol with no Postgres
dependency (and is trivially unit-testable without a database)."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from elums.blobs.store import BlobRef
from elums.models.blob import Blob


async def record_blob(db: AsyncSession, ref: BlobRef) -> None:
    """Insert the `blobs` row for `ref`, or no-op if it already exists —
    blobs are immutable and content-addressed, so a conflict on `sha256`
    means identical bytes were already stored under this hash."""
    stmt = insert(Blob).values(
        sha256=ref.sha256, size_bytes=ref.size_bytes, content_type=ref.content_type
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["sha256"])
    await db.execute(stmt)
