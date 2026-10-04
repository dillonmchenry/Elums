from __future__ import annotations

import uuid

from pydantic import BaseModel

from elums.models.song import SongVisibility


class SongPublic(BaseModel):
    id: uuid.UUID
    title: str
    source_blob_sha256: str
    visibility: SongVisibility
    uploaded_by_user_id: uuid.UUID | None

    model_config = {"from_attributes": True}
