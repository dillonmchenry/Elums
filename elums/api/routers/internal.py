"""`/internal/blob-authz` — the FastAPI side of Caddy's `forward_auth` for
`/blobs/*`. Deliberately mounted WITHOUT the `/api` prefix: Caddy's own
Caddyfile only proxies `/api/*` and the SPA catch-all to the outside
world, so `/internal/*` is unreachable through the public tunnel even if
Caddy's own in-cluster call to `api:8000/internal/blob-authz` resolves
fine. `api` also publishes no host port, which is the second half of that
guarantee — see IMPLEMENTATION_PLAN_2026-10-03.md M7.

Policy, per the plan's own wording: "allow if the blob is reachable from a
song ... the session may read; allow anonymously if that song is public;
else deny." A blob with no referencing song at all (an orphaned upload
that failed ffprobe validation, or someone probing random hashes) is
denied — there is nothing to be "reachable from".

Caddy forces this to a GET and never consumes a body, so there is no
request to parse — only `X-Forwarded-Uri` (the original `/blobs/...`
path) and the forwarded `Cookie` header matter.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_db
from elums.auth.sessions import get_session_by_token
from elums.config import settings
from elums.models.song import Song, SongVisibility
from elums.models.stem import Stem

router = APIRouter(prefix="/internal", tags=["internal"])

# Must match LocalBlobStore's fanout layout exactly: /blobs/<ab>/<cd>/<sha256>.
_BLOB_URI_RE = re.compile(r"^/blobs/[0-9a-f]{2}/[0-9a-f]{2}/(?P<sha256>[0-9a-f]{64})$")


@router.get("/blob-authz", include_in_schema=False)
async def blob_authz(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    uri = request.headers.get("X-Forwarded-Uri", "")
    match = _BLOB_URI_RE.match(uri.split("?", 1)[0])
    if match is None:
        return Response(status_code=403)
    sha256 = match.group("sha256")

    # A blob is "reachable" either as a song's own source upload, or (M8)
    # as one of that song's separated stems — both grant the same access
    # as the owning song, since a stem is derived from and inherits the
    # visibility of its song, not a separate permission of its own.
    direct = await db.execute(select(Song).where(Song.source_blob_sha256 == sha256))
    via_stem = await db.execute(
        select(Song).join(Stem, Stem.song_id == Song.id).where(Stem.blob_sha256 == sha256)
    )
    songs = list({song.id: song for song in (*direct.scalars(), *via_stem.scalars())}.values())
    if not songs:
        return Response(status_code=403)

    if any(song.visibility is SongVisibility.PUBLIC for song in songs):
        return Response(status_code=204)

    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        return Response(status_code=403)

    session = await get_session_by_token(db, raw_token)
    if session is None:
        return Response(status_code=403)

    if any(song.uploaded_by_user_id == session.user_id for song in songs):
        return Response(status_code=204)

    return Response(status_code=403)
