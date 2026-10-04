"""Request-scoped dependencies. Routers depend on these, never construct
infra clients themselves — see elums/db.py and elums/config.py."""

from __future__ import annotations

from collections.abc import AsyncIterator

import valkey.asyncio as valkey_asyncio
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.errors import ApiError
from elums.auth.sessions import get_session_by_token
from elums.blobs.store import BlobStore, LocalBlobStore
from elums.config import settings
from elums.db import get_db  # re-exported for router convenience
from elums.models.user import User

__all__ = ["get_blob_store", "get_current_user", "get_db", "get_valkey"]

_valkey_pool: valkey_asyncio.Valkey | None = None
_blob_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    global _blob_store
    if _blob_store is None:
        _blob_store = LocalBlobStore(settings.blob_root)
    return _blob_store


def _valkey_client() -> valkey_asyncio.Valkey:
    global _valkey_pool
    if _valkey_pool is None:
        _valkey_pool = valkey_asyncio.from_url(settings.valkey_url, decode_responses=True)
    return _valkey_pool


async def get_valkey() -> AsyncIterator[valkey_asyncio.Valkey]:
    yield _valkey_client()


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        raise ApiError("not_authenticated", "No session cookie.", status_code=401)

    session = await get_session_by_token(db, raw_token)
    if session is None:
        raise ApiError("not_authenticated", "Session is invalid or expired.", status_code=401)

    user = await db.get(User, session.user_id)
    if user is None:  # orphaned session row — shouldn't happen (FK cascade), but don't 500 on it
        raise ApiError("not_authenticated", "Session user no longer exists.", status_code=401)
    return user
